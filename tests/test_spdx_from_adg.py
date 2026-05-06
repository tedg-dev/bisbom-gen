"""Tests for spdx_from_adg module."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0, str(Path(__file__).parent.parent / "app")
)

from spdx_from_adg import (
    AdgParser,
    AdgSpdxGenerator,
    ComponentResolver,
    SpdxEmitter,
    VendoredVersionDetector,
)
from app.version_detection.strategies import (
    parse_version_file,
    parse_kv_version_file,
    parse_package_json,
    parse_configure_ac,
    parse_cmakelists,
    parse_meson_build,
    parse_pc_in,
    parse_define_version_str,
    parse_define_parts,
    parse_define_any_version,
    parse_header_comment,
    parse_makefile,
)
from app.version_detection.patterns import (
    name_prefixes,
)
from app.spdx.package_resolver import (
    PackageResolver,
)


class _FakeDpkgResolver(PackageResolver):
    """Stub resolver for testing ComponentResolver on macOS."""

    def resolve(self, file_path):
        return None

    def purl_scheme(self):
        return "pkg:deb/ubuntu"

    @property
    def distro_version_qualifier(self):
        return "ubuntu-22.04"


def _fake_dpkg_resolver():
    return _FakeDpkgResolver()


class TestAdgParser(unittest.TestCase):
    """Tests for AdgParser."""

    def _setup_bom_dir(self, td):
        meta = (
            Path(td) / "bom" / "metadata" / "bomsh"
        )
        meta.mkdir(parents=True)
        return meta

    def test_classify_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            treedb = {
                "aaa": {
                    "file_path": (
                        "/usr/lib/x86_64/libssl.so"
                    ),
                },
                "bbb": {
                    "file_path": (
                        "/usr/include/openssl/ssl.h"
                    ),
                },
                "ccc": {
                    "file_path": (
                        "/repos/curl/src/main.c"
                    ),
                },
                "ddd": {
                    "file_path": (
                        "/repos/curl/src/main.o"
                    ),
                    "build_cmd": "gcc -c main.c",
                },
                "eee": {
                    "file_path": (
                        "/usr/lib/x86_64/crtbeginS.o"
                    ),
                },
            }
            (meta / "bomsh_omnibor_treedb").write_text(
                json.dumps(treedb)
            )

            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.parse()

            self.assertEqual(
                len(result["system_lib"]), 1
            )
            self.assertEqual(
                len(result["system_header"]), 1
            )
            self.assertEqual(
                len(result["project_source"]), 1
            )
            self.assertEqual(
                len(result["build_intermediate"]), 1
            )
            self.assertEqual(
                len(result["crt_object"]), 1
            )
            # build_cmd preserved
            self.assertIn(
                "build_cmd",
                result["build_intermediate"][0],
            )

    def test_load_doc_mapping(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            mapping = {"abc123": "doc456"}
            (
                meta / "bomsh_omnibor_doc_mapping"
            ).write_text(json.dumps(mapping))

            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.load_doc_mapping()
            self.assertEqual(
                result["abc123"], "doc456"
            )

    def test_load_doc_mapping_missing(self):
        with tempfile.TemporaryDirectory() as td:
            self._setup_bom_dir(td)
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.load_doc_mapping()
            self.assertEqual(result, {})

    def test_load_raw_logfile_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            sha = "a" * 40
            (
                meta / "bomsh_hook_raw_logfile"
            ).write_text(
                f"outfile: {sha} path: /repo/curl\n"
                "some other line\n"
            )

            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.load_raw_logfile_hashes()
            self.assertEqual(result["/repo/curl"], sha)
            self.assertEqual(len(result), 1)

    def test_load_raw_logfile_missing(self):
        with tempfile.TemporaryDirectory() as td:
            self._setup_bom_dir(td)
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.load_raw_logfile_hashes()
            self.assertEqual(result, {})

    def test_parse_strace_openat_log(self):
        """Parses strace openat log for Java builds."""
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            lines = [
                '1234 openat(AT_FDCWD, '
                '"/repo/src/Main.java", '
                'O_RDONLY) = 3',
                '1234 openat(AT_FDCWD, '
                '"/repo/target/Main.class", '
                'O_WRONLY|O_CREAT) = 4',
                '1234 openat(AT_FDCWD, '
                '"/missing/Nope.java", '
                'O_RDONLY) = -1 ENOENT',
                '1234 openat(AT_FDCWD, '
                '"/m2/repo/guava.jar", '
                'O_RDONLY) = 5',
            ]
            (meta / "strace_java_logfile").write_text(
                "\n".join(lines) + "\n"
            )
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.parse_strace_openat_log()
            # 3 successful opens, 1 failed (ENOENT)
            self.assertEqual(len(result), 3)
            self.assertIn(
                "/repo/src/Main.java", result
            )
            self.assertIn(
                "/repo/target/Main.class", result
            )
            self.assertIn(
                "/m2/repo/guava.jar", result
            )
            # Failed open excluded
            self.assertNotIn(
                "/missing/Nope.java", result
            )

    def test_parse_strace_openat_log_missing(self):
        """Returns empty set when log doesn't exist."""
        with tempfile.TemporaryDirectory() as td:
            self._setup_bom_dir(td)
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.parse_strace_openat_log()
            self.assertEqual(result, set())

    def test_parse_strace_openat_log_empty(self):
        """Returns empty set for empty log file."""
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            (meta / "strace_java_logfile").write_text("")
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.parse_strace_openat_log()
            self.assertEqual(result, set())

    def test_parse_strace_openat_unfinished(self):
        """Captures files from <unfinished ...> lines."""
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            lines = [
                '187 openat(AT_FDCWD, '
                '"/repo/src/App.java", '
                'O_RDONLY <unfinished ...>',
                '187 <... openat resumed>) = 88',
                '187 openat(AT_FDCWD, '
                '"/repo/src/Util.java", '
                'O_RDONLY) = 5',
                '187 openat(AT_FDCWD, '
                '"/nope/Missing.java", '
                'O_RDONLY <unfinished ...>',
                '187 <... openat resumed>) = -1',
            ]
            (meta / "strace_java_logfile").write_text(
                "\n".join(lines) + "\n"
            )
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.parse_strace_openat_log()
            self.assertIn(
                "/repo/src/App.java", result
            )
            self.assertIn(
                "/repo/src/Util.java", result
            )
            # unfinished that later failed — but we
            # can't correlate resume lines to start
            # lines, so unfinished paths are included
            # optimistically.  Only paths that ALSO
            # have an explicit = -1 are removed.
            self.assertIn(
                "/nope/Missing.java", result
            )

    def test_parse_strace_only_failed(self):
        """Path only seen as failed is excluded."""
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            lines = [
                '1 openat(AT_FDCWD, '
                '"/gone/X.java", '
                'O_RDONLY) = -1 ENOENT',
            ]
            (meta / "strace_java_logfile").write_text(
                "\n".join(lines) + "\n"
            )
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.parse_strace_openat_log()
            self.assertNotIn(
                "/gone/X.java", result
            )

    def test_get_jar_source_files_basic(self):
        """Extracts sources for project JARs."""
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            treedb = {
                "jar_sha": {
                    "file_path": (
                        "/repos/myapp/target/app.jar"
                    ),
                    "hash_tree": ["cls_sha"],
                },
                "cls_sha": {
                    "file_path": (
                        "/repos/myapp/target/"
                        "classes/App.class"
                    ),
                    "hash_tree": ["src_sha"],
                },
                "src_sha": {
                    "file_path": (
                        "/repos/myapp/src/App.java"
                    ),
                },
            }
            (meta / "bomsh_omnibor_treedb").write_text(
                json.dumps(treedb)
            )
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.get_jar_source_files()
            self.assertIn(
                "myapp/target/app.jar", result
            )
            sources = result["myapp/target/app.jar"]
            paths = [s["file_path"] for s in sources]
            self.assertTrue(
                any("App.java" in p for p in paths)
            )
            self.assertTrue(
                any("App.class" in p for p in paths)
            )

    def test_get_jar_source_files_skips_test_jars(self):
        """Excludes test JARs and non-project JARs."""
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            treedb = {
                "test_jar": {
                    "file_path": (
                        "/repos/myapp/target/"
                        "app-tests.jar"
                    ),
                    "hash_tree": ["c1"],
                },
                "test_cls_jar": {
                    "file_path": (
                        "/repos/myapp/target/"
                        "test-classes/Test.jar"
                    ),
                    "hash_tree": ["c2"],
                },
                "system_jar": {
                    "file_path": "/usr/lib/rt.jar",
                    "hash_tree": ["c3"],
                },
                "no_tree": {
                    "file_path": (
                        "/repos/myapp/target/x.jar"
                    ),
                },
                "test_dir_jar": {
                    "file_path": (
                        "/repos/myapp/target/test/"
                        "foo.jar"
                    ),
                    "hash_tree": ["c4"],
                },
                "c1": {"file_path": "/f1"},
                "c2": {"file_path": "/f2"},
                "c3": {"file_path": "/f3"},
                "c4": {"file_path": "/f4"},
            }
            (meta / "bomsh_omnibor_treedb").write_text(
                json.dumps(treedb)
            )
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.get_jar_source_files()
            self.assertEqual(len(result), 0)

    def test_get_jar_source_files_missing_class(self):
        """Handles class SHA not in treedb."""
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            treedb = {
                "jar_sha": {
                    "file_path": (
                        "/repos/myapp/target/app.jar"
                    ),
                    "hash_tree": ["missing_cls"],
                },
            }
            (meta / "bomsh_omnibor_treedb").write_text(
                json.dumps(treedb)
            )
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.get_jar_source_files()
            # JAR has no resolvable sources
            self.assertEqual(len(result), 0)

    def test_get_jar_source_files_no_source_tree(self):
        """Class without hash_tree still included."""
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            treedb = {
                "jar_sha": {
                    "file_path": (
                        "/repos/myapp/target/app.jar"
                    ),
                    "hash_tree": ["cls_sha"],
                },
                "cls_sha": {
                    "file_path": (
                        "/repos/myapp/target/"
                        "classes/App.class"
                    ),
                },
            }
            (meta / "bomsh_omnibor_treedb").write_text(
                json.dumps(treedb)
            )
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.get_jar_source_files()
            self.assertIn(
                "myapp/target/app.jar", result
            )
            # Only the class file, no source
            sources = result["myapp/target/app.jar"]
            self.assertEqual(len(sources), 1)
            self.assertIn(
                "App.class",
                sources[0]["file_path"],
            )

    def test_classify_empty_filepath(self):
        """Entries with empty file_path are skipped."""
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            treedb = {
                "aaa": {"file_path": ""},
                "bbb": {},
            }
            (meta / "bomsh_omnibor_treedb").write_text(
                json.dumps(treedb)
            )
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.parse()
            total = sum(
                len(v) for v in result.values()
            )
            self.assertEqual(total, 0)

    def test_classify_static_lib(self):
        """Static .a files under /usr/lib are system_lib."""
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            treedb = {
                "aaa": {
                    "file_path": (
                        "/usr/lib/x86_64/libfoo.a"
                    ),
                },
            }
            (meta / "bomsh_omnibor_treedb").write_text(
                json.dumps(treedb)
            )
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.parse()
            self.assertEqual(
                len(result["system_lib"]), 1
            )

    def test_classify_other_system_file(self):
        """Files outside /usr/lib, /usr/include, repos."""
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            treedb = {
                "aaa": {
                    "file_path": "/opt/custom/lib.h",
                },
            }
            (meta / "bomsh_omnibor_treedb").write_text(
                json.dumps(treedb)
            )
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.parse()
            self.assertEqual(
                len(result["system_header"]), 1
            )


class TestComponentResolver(unittest.TestCase):
    """Tests for ComponentResolver."""

    def _write_metadata(self, td, metadata):
        path = Path(td) / "component_metadata.json"
        path.write_text(json.dumps(metadata))
        return str(path)

    def _base_metadata(self):
        return {
            "distro": "Ubuntu 22.04.5 LTS",
            "gcc_version": "gcc (Ubuntu 11.4.0) 11.4.0",
            "repo_version": "8.19.0-DEV",
            "pkg_metadata": {},
            "file_to_pkg": {},
            "unresolved_files": [],
        }

    def _base_dynlibs(self):
        return {
            "binary": "/repos/curl/src/.libs/curl",
            "direct_needed": ["libssl.so.3"],
            "dynamic_libs": {
                "libssl.so.3": {
                    "path": "/lib/libssl.so.3",
                    "real_path": "/lib/libssl.so.3",
                    "direct": True,
                    "dpkg_package": "libssl3",
                    "source": "openssl",
                    "metadata": {
                        "Package": "libssl3",
                        "Version": "3.0.2-0ubuntu1.21",
                        "Source": "openssl",
                        "Maintainer": "Ubuntu Developers",
                        "Homepage": "https://www.openssl.org/",
                        "Architecture": "amd64",
                    },
                },
                "libcrypto.so.3": {
                    "path": "/lib/libcrypto.so.3",
                    "real_path": "/lib/libcrypto.so.3",
                    "direct": False,
                    "dpkg_package": "libssl3",
                    "source": "openssl",
                    "metadata": {
                        "Package": "libssl3",
                        "Version": "3.0.2-0ubuntu1.21",
                        "Source": "openssl",
                        "Maintainer": "Ubuntu Developers",
                        "Homepage": "https://www.openssl.org/",
                        "Architecture": "amd64",
                    },
                },
                "libz.so.1": {
                    "path": "/lib/libz.so.1",
                    "real_path": "/lib/libz.so.1",
                    "direct": True,
                    "dpkg_package": "zlib1g",
                    "source": "zlib",
                    "metadata": {
                        "Package": "zlib1g",
                        "Version": "1:1.2.11.dfsg-2ubuntu9.2",
                        "Source": "zlib",
                        "Maintainer": "Ubuntu Developers",
                        "Homepage": "http://zlib.net/",
                        "Architecture": "amd64",
                    },
                },
            },
            "libcurl_needed": [],
        }

    def test_resolve_dynamic_components(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path, resolver=_fake_dpkg_resolver())

            dynlib_path = Path(td) / "dynamic_libs.json"
            dynlib_path.write_text(
                json.dumps(self._base_dynlibs())
            )
            resolver.load_dynamic_libs(str(dynlib_path))
            components = (
                resolver.resolve_dynamic_components()
            )
            self.assertEqual(len(components), 2)
            names = [c["name"] for c in components]
            self.assertIn("libssl3", names)
            self.assertIn("zlib1g", names)

    def test_direct_flag(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path, resolver=_fake_dpkg_resolver())

            dynlib_path = Path(td) / "dynamic_libs.json"
            dynlib_path.write_text(
                json.dumps(self._base_dynlibs())
            )
            resolver.load_dynamic_libs(str(dynlib_path))
            components = (
                resolver.resolve_dynamic_components()
            )
            ssl = [c for c in components if c["name"] == "libssl3"][0]
            zlib = [c for c in components if c["name"] == "zlib1g"][0]
            # openssl has one direct soname
            self.assertTrue(ssl["direct"])
            self.assertTrue(zlib["direct"])

    def test_sonames_grouped(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path, resolver=_fake_dpkg_resolver())

            dynlib_path = Path(td) / "dynamic_libs.json"
            dynlib_path.write_text(
                json.dumps(self._base_dynlibs())
            )
            resolver.load_dynamic_libs(str(dynlib_path))
            components = (
                resolver.resolve_dynamic_components()
            )
            ssl = [c for c in components if c["name"] == "libssl3"][0]
            self.assertEqual(len(ssl["sonames"]), 2)
            self.assertIn("libssl.so.3", ssl["sonames"])
            self.assertIn("libcrypto.so.3", ssl["sonames"])

    def test_purl_format(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path, resolver=_fake_dpkg_resolver())

            dynlib_path = Path(td) / "dynamic_libs.json"
            dynlib_path.write_text(
                json.dumps(self._base_dynlibs())
            )
            resolver.load_dynamic_libs(str(dynlib_path))
            components = (
                resolver.resolve_dynamic_components()
            )
            ssl = [c for c in components if c["name"] == "libssl3"][0]
            self.assertIn("pkg:deb/ubuntu/", ssl["purl"])
            self.assertIn("distro=ubuntu-22.04", ssl["purl"])
            self.assertIn("arch=amd64", ssl["purl"])

    def test_cpe_format(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path, resolver=_fake_dpkg_resolver())

            dynlib_path = Path(td) / "dynamic_libs.json"
            dynlib_path.write_text(
                json.dumps(self._base_dynlibs())
            )
            resolver.load_dynamic_libs(str(dynlib_path))
            components = (
                resolver.resolve_dynamic_components()
            )
            ssl = [c for c in components if c["name"] == "libssl3"][0]
            self.assertTrue(
                ssl["cpe23"].startswith("cpe:2.3:a:")
            )
            # CPE uses source package name
            self.assertIn("openssl", ssl["cpe23"])
            self.assertIn("3.0.2", ssl["cpe23"])

    def test_clean_version(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path, resolver=_fake_dpkg_resolver())

            # Epoch removal
            self.assertEqual(
                resolver._clean_version(
                    "1:1.2.11.dfsg-2ubuntu9.2"
                ),
                "1.2.11",
            )
            # dfsg removal
            self.assertEqual(
                resolver._clean_version(
                    "1.4.8+dfsg-3build1"
                ),
                "1.4.8",
            )
            # Simple version
            self.assertEqual(
                resolver._clean_version("3.0.2-0ubuntu1.21"),
                "3.0.2",
            )

    def test_distro_codename(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path, resolver=_fake_dpkg_resolver())
            self.assertEqual(
                resolver.distro_codename,
                "ubuntu-22.04",
            )

    def test_no_dynamic_libs_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path, resolver=_fake_dpkg_resolver())
            # Don't load dynamic libs
            components = (
                resolver.resolve_dynamic_components()
            )
            self.assertEqual(len(components), 0)

    def test_libs_without_version_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path, resolver=_fake_dpkg_resolver())

            dynlibs = {
                "binary": "/curl",
                "direct_needed": [],
                "dynamic_libs": {
                    "ld-linux": {
                        "path": "/lib64/ld-linux.so.2",
                        "real_path": "/lib64/ld-linux.so.2",
                        "direct": False,
                        "dpkg_package": None,
                        "source": "ld-linux",
                        "metadata": {},
                    },
                },
                "libcurl_needed": [],
            }
            dynlib_path = Path(td) / "dynamic_libs.json"
            dynlib_path.write_text(json.dumps(dynlibs))
            resolver.load_dynamic_libs(str(dynlib_path))
            components = (
                resolver.resolve_dynamic_components()
            )
            self.assertEqual(len(components), 0)


class TestSpdxEmitter(unittest.TestCase):
    """Tests for SpdxEmitter."""

    def test_emit_basic_structure(self):
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            bomtrace_version="6.11",
            bomsh_version="0.0.1-abc",
        )
        doc = emitter.emit(
            components=[],
            project_files=[],
            doc_mapping={},
            logfile_hashes={},
        )
        self.assertEqual(
            doc["spdxVersion"], "SPDX-2.3"
        )
        self.assertEqual(
            doc["dataLicense"], "CC0-1.0"
        )
        self.assertIn(
            "omnibor.io",
            doc["documentNamespace"],
        )
        self.assertEqual(
            doc["SPDXID"], "SPDXRef-DOCUMENT"
        )
        # Root package + gcc = 2
        self.assertEqual(len(doc["packages"]), 2)
        # DESCRIBES + BUILD_TOOL_OF = 2
        self.assertEqual(
            len(doc["relationships"]), 2
        )

    def test_emit_vcs_uri_on_root_package(self):
        """vcs_uri sets downloadLocation on root pkg."""
        vcs = (
            "https://github.com/curl/curl/commit/"
            + "a" * 40
        )
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            vcs_uri=vcs,
        )
        doc = emitter.emit(
            components=[],
            project_files=[],
            doc_mapping={},
            logfile_hashes={},
        )
        root_pkg = doc["packages"][0]
        self.assertEqual(
            root_pkg["downloadLocation"], vcs,
        )

    def test_emit_default_download_location(self):
        """Default downloadLocation is NOASSERTION."""
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
        )
        doc = emitter.emit(
            components=[],
            project_files=[],
            doc_mapping={},
            logfile_hashes={},
        )
        root_pkg = doc["packages"][0]
        self.assertEqual(
            root_pkg["downloadLocation"],
            "NOASSERTION",
        )

    def test_emit_with_components(self):
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
        )
        components = [{
            "name": "openssl",
            "version": "3.0.2",
            "supplier": "Ubuntu Developers",
            "homepage": "https://www.openssl.org/",
            "dpkg_packages": ["libssl3"],
            "architecture": "amd64",
            "purl": "pkg:deb/ubuntu/libssl3@3.0.2",
            "cpe23": "cpe:2.3:a:openssl:openssl:3.0.2:*:*:*:*:*:*:*",
            "sonames": ["libssl.so.3", "libcrypto.so.3"],
            "direct": True,
        }]
        doc = emitter.emit(
            components=components,
            project_files=[],
            doc_mapping={},
            logfile_hashes={},
        )
        # Root + openssl + gcc = 3
        self.assertEqual(len(doc["packages"]), 3)
        ssl_pkg = doc["packages"][1]
        self.assertEqual(ssl_pkg["name"], "openssl")
        # Labeled as LIBRARY
        self.assertEqual(
            ssl_pkg["primaryPackagePurpose"],
            "LIBRARY",
        )
        # Comment mentions dynamically linked
        self.assertIn(
            "Dynamically linked (direct)",
            ssl_pkg["comment"],
        )
        self.assertIn(
            "libssl.so.3", ssl_pkg["comment"]
        )
        ref_types = [
            r["referenceType"]
            for r in ssl_pkg["externalRefs"]
        ]
        self.assertIn("purl", ref_types)
        self.assertIn("cpe23Type", ref_types)
        # packageSourceInfo for dpkg library
        self.assertIn(
            "packageSourceInfo", ssl_pkg
        )
        self.assertIn(
            "Installed via dpkg",
            ssl_pkg["packageSourceInfo"],
        )
        self.assertIn(
            "libssl3",
            ssl_pkg["packageSourceInfo"],
        )
        # DYNAMIC_LINK relationship
        rels = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "DYNAMIC_LINK"
        ]
        self.assertEqual(len(rels), 1)

    def test_emit_direct_only_filters_transitive(self):
        """direct_only=True excludes transitive deps."""
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            binary_name="curl",
        )
        components = [
            {
                "name": "glibc",
                "version": "2.35",
                "supplier": "Ubuntu",
                "homepage": "NOASSERTION",
                "dpkg_packages": ["libc6"],
                "architecture": "amd64",
                "purl": "pkg:deb/ubuntu/libc6@2.35",
                "cpe23": "cpe:2.3:a:glibc:glibc:2.35:*:*:*:*:*:*:*",
                "sonames": ["libc.so.6"],
                "direct": True,
            },
            {
                "name": "openssl",
                "version": "3.0.2",
                "supplier": "Ubuntu",
                "homepage": "NOASSERTION",
                "dpkg_packages": ["libssl3"],
                "architecture": "amd64",
                "purl": "pkg:deb/ubuntu/libssl3@3.0.2",
                "cpe23": "cpe:2.3:a:openssl:openssl:3.0.2:*:*:*:*:*:*:*",
                "sonames": ["libssl.so.3"],
                "direct": False,
            },
        ]
        doc = emitter.emit(
            components=components,
            project_files=[],
            doc_mapping={},
            logfile_hashes={},
            direct_only=True,
        )
        # Root + glibc + gcc = 3 (openssl excluded)
        self.assertEqual(len(doc["packages"]), 3)
        names = [p["name"] for p in doc["packages"]]
        self.assertIn("glibc", names)
        self.assertNotIn("openssl", names)
        # Only 1 DYNAMIC_LINK (glibc)
        dyn_rels = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "DYNAMIC_LINK"
        ]
        self.assertEqual(len(dyn_rels), 1)

    def test_emit_static_only_excludes_dynamic(self):
        """static_only=True excludes all dynamic deps."""
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            binary_name="curl",
        )
        components = [
            {
                "name": "libc6",
                "version": "2.35",
                "supplier": "Ubuntu",
                "homepage": "NOASSERTION",
                "dpkg_packages": ["libc6"],
                "architecture": "amd64",
                "purl": "pkg:deb/ubuntu/libc6@2.35",
                "cpe23": "cpe:2.3:a:glibc:glibc:2.35:*:*:*:*:*:*:*",
                "sonames": ["libc.so.6"],
                "direct": True,
            },
        ]
        doc = emitter.emit(
            components=components,
            project_files=[],
            doc_mapping={},
            logfile_hashes={},
            static_only=True,
        )
        # Root only = 1 (libc6 + gcc excluded)
        # static_only excludes dynamic libs AND
        # build tools (CISA Analyzed SBOM).
        self.assertEqual(len(doc["packages"]), 1)
        names = [p["name"] for p in doc["packages"]]
        self.assertNotIn("libc6", names)
        self.assertNotIn("gcc", names)
        # No DYNAMIC_LINK relationships
        dyn_rels = [
            r for r in doc["relationships"]
            if r["relationshipType"]
            == "DYNAMIC_LINK"
        ]
        self.assertEqual(len(dyn_rels), 0)
        # No BUILD_TOOL_OF relationships
        build_rels = [
            r for r in doc["relationships"]
            if r["relationshipType"]
            == "BUILD_TOOL_OF"
        ]
        self.assertEqual(len(build_rels), 0)

    def test_emit_with_omnibor_ref(self):
        sha = "a" * 40
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
        )
        doc = emitter.emit(
            components=[],
            project_files=[],
            doc_mapping={sha: "omnibor_doc_123"},
            logfile_hashes={
                "/repo/src/.libs/curl": sha,
            },
        )
        root = doc["packages"][0]
        gitoid_refs = [
            r for r in root["externalRefs"]
            if "gitoid" in r.get(
                "referenceLocator", ""
            )
        ]
        self.assertEqual(len(gitoid_refs), 1)
        self.assertIn(
            "omnibor_doc_123",
            gitoid_refs[0]["referenceLocator"],
        )

    def test_emit_with_source_files(self):
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
        )
        project_files = [
            {"sha1": "abc", "file_path": "/repos/curl/src/main.c"},
            {"sha1": "def", "file_path": "/repos/curl/src/util.h"},
            {"sha1": "ghi", "file_path": "/repos/curl/Makefile"},
        ]
        doc = emitter.emit(
            components=[],
            project_files=project_files,
            doc_mapping={},
            logfile_hashes={},
        )
        # .c and .h included, Makefile excluded
        self.assertEqual(len(doc["files"]), 2)
        fnames = [
            f["fileName"] for f in doc["files"]
        ]
        self.assertTrue(
            any("main.c" in f for f in fnames)
        )

    def test_creators(self):
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            bomtrace_version="6.11-dirty",
            bomsh_version="0.0.1-abc",
        )
        doc = emitter.emit(
            components=[], project_files=[],
            doc_mapping={}, logfile_hashes={},
        )
        creators = doc["creationInfo"]["creators"]
        self.assertIn(
            "Tool: bomtrace3-6.11-dirty", creators
        )
        self.assertIn(
            "Tool: bomsh-0.0.1-abc", creators
        )
        self.assertTrue(
            any("omnibor-analysis" in c for c in creators)
        )


class TestSpdxEmitterVendored(unittest.TestCase):
    """Tests for vendored/static dependency detection."""

    def _emitter(self, binary_name="redis-server"):
        return SpdxEmitter(
            repo_name="redis",
            repo_version="7.2.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            binary_name=binary_name,
        )

    def test_detect_vendored_groups(self):
        """Files under deps/ are grouped by library."""
        emitter = self._emitter()
        files = [
            {"sha1": "a1", "file_path":
                "/repos/redis/deps/lua/src/lapi.c"},
            {"sha1": "a2", "file_path":
                "/repos/redis/deps/lua/src/lapi.h"},
            {"sha1": "a3", "file_path":
                "/repos/redis/deps/jemalloc/src/arena.c"},
            {"sha1": "a4", "file_path":
                "/repos/redis/src/server.c"},
        ]
        vendored, own = (
            emitter._detect_vendored_groups(files)
        )
        self.assertEqual(sorted(vendored.keys()),
                         ["jemalloc", "lua"])
        self.assertEqual(len(vendored["lua"]), 2)
        self.assertEqual(len(vendored["jemalloc"]), 1)
        self.assertEqual(len(own), 1)
        self.assertEqual(
            own[0]["file_path"],
            "/repos/redis/src/server.c",
        )

    def test_vendored_dirs_patterns(self):
        """All VENDORED_DIRS patterns are detected."""
        emitter = self._emitter()
        files = [
            {"sha1": "a", "file_path":
                "/r/deps/libA/x.c"},
            {"sha1": "b", "file_path":
                "/r/vendor/libB/y.c"},
            {"sha1": "c", "file_path":
                "/r/third_party/libC/z.c"},
            {"sha1": "d", "file_path":
                "/r/thirdparty/libD/w.c"},
            {"sha1": "e", "file_path":
                "/r/external/libE/v.c"},
            {"sha1": "f", "file_path":
                "/r/contrib/libF/u.c"},
        ]
        vendored, own = (
            emitter._detect_vendored_groups(files)
        )
        self.assertEqual(
            sorted(vendored.keys()),
            ["libA", "libB", "libC",
             "libD", "libE", "libF"],
        )
        self.assertEqual(len(own), 0)

    def test_custom_vendored_dirs(self):
        """Custom vendored_dirs override class defaults.

        Nmap-style: the vendored dir IS the library,
        not a container for multiple libraries.
        """
        emitter = SpdxEmitter(
            repo_name="nmap",
            repo_version="7.95",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            binary_name="nmap",
            vendored_dirs=[
                "/liblua/", "/libdnet-stripped/",
                "/nsock/",
            ],
        )
        files = [
            {"sha1": "a1", "file_path":
                "/repos/nmap/liblua/lapi.c"},
            {"sha1": "a2", "file_path":
                "/repos/nmap/liblua/lapi.h"},
            {"sha1": "a3", "file_path":
                "/repos/nmap/libdnet-stripped/src/addr.c"},
            {"sha1": "a4", "file_path":
                "/repos/nmap/nsock/src/nsock_core.c"},
            {"sha1": "a5", "file_path":
                "/repos/nmap/nmap.cc"},
        ]
        vendored, own = (
            emitter._detect_vendored_groups(files)
        )
        self.assertEqual(
            sorted(vendored.keys()),
            ["libdnet-stripped", "liblua", "nsock"],
        )
        self.assertEqual(len(vendored["liblua"]), 2)
        self.assertEqual(
            len(vendored["libdnet-stripped"]), 1,
        )
        self.assertEqual(len(vendored["nsock"]), 1)
        self.assertEqual(len(own), 1)
        self.assertEqual(
            own[0]["file_path"],
            "/repos/nmap/nmap.cc",
        )

    def test_custom_vendored_dirs_with_subdirs(self):
        """Files in subdirs of specific vendored dirs
        still group under the library name."""
        emitter = SpdxEmitter(
            repo_name="nmap",
            repo_version="7.95",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            binary_name="nmap",
            vendored_dirs=["/libssh2/"],
        )
        files = [
            {"sha1": "a1", "file_path":
                "/repos/nmap/libssh2/src/session.c"},
            {"sha1": "a2", "file_path":
                "/repos/nmap/libssh2/src/channel.c"},
            {"sha1": "a3", "file_path":
                "/repos/nmap/libssh2/include/libssh2.h"},
        ]
        vendored, own = (
            emitter._detect_vendored_groups(files)
        )
        self.assertEqual(
            list(vendored.keys()), ["libssh2"],
        )
        self.assertEqual(len(vendored["libssh2"]), 3)
        self.assertEqual(len(own), 0)

    def test_default_vendored_dirs_unaffected(self):
        """Without custom vendored_dirs, defaults work."""
        emitter = self._emitter()
        files = [
            {"sha1": "a1", "file_path":
                "/repos/redis/deps/lua/src/lapi.c"},
        ]
        vendored, own = (
            emitter._detect_vendored_groups(files)
        )
        self.assertEqual(
            list(vendored.keys()), ["lua"],
        )

    def test_emit_creates_vendored_packages(self):
        """Vendored libs become SPDX packages."""
        emitter = self._emitter()
        files = [
            {"sha1": "a1", "file_path":
                "/repos/redis/deps/lua/src/lapi.c"},
            {"sha1": "a2", "file_path":
                "/repos/redis/deps/hiredis/hiredis.c"},
            {"sha1": "a3", "file_path":
                "/repos/redis/src/server.c"},
        ]
        doc = emitter.emit(
            components=[], project_files=files,
            doc_mapping={}, logfile_hashes={},
        )
        names = [p["name"] for p in doc["packages"]]
        # root + gcc + hiredis + lua = 4
        self.assertEqual(len(doc["packages"]), 4)
        self.assertIn("lua", names)
        self.assertIn("hiredis", names)

        # Check STATIC_LINK relationships
        static_rels = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "STATIC_LINK"
        ]
        self.assertEqual(len(static_rels), 2)

        # Vendored packages have LIBRARY purpose
        for pkg in doc["packages"]:
            if pkg["name"] in ("lua", "hiredis"):
                self.assertEqual(
                    pkg["primaryPackagePurpose"],
                    "LIBRARY",
                )
                self.assertIn(
                    "Vendored source compiled",
                    pkg["comment"],
                )
                self.assertIn(
                    "packageSourceInfo",
                    pkg,
                )
                self.assertIn(
                    "Vendored from",
                    pkg["packageSourceInfo"],
                )

    def test_vendored_files_owned_by_lib_package(self):
        """Vendored source files CONTAINS from lib pkg."""
        emitter = self._emitter()
        files = [
            {"sha1": "a1", "file_path":
                "/repos/redis/deps/lua/src/lapi.c"},
            {"sha1": "a2", "file_path":
                "/repos/redis/src/server.c"},
        ]
        doc = emitter.emit(
            components=[], project_files=files,
            doc_mapping={}, logfile_hashes={},
        )
        # Find lua package ID
        lua_pkg = [
            p for p in doc["packages"]
            if p["name"] == "lua"
        ][0]
        lua_id = lua_pkg["SPDXID"]

        # Find CONTAINS rels from lua package
        lua_contains = [
            r for r in doc["relationships"]
            if r["spdxElementId"] == lua_id
            and r["relationshipType"] == "CONTAINS"
        ]
        self.assertEqual(len(lua_contains), 1)

        # Root CONTAINS: server.c (source file) +
        # lua package (vendored containment)
        root_contains = [
            r for r in doc["relationships"]
            if r["spdxElementId"]
            == "SPDXRef-Package-root"
            and r["relationshipType"] == "CONTAINS"
        ]
        self.assertEqual(len(root_contains), 2)

    def test_rust_build_output_not_vendored(self):
        """Rust target/release/deps/ must not match
        vendored /deps/ pattern."""
        emitter = self._emitter()
        files = [
            # Rust build intermediate in target/
            {"sha1": "r1", "file_path":
                "/repos/dura/target/release/deps/"
                "libadler-0ae352ee44010592.rlib"},
            # Project own source
            {"sha1": "r2", "file_path":
                "/repos/dura/src/main.rs"},
        ]
        vendored, own = (
            emitter._detect_vendored_groups(files)
        )
        # .rlib should NOT be in vendored dict
        self.assertEqual(len(vendored), 0)
        # Both files should be in own
        self.assertEqual(len(own), 2)

    def test_is_vendored_requires_vendored_dir_match(
        self,
    ):
        """CONTAINS only emitted when files actually
        reside under a vendored directory pattern."""
        emitter = self._emitter()
        # File NOT in any vendored dir
        files = [
            {"sha1": "x1", "file_path":
                "/repos/redis/src/server.c"},
            {"sha1": "x2", "file_path":
                "/repos/redis/src/networking.c"},
        ]
        doc = emitter.emit(
            components=[], project_files=files,
            doc_mapping={}, logfile_hashes={},
        )
        contains_rels = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "CONTAINS"
            and r["relatedSpdxElement"].startswith(
                "SPDXRef-Package-"
            )
            and r["relatedSpdxElement"]
            != "SPDXRef-Package-root"
        ]
        # No package-level CONTAINS (only file CONTAINS)
        self.assertEqual(len(contains_rels), 0)

    def test_no_vendored_files_no_extra_packages(self):
        """No vendored dirs means no extra packages."""
        emitter = self._emitter()
        files = [
            {"sha1": "a1", "file_path":
                "/repos/redis/src/server.c"},
        ]
        doc = emitter.emit(
            components=[], project_files=files,
            doc_mapping={}, logfile_hashes={},
        )
        # root + gcc only
        self.assertEqual(len(doc["packages"]), 2)
        static_rels = [
            r for r in doc["relationships"]
            if r["relationshipType"] == "STATIC_LINK"
        ]
        self.assertEqual(len(static_rels), 0)


class TestSubComponentSplitting(unittest.TestCase):
    """Tests for sub-component detection in vendored dirs."""

    def _emitter(self):
        return SpdxEmitter(
            repo_name="redis",
            repo_version="7.2.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            binary_name="redis-server",
        )

    def test_split_sub_component_by_version_define(
        self,
    ):
        """Files with own #define VERSION split out."""
        with tempfile.TemporaryDirectory() as td:
            lua_dir = Path(td) / "deps" / "lua" / "src"
            lua_dir.mkdir(parents=True)
            # Parent lib file
            (lua_dir / "lapi.c").write_text(
                '#define LUA_VERSION "Lua 5.1"\n'
            )
            # Sub-component with own version
            (lua_dir / "lua_cjson.c").write_text(
                '#define CJSON_VERSION "2.1.0"\n'
                "int cjson_init() {}\n"
            )
            emitter = self._emitter()
            files = [
                {"sha1": "a1", "file_path":
                    str(lua_dir / "lapi.c")},
                {"sha1": "a2", "file_path":
                    str(lua_dir / "lua_cjson.c")},
            ]
            vendored, own = (
                emitter._detect_vendored_groups(files)
            )
            self.assertIn("lua-cjson", vendored)
            self.assertEqual(
                len(vendored["lua-cjson"]), 1
            )
            # Parent still has its file
            self.assertIn("lua", vendored)
            self.assertEqual(
                len(vendored["lua"]), 1
            )

    def test_sub_component_gets_spdx_package(self):
        """Sub-components become SPDX packages."""
        with tempfile.TemporaryDirectory() as td:
            lua_dir = Path(td) / "deps" / "lua" / "src"
            lua_dir.mkdir(parents=True)
            (lua_dir / "lapi.c").write_text(
                '#define LUA_VERSION "Lua 5.1"\n'
            )
            (lua_dir / "lua_cjson.c").write_text(
                '#define CJSON_VERSION "2.1.0"\n'
            )
            (lua_dir / "lua_cmsgpack.c").write_text(
                '#define LUACMSGPACK_VERSION '
                '"lua-cmsgpack 0.4.0"\n'
            )
            emitter = self._emitter()
            files = [
                {"sha1": "a1", "file_path":
                    str(lua_dir / "lapi.c")},
                {"sha1": "a2", "file_path":
                    str(lua_dir / "lua_cjson.c")},
                {"sha1": "a3", "file_path":
                    str(lua_dir / "lua_cmsgpack.c")},
            ]
            doc = emitter.emit(
                components=[],
                project_files=files,
                doc_mapping={},
                logfile_hashes={},
            )
            names = [
                p["name"] for p in doc["packages"]
            ]
            self.assertIn("lua-cjson", names)
            self.assertIn(
                "lua-luacmsgpack", names
            )
            self.assertIn("lua", names)

            # Sub-components get STATIC_LINK
            static_rels = [
                r for r in doc["relationships"]
                if r["relationshipType"]
                == "STATIC_LINK"
            ]
            # lua + lua-cjson + lua-luacmsgpack = 3
            self.assertEqual(len(static_rels), 3)

    def test_sub_component_version_detected(self):
        """Sub-component version is in SPDX pkg."""
        with tempfile.TemporaryDirectory() as td:
            lua_dir = Path(td) / "deps" / "lua" / "src"
            lua_dir.mkdir(parents=True)
            (lua_dir / "lapi.c").write_text("")
            (lua_dir / "lua_cjson.c").write_text(
                '#define CJSON_VERSION "2.1.0"\n'
            )
            emitter = self._emitter()
            files = [
                {"sha1": "a1", "file_path":
                    str(lua_dir / "lapi.c")},
                {"sha1": "a2", "file_path":
                    str(lua_dir / "lua_cjson.c")},
            ]
            doc = emitter.emit(
                components=[],
                project_files=files,
                doc_mapping={},
                logfile_hashes={},
            )
            cjson_pkg = [
                p for p in doc["packages"]
                if p["name"] == "lua-cjson"
            ][0]
            self.assertEqual(
                cjson_pkg["versionInfo"], "2.1.0"
            )

    def test_split_parent_prefixed_sub_component(
        self,
    ):
        """Sub-components whose prefix starts with
        parent name are still split (e.g. LUA_BITOP
        is lua-bitop, not part of lua)."""
        with tempfile.TemporaryDirectory() as td:
            lua_dir = Path(td) / "deps" / "lua" / "src"
            lua_dir.mkdir(parents=True)
            (lua_dir / "lapi.c").write_text("")
            (lua_dir / "lua_bit.c").write_text(
                '#define LUA_BITOP_VERSION'
                '    "1.0.2"\n'
            )
            emitter = self._emitter()
            files = [
                {"sha1": "a1", "file_path":
                    str(lua_dir / "lapi.c")},
                {"sha1": "a2", "file_path":
                    str(lua_dir / "lua_bit.c")},
            ]
            vendored, own = (
                emitter._detect_vendored_groups(files)
            )
            self.assertIn("lua-bitop", vendored)
            self.assertEqual(
                len(vendored["lua-bitop"]), 1
            )

    def test_no_split_when_prefix_matches_parent(
        self,
    ):
        """Parent's own VERSION define is not split."""
        with tempfile.TemporaryDirectory() as td:
            lua_dir = Path(td) / "deps" / "lua" / "src"
            lua_dir.mkdir(parents=True)
            (lua_dir / "lua.h").write_text(
                '#define LUA_RELEASE "Lua 5.1.5"\n'
                '#define LUA_VERSION_NUM 501\n'
            )
            emitter = self._emitter()
            files = [
                {"sha1": "a1", "file_path":
                    str(lua_dir / "lua.h")},
            ]
            vendored, own = (
                emitter._detect_vendored_groups(files)
            )
            # Should stay as "lua", no sub-split
            self.assertIn("lua", vendored)
            self.assertEqual(len(vendored), 1)

    def test_related_files_follow_sub_component(
        self,
    ):
        """Header files matching sub-component name
        are assigned to the sub-component group."""
        with tempfile.TemporaryDirectory() as td:
            lua_dir = Path(td) / "deps" / "lua" / "src"
            lua_dir.mkdir(parents=True)
            (lua_dir / "lapi.c").write_text("")
            (lua_dir / "lua_cjson.c").write_text(
                '#define CJSON_VERSION "2.1.0"\n'
            )
            (lua_dir / "strbuf.h").write_text(
                "/* string buffer for cjson */\n"
            )
            emitter = self._emitter()
            files = [
                {"sha1": "a1", "file_path":
                    str(lua_dir / "lapi.c")},
                {"sha1": "a2", "file_path":
                    str(lua_dir / "lua_cjson.c")},
                {"sha1": "a3", "file_path":
                    str(lua_dir / "strbuf.h")},
            ]
            vendored, own = (
                emitter._detect_vendored_groups(files)
            )
            # strbuf.h doesn't match "cjson" prefix,
            # so stays with lua parent
            self.assertIn("lua-cjson", vendored)
            self.assertEqual(
                len(vendored["lua-cjson"]), 1
            )
            self.assertIn("lua", vendored)
            self.assertEqual(
                len(vendored["lua"]), 2
            )


class TestVendoredVersionDetector(unittest.TestCase):
    """Tests for VendoredVersionDetector."""

    def test_version_file(self):
        """Detect version from VERSION file."""
        with tempfile.TemporaryDirectory() as td:
            lib_dir = Path(td) / "deps" / "jemalloc"
            src_dir = lib_dir / "src"
            src_dir.mkdir(parents=True)
            (lib_dir / "VERSION").write_text(
                "5.3.0-0-g0\n"
            )
            (src_dir / "arena.c").write_text("")
            det = VendoredVersionDetector()
            ver = det.detect("jemalloc", [
                str(src_dir / "arena.c"),
            ])
            self.assertEqual(ver, "5.3.0")

    def test_header_define_release(self):
        """Detect version from #define LIB_RELEASE."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "lua.h"
            h.write_text(
                '#define LUA_VERSION "Lua 5.1"\n'
                '#define LUA_RELEASE "Lua 5.1.5"\n'
                '#define LUA_VERSION_NUM 501\n'
            )
            det = VendoredVersionDetector()
            ver = det.detect("lua", [str(h)])
            self.assertEqual(ver, "5.1.5")

    def test_header_define_major_minor_patch(self):
        """Detect version from MAJOR/MINOR/PATCH."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "hiredis.h"
            h.write_text(
                "#define HIREDIS_MAJOR 1\n"
                "#define HIREDIS_MINOR 2\n"
                "#define HIREDIS_PATCH 0\n"
            )
            det = VendoredVersionDetector()
            ver = det.detect("hiredis", [str(h)])
            self.assertEqual(ver, "1.2.0")

    def test_header_define_version_major_minor(self):
        """Detect X.Y.Z with RELEASE as PATCH alias."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "lib.h"
            h.write_text(
                "#define XXH_VERSION_MAJOR    0\n"
                "#define XXH_VERSION_MINOR    8\n"
                "#define XXH_VERSION_RELEASE  3\n"
            )
            det = VendoredVersionDetector()
            # RELEASE is treated as PATCH alias
            ver = det.detect("xxhash", [str(h)])
            self.assertEqual(ver, "0.8.3")

    def test_header_comment_version(self):
        """Detect version from header comment."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "linenoise.h"
            h.write_text(
                "/* linenoise.h -- VERSION 1.0\n"
                " * A readline replacement.\n"
                " */\n"
            )
            det = VendoredVersionDetector()
            ver = det.detect("linenoise", [str(h)])
            self.assertEqual(ver, "1.0")

    def test_pc_in_file(self):
        """Detect version from .pc.in file."""
        with tempfile.TemporaryDirectory() as td:
            pc = Path(td) / "hiredis.pc.in"
            pc.write_text(
                "prefix=@PREFIX@\n"
                "Name: hiredis\n"
                "Version: 1.2.0\n"
            )
            h = Path(td) / "hiredis.h"
            h.write_text("/* no version */\n")
            det = VendoredVersionDetector()
            ver = det.detect("hiredis", [str(h)])
            self.assertEqual(ver, "1.2.0")

    def test_no_version_found(self):
        """Return None when no version info exists."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "fpconv_dtoa.h"
            h.write_text("/* no version info */\n")
            det = VendoredVersionDetector()
            ver = det.detect("fpconv", [str(h)])
            self.assertIsNone(ver)

    def test_version_file_unreadable(self):
        """Gracefully handle unreadable VERSION."""
        result = parse_version_file(
            Path("/nonexistent/VERSION")
        )
        self.assertIsNone(result)

    def test_header_unreadable(self):
        """Gracefully handle unreadable header."""
        result = parse_define_version_str(
            "/nonexistent/lib.h", ["LIB"]
        )
        self.assertIsNone(result)
        result = parse_define_parts(
            "/nonexistent/lib.h", ["LIB"]
        )
        self.assertIsNone(result)

    def test_header_comment_unreadable(self):
        """Gracefully handle unreadable header."""
        result = parse_header_comment(
            "/nonexistent/lib.h"
        )
        self.assertIsNone(result)

    def test_pc_in_unreadable(self):
        """Gracefully handle unreadable .pc.in."""
        result = parse_pc_in(
            Path("/nonexistent/lib.pc.in")
        )
        self.assertIsNone(result)

    def test_configure_ac(self):
        """Detect version from AC_INIT in configure.ac."""
        with tempfile.TemporaryDirectory() as td:
            ac = Path(td) / "configure.ac"
            ac.write_text(
                "AC_INIT([libdnet],[1.18.0])\n"
                "AC_CONFIG_SRCDIR([src/addr.c])\n"
            )
            h = Path(td) / "src" / "addr.h"
            h.parent.mkdir()
            h.write_text("/* no version */\n")
            det = VendoredVersionDetector()
            ver = det.detect(
                "libdnet-stripped",
                [str(h)],
            )
            self.assertEqual(ver, "1.18.0")

    def test_cmakelists_project_version(self):
        """Detect version from CMakeLists.txt."""
        with tempfile.TemporaryDirectory() as td:
            cm = Path(td) / "CMakeLists.txt"
            cm.write_text(
                "cmake_minimum_required(VERSION 3.1)\n"
                "project(libssh2 C VERSION 1.11.1)\n"
            )
            h = Path(td) / "lib.h"
            h.write_text("/* no version */\n")
            det = VendoredVersionDetector()
            ver = det.detect("libssh2", [str(h)])
            self.assertEqual(ver, "1.11.1")

    def test_meson_build_version(self):
        """Detect version from meson.build."""
        with tempfile.TemporaryDirectory() as td:
            mb = Path(td) / "meson.build"
            mb.write_text(
                "project('mylib', 'c',\n"
                "  version: '2.4.1',\n"
                ")\n"
            )
            h = Path(td) / "mylib.h"
            h.write_text("/* no version */\n")
            det = VendoredVersionDetector()
            ver = det.detect("mylib", [str(h)])
            self.assertEqual(ver, "2.4.1")

    def test_makefile_version(self):
        """Detect version from Makefile variable."""
        with tempfile.TemporaryDirectory() as td:
            mf = Path(td) / "Makefile"
            mf.write_text(
                "CC = gcc\n"
                "VERSION = 3.7.2\n"
                "CFLAGS = -O2\n"
            )
            h = Path(td) / "lib.h"
            h.write_text("/* no version */\n")
            det = VendoredVersionDetector()
            ver = det.detect("mylib", [str(h)])
            self.assertEqual(ver, "3.7.2")

    def test_quoted_major_minor_release(self):
        """Detect version from quoted string parts
        like Lua uses."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "lua.h"
            h.write_text(
                '#define LUA_VERSION_MAJOR\t"5"\n'
                '#define LUA_VERSION_MINOR\t"4"\n'
                '#define LUA_VERSION_RELEASE\t"8"\n'
            )
            det = VendoredVersionDetector()
            # "liblua" -> prefix tries LUA too
            ver = det.detect("liblua", [str(h)])
            self.assertEqual(ver, "5.4.8")

    def test_lib_prefix_stripping(self):
        """lib prefix is stripped for prefix
        matching."""
        pfx = name_prefixes("liblua")
        self.assertIn("LUA", pfx)
        self.assertIn("LIBLUA", pfx)

    def test_suffix_stripping(self):
        """Trailing qualifiers are stripped for
        prefix matching."""
        pfx = name_prefixes("libdnet-stripped")
        self.assertIn("DNET", pfx)
        self.assertIn("LIBDNET", pfx)

    def test_version_txt_file(self):
        """Detect version from VERSION.txt."""
        with tempfile.TemporaryDirectory() as td:
            vf = Path(td) / "VERSION.txt"
            vf.write_text("1.10.5\n")
            h = Path(td) / "pcap.h"
            h.write_text("/* no version */\n")
            det = VendoredVersionDetector()
            ver = det.detect("libpcap", [str(h)])
            self.assertEqual(ver, "1.10.5")

    def test_release_text_file(self):
        """Detect version from RELEASE file."""
        with tempfile.TemporaryDirectory() as td:
            rf = Path(td) / "RELEASE"
            rf.write_text("8.0\n")
            h = Path(td) / "codec.h"
            h.write_text("/* no version */\n")
            det = VendoredVersionDetector()
            ver = det.detect("ffmpeg", [str(h)])
            self.assertEqual(ver, "8.0")

    def test_define_any_version_fallback(self):
        """Broad fallback finds any #define with
        VERSION containing semver."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "version.h"
            h.write_text(
                '#define REDIS_VERSION "7.2.4"\n'
            )
            det = VendoredVersionDetector()
            ver = det.detect("redis", [str(h)])
            self.assertEqual(ver, "7.2.4")

    def test_configure_ac_unreadable(self):
        """Gracefully handle unreadable configure.ac.
        """
        result = parse_configure_ac(
            Path("/nonexistent/configure.ac")
        )
        self.assertIsNone(result)

    def test_cmakelists_unreadable(self):
        """Gracefully handle unreadable CMakeLists."""
        result = parse_cmakelists(
            Path("/nonexistent/CMakeLists.txt")
        )
        self.assertIsNone(result)

    def test_meson_build_unreadable(self):
        """Gracefully handle unreadable meson.build."""
        result = parse_meson_build(
            Path("/nonexistent/meson.build")
        )
        self.assertIsNone(result)

    def test_makefile_unreadable(self):
        """Gracefully handle unreadable Makefile."""
        result = parse_makefile(
            Path("/nonexistent/Makefile")
        )
        self.assertIsNone(result)

    def test_define_any_version_unreadable(self):
        """Gracefully handle unreadable header for
        broad fallback."""
        result = parse_define_any_version(
            "/nonexistent/lib.h"
        )
        self.assertIsNone(result)

    def test_emit_includes_detected_version(self):
        """Vendored packages get versionInfo when found."""
        with tempfile.TemporaryDirectory() as td:
            # Create a vendored header with version
            dep_dir = Path(td) / "deps" / "lua" / "src"
            dep_dir.mkdir(parents=True)
            (dep_dir / "lua.h").write_text(
                '#define LUA_RELEASE "Lua 5.1.5"\n'
            )
            emitter = SpdxEmitter(
                repo_name="redis",
                repo_version="7.2.0",
                distro="Ubuntu 22.04",
                gcc_version="gcc 11.4.0",
                binary_name="redis-server",
            )
            files = [
                {"sha1": "a1", "file_path":
                    str(dep_dir / "lua.h")},
            ]
            doc = emitter.emit(
                components=[], project_files=files,
                doc_mapping={}, logfile_hashes={},
            )
            lua_pkg = [
                p for p in doc["packages"]
                if p["name"] == "lua"
            ][0]
            self.assertEqual(
                lua_pkg["versionInfo"], "5.1.5"
            )


class TestSpdxEmitterPerBinary(unittest.TestCase):
    """Tests for per-binary SPDX generation."""

    def test_shared_lib_root_purpose(self):
        """libcurl.so root should be LIBRARY."""
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            binary_name="libcurl.so",
        )
        doc = emitter.emit(
            components=[], project_files=[],
            doc_mapping={}, logfile_hashes={},
        )
        root = doc["packages"][0]
        self.assertEqual(root["name"], "libcurl.so")
        self.assertEqual(
            root["primaryPackagePurpose"],
            "LIBRARY",
        )
        self.assertEqual(doc["name"], "libcurl.so")

    def test_application_root_purpose(self):
        """curl binary root should be APPLICATION."""
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            binary_name="curl",
        )
        doc = emitter.emit(
            components=[], project_files=[],
            doc_mapping={}, logfile_hashes={},
        )
        root = doc["packages"][0]
        self.assertEqual(root["name"], "curl")
        self.assertEqual(
            root["primaryPackagePurpose"],
            "APPLICATION",
        )

    def test_binary_name_defaults_to_repo(self):
        """binary_name defaults to repo_name."""
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
        )
        self.assertEqual(
            emitter.binary_name, "curl"
        )

    def test_so_version_in_name(self):
        """libfoo.so.3 should be LIBRARY."""
        emitter = SpdxEmitter(
            repo_name="foo",
            repo_version="1.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            binary_name="libfoo.so.3",
        )
        doc = emitter.emit(
            components=[], project_files=[],
            doc_mapping={}, logfile_hashes={},
        )
        root = doc["packages"][0]
        self.assertEqual(
            root["primaryPackagePurpose"],
            "LIBRARY",
        )


class TestComponentResolverEdgeCases(
    unittest.TestCase
):
    """Edge-case tests for ComponentResolver."""

    def test_non_ubuntu_distro_fallback(self):
        """When resolver has no qualifier and distro
        is not Ubuntu, falls back to 'linux'."""

        class _NoQualResolver(PackageResolver):
            def resolve(self, file_path):
                return None

            def purl_scheme(self):
                return "pkg:deb/debian"

        with tempfile.TemporaryDirectory() as td:
            meta = {
                "distro": "Debian GNU/Linux 12",
                "gcc_version": "gcc 12",
                "repo_version": "8.0",
                "pkg_metadata": {},
                "file_to_pkg": {},
                "unresolved_files": [],
            }
            path = Path(td) / "meta.json"
            path.write_text(json.dumps(meta))
            resolver = ComponentResolver(
                str(path),
                resolver=_NoQualResolver(),
            )
            self.assertEqual(
                resolver.distro_codename, "linux"
            )


class TestAdgSpdxGenerator(unittest.TestCase):
    """Tests for AdgSpdxGenerator facade."""

    def setUp(self):
        patcher = patch(
            "app.spdx.package_resolver.auto_detect_resolver",
            return_value=_fake_dpkg_resolver(),
        )
        self._mock_resolver = patcher.start()
        self.addCleanup(patcher.stop)

    def _setup_full(self, td):
        """Create a complete test environment."""
        bom = Path(td) / "bom"
        meta = bom / "metadata" / "bomsh"
        meta.mkdir(parents=True)

        sha = "a" * 40
        treedb = {
            sha: {
                "file_path": "/repos/curl/src/main.c",
            },
        }
        (meta / "bomsh_omnibor_treedb").write_text(
            json.dumps(treedb)
        )
        (meta / "bomsh_omnibor_doc_mapping").write_text(
            json.dumps({sha: "omnibor_doc"})
        )
        (meta / "bomsh_hook_raw_logfile").write_text(
            f"outfile: {sha} path: /repos/curl\n"
        )

        comp_meta = {
            "distro": "Ubuntu 22.04",
            "gcc_version": "gcc 11.4.0",
            "repo_version": "8.19.0",
            "pkg_metadata": {},
            "file_to_pkg": {},
            "unresolved_files": [],
        }
        (bom / "metadata" / "component_metadata.json").write_text(
            json.dumps(comp_meta)
        )

        dynlibs = {
            "binary": "/repos/curl/src/.libs/curl",
            "direct_needed": ["libssl.so.3"],
            "dynamic_libs": {
                "libssl.so.3": {
                    "path": "/lib/libssl.so.3",
                    "real_path": "/lib/libssl.so.3",
                    "direct": True,
                    "dpkg_package": "libssl3",
                    "source": "openssl",
                    "metadata": {
                        "Package": "libssl3",
                        "Version": "3.0.2",
                        "Source": "openssl",
                        "Maintainer": "Ubuntu",
                        "Homepage": "https://openssl.org",
                        "Architecture": "amd64",
                    },
                },
            },
            "libcurl_needed": [],
        }
        (bom / "metadata" / "dynamic_libs.json").write_text(
            json.dumps(dynlibs)
        )

        return str(bom)

    def test_generate_success(self):
        with tempfile.TemporaryDirectory() as td:
            bom_dir = self._setup_full(td)
            out = str(
                Path(td) / "out" / "curl.spdx.json"
            )

            gen = AdgSpdxGenerator(
                bom_dir=bom_dir,
                repos_dir="/repos",
                repo_name="curl",
                bomtrace_version="6.11",
                bomsh_version="0.0.1",
            )
            with patch("builtins.print"):
                result = gen.generate(out)

            self.assertIsNotNone(result)
            doc = json.loads(Path(out).read_text())
            self.assertEqual(
                doc["spdxVersion"], "SPDX-2.3"
            )
            # Root + openssl + gcc = 3
            self.assertEqual(
                len(doc["packages"]), 3
            )

    def test_generate_per_binary_with_dynlib_dir(self):
        """Generate SPDX for libcurl.so with separate dynlib_dir."""
        with tempfile.TemporaryDirectory() as td:
            bom_dir = self._setup_full(td)

            # Create separate dynlib dir for libcurl.so
            libcurl_dl = Path(td) / "libcurl_dynlibs"
            libcurl_dl.mkdir()
            dynlibs = {
                "binary": "/repos/curl/lib/.libs/libcurl.so",
                "direct_needed": ["libz.so.1"],
                "dynamic_libs": {
                    "libz.so.1": {
                        "path": "/lib/libz.so.1",
                        "real_path": "/lib/libz.so.1",
                        "direct": True,
                        "dpkg_package": "zlib1g",
                        "source": "zlib",
                        "metadata": {
                            "Package": "zlib1g",
                            "Version": "1.2.11",
                            "Source": "zlib",
                            "Maintainer": "Ubuntu",
                            "Homepage": "http://zlib.net",
                            "Architecture": "amd64",
                        },
                    },
                },
                "libcurl_needed": [],
            }
            (libcurl_dl / "dynamic_libs.json").write_text(
                json.dumps(dynlibs)
            )

            out = str(
                Path(td) / "out" / "libcurl.spdx.json"
            )
            gen = AdgSpdxGenerator(
                bom_dir=bom_dir,
                repos_dir="/repos",
                repo_name="curl",
            )
            with patch("builtins.print"):
                result = gen.generate(
                    out,
                    binary_name="libcurl.so",
                    dynlib_dir=str(libcurl_dl),
                )

            self.assertIsNotNone(result)
            doc = json.loads(Path(out).read_text())
            root = doc["packages"][0]
            self.assertEqual(
                root["name"], "libcurl.so"
            )
            self.assertEqual(
                root["primaryPackagePurpose"],
                "LIBRARY",
            )
            # Root + zlib + gcc = 3
            self.assertEqual(
                len(doc["packages"]), 3
            )

    def test_generate_missing_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            bom = Path(td) / "bom"
            meta = bom / "metadata" / "bomsh"
            meta.mkdir(parents=True)
            treedb = {
                "aaa": {
                    "file_path": "/repos/curl/x.c"
                },
            }
            (
                meta / "bomsh_omnibor_treedb"
            ).write_text(json.dumps(treedb))
            (
                meta / "bomsh_omnibor_doc_mapping"
            ).write_text("{}")
            out = str(
                Path(td) / "out" / "curl.spdx.json"
            )

            gen = AdgSpdxGenerator(
                bom_dir=str(bom),
                repos_dir="/repos",
                repo_name="curl",
            )
            with patch("builtins.print"):
                result = gen.generate(out)

            self.assertIsNone(result)


class TestCli(unittest.TestCase):
    """Tests for CLI main() function."""

    def setUp(self):
        patcher = patch(
            "app.spdx.package_resolver.auto_detect_resolver",
            return_value=_fake_dpkg_resolver(),
        )
        self._mock_resolver = patcher.start()
        self.addCleanup(patcher.stop)

    def test_main_success(self):
        from spdx_from_adg import main
        with tempfile.TemporaryDirectory() as td:
            # Reuse full setup from generator test
            bom = Path(td) / "bom"
            meta = bom / "metadata" / "bomsh"
            meta.mkdir(parents=True)
            sha = "a" * 40
            treedb = {
                sha: {
                    "file_path": "/repos/curl/src/x.c",
                },
            }
            (meta / "bomsh_omnibor_treedb").write_text(
                json.dumps(treedb)
            )
            (
                meta / "bomsh_omnibor_doc_mapping"
            ).write_text(json.dumps({}))
            comp_meta = {
                "distro": "Ubuntu 22.04",
                "gcc_version": "gcc 11.4.0",
                "repo_version": "8.19.0",
                "pkg_metadata": {},
                "file_to_pkg": {},
                "unresolved_files": [],
            }
            (
                bom / "metadata"
                / "component_metadata.json"
            ).write_text(json.dumps(comp_meta))

            dynlibs = {
                "binary": "/repos/curl/src/.libs/curl",
                "direct_needed": [],
                "dynamic_libs": {},
                "libcurl_needed": [],
            }
            (
                bom / "metadata"
                / "dynamic_libs.json"
            ).write_text(json.dumps(dynlibs))

            out = str(
                Path(td) / "out" / "curl.spdx.json"
            )
            args = [
                "--bom-dir", str(bom),
                "--repos-dir", "/repos",
                "--repo-name", "curl",
                "--output", out,
                "--bomtrace-version", "6.11",
                "--bomsh-version", "0.0.1",
            ]
            with patch(
                "sys.argv",
                ["spdx_from_adg.py"] + args,
            ), patch("builtins.print"):
                main()

            self.assertTrue(Path(out).exists())

    def test_main_failure(self):
        from spdx_from_adg import main
        with tempfile.TemporaryDirectory() as td:
            bom = Path(td) / "bom"
            meta = bom / "metadata" / "bomsh"
            meta.mkdir(parents=True)
            (
                meta / "bomsh_omnibor_treedb"
            ).write_text(json.dumps({}))
            (
                meta / "bomsh_omnibor_doc_mapping"
            ).write_text(json.dumps({}))
            # No component_metadata.json
            out = str(
                Path(td) / "out" / "curl.spdx.json"
            )
            args = [
                "--bom-dir", str(bom),
                "--repos-dir", "/repos",
                "--repo-name", "curl",
                "--output", out,
            ]
            with patch(
                "sys.argv",
                ["spdx_from_adg.py"] + args,
            ), patch("builtins.print"):
                with self.assertRaises(SystemExit):
                    main()


class TestProjectBuiltLibs(unittest.TestCase):
    """Tests for project-built shared library detection
    and SPDX emission (lines 318-326, 951-968)."""

    def _write_metadata(self, td, metadata):
        path = Path(td) / "component_metadata.json"
        path.write_text(json.dumps(metadata))
        return str(path)

    def _base_metadata(self):
        return {
            "distro": "Ubuntu 22.04.5 LTS",
            "gcc_version": "gcc (Ubuntu 11.4.0) 11.4.0",
            "repo_version": "8.19.0-DEV",
            "pkg_metadata": {},
            "file_to_pkg": {},
            "unresolved_files": [],
        }

    def test_resolve_project_built_libs(self):
        """project_built_libs in dynlibs produces
        components with project_built=True."""
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path, resolver=_fake_dpkg_resolver())

            dynlibs = {
                "binary": "/repos/ffmpeg/ffmpeg",
                "direct_needed": ["libavcodec.so"],
                "dynamic_libs": {},
                "libcurl_needed": [],
                "project_built_libs": {
                    "libavcodec.so": {
                        "name": "libavcodec",
                        "direct": True,
                    },
                    "libavutil.so": {
                        "direct": False,
                    },
                },
            }
            dynlib_path = Path(td) / "dynamic_libs.json"
            dynlib_path.write_text(json.dumps(dynlibs))
            resolver.load_dynamic_libs(str(dynlib_path))
            components = (
                resolver.resolve_dynamic_components()
            )
            proj = [
                c for c in components
                if c.get("project_built")
            ]
            self.assertEqual(len(proj), 2)
            names = [c["name"] for c in proj]
            self.assertIn("libavcodec", names)
            # Falls back to soname when no "name" key
            self.assertIn("libavutil.so", names)
            # Check direct flag
            avcodec = [
                c for c in proj
                if c["name"] == "libavcodec"
            ][0]
            self.assertTrue(avcodec["direct"])
            avutil = [
                c for c in proj
                if c["name"] == "libavutil.so"
            ][0]
            self.assertFalse(avutil["direct"])

    def test_emit_project_built_component(self):
        """project_built components become SPDX packages
        with LIBRARY purpose and project version."""
        emitter = SpdxEmitter(
            repo_name="ffmpeg",
            repo_version="6.1",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            binary_name="ffmpeg",
        )
        components = [{
            "name": "libavcodec",
            "source": "libavcodec",
            "sonames": ["libavcodec.so"],
            "direct": True,
            "project_built": True,
        }]
        doc = emitter.emit(
            components=components,
            project_files=[],
            doc_mapping={},
            logfile_hashes={},
        )
        # Root + libavcodec + gcc = 3
        self.assertEqual(len(doc["packages"]), 3)
        avcodec = [
            p for p in doc["packages"]
            if p["name"] == "libavcodec"
        ][0]
        self.assertEqual(
            avcodec["primaryPackagePurpose"],
            "LIBRARY",
        )
        self.assertIn(
            "Project-built", avcodec["comment"]
        )
        self.assertIn(
            "libavcodec.so", avcodec["comment"]
        )
        self.assertEqual(
            avcodec["versionInfo"], "6.1"
        )
        self.assertEqual(
            avcodec["downloadLocation"],
            "NOASSERTION",
        )
        # packageSourceInfo for project-built lib
        self.assertIn(
            "packageSourceInfo", avcodec
        )
        self.assertIn(
            "Built from project source",
            avcodec["packageSourceInfo"],
        )
        self.assertIn(
            "ffmpeg",
            avcodec["packageSourceInfo"],
        )

    def test_emit_project_built_no_version(self):
        """project_built without repo_version omits
        versionInfo."""
        emitter = SpdxEmitter(
            repo_name="ffmpeg",
            repo_version=None,
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
        )
        components = [{
            "name": "libavcodec",
            "source": "libavcodec",
            "sonames": ["libavcodec.so"],
            "direct": True,
            "project_built": True,
        }]
        doc = emitter.emit(
            components=components,
            project_files=[],
            doc_mapping={},
            logfile_hashes={},
        )
        avcodec = [
            p for p in doc["packages"]
            if p["name"] == "libavcodec"
        ][0]
        self.assertNotIn("versionInfo", avcodec)


class TestHeaderCommentBreak(unittest.TestCase):
    """Test _parse_header_comment line limit (line 527)."""

    def test_version_after_line_20_not_found(self):
        """VERSION past the 20-line window is ignored."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "big.h"
            lines = ["/* no version */\n"] * 21
            lines.append(
                "/* VERSION 9.9.9 */\n"
            )
            h.write_text("".join(lines))
            result = parse_header_comment(str(h))
            self.assertIsNone(result)

    def test_version_within_first_20_lines(self):
        """VERSION within 20-line window IS found."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "ok.h"
            lines = ["/* padding */\n"] * 5
            lines.append("/* VERSION 3.2.1 */\n")
            h.write_text("".join(lines))
            result = parse_header_comment(str(h))
            self.assertEqual(result, "3.2.1")


class TestSubComponentRemainingFiles(
    unittest.TestCase
):
    """Tests for remaining-file assignment in
    sub-component splitting (lines 718-719, 745-747)."""

    def _emitter(self):
        return SpdxEmitter(
            repo_name="redis",
            repo_version="7.2.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            binary_name="redis-server",
        )

    def test_non_source_files_go_to_remaining(self):
        """Non .c/.h files skip sub-component detection
        and go to remaining (lines 718-719)."""
        with tempfile.TemporaryDirectory() as td:
            lua_dir = Path(td) / "deps" / "lua" / "src"
            lua_dir.mkdir(parents=True)
            (lua_dir / "lapi.c").write_text("")
            (lua_dir / "lua_cjson.c").write_text(
                '#define CJSON_VERSION "2.1.0"\n'
            )
            # .o file — not .c or .h
            (lua_dir / "lapi.o").write_text("")
            emitter = self._emitter()
            files = [
                {"sha1": "a1", "file_path":
                    str(lua_dir / "lapi.c")},
                {"sha1": "a2", "file_path":
                    str(lua_dir / "lua_cjson.c")},
                {"sha1": "a3", "file_path":
                    str(lua_dir / "lapi.o")},
            ]
            vendored, own = (
                emitter._detect_vendored_groups(files)
            )
            # .o goes to parent (lua) as remaining
            self.assertIn("lua", vendored)
            # lapi.c + lapi.o in lua group
            lua_paths = [
                f["file_path"]
                for f in vendored["lua"]
            ]
            self.assertTrue(
                any("lapi.o" in p for p in lua_paths)
            )

    def test_remaining_files_matched_to_subcomponent(
        self,
    ):
        """Non-source files whose basename contains a
        sub-component key are assigned to it
        (lines 745-747)."""
        with tempfile.TemporaryDirectory() as td:
            lua_dir = Path(td) / "deps" / "lua" / "src"
            lua_dir.mkdir(parents=True)
            (lua_dir / "lapi.c").write_text("")
            (lua_dir / "lua_cjson.c").write_text(
                '#define CJSON_VERSION "2.1.0"\n'
            )
            # .o file whose name contains "cjson"
            (lua_dir / "lua_cjson.o").write_text("")
            emitter = self._emitter()
            files = [
                {"sha1": "a1", "file_path":
                    str(lua_dir / "lapi.c")},
                {"sha1": "a2", "file_path":
                    str(lua_dir / "lua_cjson.c")},
                {"sha1": "a3", "file_path":
                    str(lua_dir / "lua_cjson.o")},
            ]
            vendored, own = (
                emitter._detect_vendored_groups(files)
            )
            self.assertIn("lua-cjson", vendored)
            # lua_cjson.c + lua_cjson.o
            self.assertEqual(
                len(vendored["lua-cjson"]), 2
            )


class TestGenericPrefixSkip(unittest.TestCase):
    """Test that generic prefix names like VERSION,
    LIB are skipped (line 799)."""

    def _emitter(self):
        return SpdxEmitter(
            repo_name="redis",
            repo_version="7.2.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            binary_name="redis-server",
        )

    def test_generic_version_prefix_skipped(self):
        """#define VERSION_VERSION is skipped as
        a generic name."""
        with tempfile.TemporaryDirectory() as td:
            lua_dir = Path(td) / "deps" / "lua" / "src"
            lua_dir.mkdir(parents=True)
            (lua_dir / "lapi.c").write_text(
                '#define VERSION "1.0.0"\n'
            )
            emitter = self._emitter()
            files = [
                {"sha1": "a1", "file_path":
                    str(lua_dir / "lapi.c")},
            ]
            vendored, own = (
                emitter._detect_vendored_groups(files)
            )
            # Should stay as "lua", no "version" sub
            self.assertIn("lua", vendored)
            self.assertNotIn("version", vendored)

    def test_generic_lib_prefix_skipped(self):
        """#define LIB_VERSION is skipped."""
        with tempfile.TemporaryDirectory() as td:
            lua_dir = Path(td) / "deps" / "lua" / "src"
            lua_dir.mkdir(parents=True)
            (lua_dir / "lapi.c").write_text(
                '#define LIB_VERSION "2.0"\n'
            )
            emitter = self._emitter()
            files = [
                {"sha1": "a1", "file_path":
                    str(lua_dir / "lapi.c")},
            ]
            vendored, own = (
                emitter._detect_vendored_groups(files)
            )
            self.assertIn("lua", vendored)
            self.assertNotIn("lib", vendored)


class TestFilePathRelativization(unittest.TestCase):
    """Test ValueError/IndexError in file path
    relativization (lines 1190-1191)."""

    def test_short_path_falls_back(self):
        """A very short file_path triggers the
        except branch and uses the raw path."""
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
        )
        # Bare filename (1 part) → parents[-2] raises
        # IndexError, so rel_path stays as-is
        files = [
            {"sha1": "abc123", "file_path": "x.c"},
        ]
        doc = emitter.emit(
            components=[],
            project_files=files,
            doc_mapping={},
            logfile_hashes={},
        )
        self.assertEqual(len(doc["files"]), 1)
        # Should still work, using raw path
        self.assertEqual(
            doc["files"][0]["fileName"], "x.c"
        )


class TestGenerateMissingDynlibs(unittest.TestCase):
    """Test generate() when dynamic_libs.json is
    missing (lines 1312-1317)."""

    def setUp(self):
        patcher = patch(
            "app.spdx.package_resolver.auto_detect_resolver",
            return_value=_fake_dpkg_resolver(),
        )
        self._mock_resolver = patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_dynlib_returns_none(self):
        """generate() returns None if dynlib not found."""
        with tempfile.TemporaryDirectory() as td:
            bom = Path(td) / "bom"
            meta = bom / "metadata" / "bomsh"
            meta.mkdir(parents=True)

            sha = "a" * 40
            treedb = {
                sha: {
                    "file_path": "/repos/curl/src/x.c"
                },
            }
            (meta / "bomsh_omnibor_treedb").write_text(
                json.dumps(treedb)
            )
            (
                meta / "bomsh_omnibor_doc_mapping"
            ).write_text(json.dumps({}))

            comp_meta = {
                "distro": "Ubuntu 22.04",
                "gcc_version": "gcc 11.4.0",
                "repo_version": "8.19.0",
                "pkg_metadata": {},
                "file_to_pkg": {},
                "unresolved_files": [],
            }
            (
                bom / "metadata"
                / "component_metadata.json"
            ).write_text(json.dumps(comp_meta))
            # NOTE: no dynamic_libs.json created

            out = str(
                Path(td) / "out" / "curl.spdx.json"
            )
            gen = AdgSpdxGenerator(
                bom_dir=str(bom),
                repos_dir="/repos",
                repo_name="curl",
            )
            with patch("builtins.print"):
                result = gen.generate(out)

            self.assertIsNone(result)


class TestVisualizationFailure(unittest.TestCase):
    """Test HTML visualization failure handling
    (lines 1384-1385)."""

    def setUp(self):
        patcher = patch(
            "app.spdx.package_resolver.auto_detect_resolver",
            return_value=_fake_dpkg_resolver(),
        )
        self._mock_resolver = patcher.start()
        self.addCleanup(patcher.stop)

    def test_visualization_exception_caught(self):
        """generate() succeeds even when visualization
        raises an exception."""
        with tempfile.TemporaryDirectory() as td:
            bom = Path(td) / "bom"
            meta = bom / "metadata" / "bomsh"
            meta.mkdir(parents=True)

            sha = "a" * 40
            treedb = {
                sha: {
                    "file_path": "/repos/curl/src/x.c"
                },
            }
            (meta / "bomsh_omnibor_treedb").write_text(
                json.dumps(treedb)
            )
            (
                meta / "bomsh_omnibor_doc_mapping"
            ).write_text(json.dumps({}))
            (
                meta / "bomsh_hook_raw_logfile"
            ).write_text("")

            comp_meta = {
                "distro": "Ubuntu 22.04",
                "gcc_version": "gcc 11.4.0",
                "repo_version": "8.19.0",
                "pkg_metadata": {},
                "file_to_pkg": {},
                "unresolved_files": [],
            }
            (
                bom / "metadata"
                / "component_metadata.json"
            ).write_text(json.dumps(comp_meta))

            dynlibs = {
                "binary": "/repos/curl/src/.libs/curl",
                "direct_needed": [],
                "dynamic_libs": {},
                "libcurl_needed": [],
            }
            (
                bom / "metadata"
                / "dynamic_libs.json"
            ).write_text(json.dumps(dynlibs))

            out = str(
                Path(td) / "out" / "curl.spdx.json"
            )
            gen = AdgSpdxGenerator(
                bom_dir=str(bom),
                repos_dir="/repos",
                repo_name="curl",
            )
            # Make spdx_visualize.generate_html raise
            with patch(
                "spdx_visualize.generate_html",
                side_effect=RuntimeError("viz failed"),
            ), patch("builtins.print"):
                result = gen.generate(out)

            # Should still succeed
            self.assertIsNotNone(result)
            self.assertTrue(Path(out).exists())


class TestGoModuleFromVendorPath(unittest.TestCase):
    """Tests for SpdxEmitter._go_module_from_vendor_path."""

    def test_github_three_segments(self):
        result = SpdxEmitter._go_module_from_vendor_path(
            "github.com/fatih/color/color.go"
        )
        self.assertEqual(
            result, "github.com/fatih/color"
        )

    def test_github_major_version_suffix(self):
        result = SpdxEmitter._go_module_from_vendor_path(
            "github.com/gdamore/tcell/v2/screen.go"
        )
        self.assertEqual(
            result,
            "github.com/gdamore/tcell/v2",
        )

    def test_golang_org_three_segments(self):
        result = SpdxEmitter._go_module_from_vendor_path(
            "golang.org/x/crypto/ssh/keys.go"
        )
        self.assertEqual(
            result, "golang.org/x/crypto"
        )

    def test_gopkg_in_dotted_two_segments(self):
        result = SpdxEmitter._go_module_from_vendor_path(
            "gopkg.in/yaml.v3/yaml.go"
        )
        self.assertEqual(
            result, "gopkg.in/yaml.v3"
        )

    def test_gopkg_in_three_segments(self):
        result = SpdxEmitter._go_module_from_vendor_path(
            "gopkg.in/ozeidan/fuzzy-patricia.v3/p.go"
        )
        self.assertEqual(
            result,
            "gopkg.in/ozeidan/fuzzy-patricia.v3",
        )

    def test_other_domain_two_segments(self):
        result = SpdxEmitter._go_module_from_vendor_path(
            "dario.cat/mergo/merge.go"
        )
        self.assertEqual(
            result, "dario.cat/mergo"
        )

    def test_no_dot_in_first_segment(self):
        """Non-domain first segment returns None."""
        result = SpdxEmitter._go_module_from_vendor_path(
            "internal/util/helper.go"
        )
        self.assertIsNone(result)

    def test_single_segment(self):
        result = SpdxEmitter._go_module_from_vendor_path(
            "README.md"
        )
        self.assertIsNone(result)

    def test_github_only_two_parts(self):
        """github.com/owner with no repo returns None."""
        result = SpdxEmitter._go_module_from_vendor_path(
            "github.com/owner"
        )
        self.assertIsNone(result)

    def test_gitlab_three_segments(self):
        result = SpdxEmitter._go_module_from_vendor_path(
            "gitlab.com/org/repo/file.go"
        )
        self.assertEqual(
            result, "gitlab.com/org/repo"
        )

    def test_bitbucket_three_segments(self):
        result = SpdxEmitter._go_module_from_vendor_path(
            "bitbucket.org/org/repo/file.go"
        )
        self.assertEqual(
            result, "bitbucket.org/org/repo"
        )

    def test_gopkg_in_no_dot_two_parts(self):
        """gopkg.in/owner with no repo returns None."""
        result = SpdxEmitter._go_module_from_vendor_path(
            "gopkg.in/owner"
        )
        self.assertIsNone(result)


class TestDetectGoVersion(unittest.TestCase):
    """Tests for SpdxEmitter._detect_go_version."""

    def test_from_build_cmd(self):
        stdlib = [{
            "file_path": "/usr/local/go/src/fmt/print.go",
            "build_cmd": (
                "compile -goversion go1.22.3 -p fmt"
            ),
        }]
        ver = SpdxEmitter._detect_go_version(stdlib)
        self.assertEqual(ver, "1.22.3")

    def test_from_version_file(self):
        stdlib = [{
            "file_path": (
                "/usr/local/go/src/fmt/a.go"
            ),
        }]
        with patch.object(
            Path, "exists", return_value=True
        ), patch.object(
            Path, "read_text",
            return_value="go1.26.0\ntime 2026\n",
        ):
            ver = SpdxEmitter._detect_go_version(
                stdlib
            )
        self.assertEqual(ver, "1.26.0")

    def test_fallback_unknown(self):
        stdlib = [{
            "file_path": (
                "/usr/local/go/src/fmt/print.go"
            ),
        }]
        # No build_cmd, non-existent go_root
        ver = SpdxEmitter._detect_go_version(
            stdlib, go_root="/nonexistent/go",
        )
        self.assertEqual(ver, "unknown")

    def test_empty_stdlib(self):
        ver = SpdxEmitter._detect_go_version(
            [], go_root="/nonexistent/go",
        )
        self.assertEqual(ver, "unknown")


class TestParseGoModulesTxt(unittest.TestCase):
    """Tests for SpdxEmitter._parse_go_modules_txt."""

    def test_parse_modules_txt(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repos" / "lazygit"
            vendor = repo / "vendor"
            vendor.mkdir(parents=True)
            (vendor / "modules.txt").write_text(
                "# github.com/fatih/color v1.16.0\n"
                "## explicit; go 1.17\n"
                "github.com/fatih/color\n"
                "# golang.org/x/sys v0.40.0\n"
                "## explicit; go 1.18\n"
                "golang.org/x/sys/unix\n"
            )
            src = str(repo / "main.go")
            files = [{"file_path": src}]
            versions = (
                SpdxEmitter._parse_go_modules_txt(files)
            )
            self.assertEqual(
                versions["github.com/fatih/color"],
                "1.16.0",
            )
            self.assertEqual(
                versions["golang.org/x/sys"],
                "0.40.0",
            )

    def test_no_project_files(self):
        versions = (
            SpdxEmitter._parse_go_modules_txt([])
        )
        self.assertEqual(versions, {})

    def test_no_modules_txt(self):
        with tempfile.TemporaryDirectory() as td:
            files = [{"file_path": str(
                Path(td) / "main.go"
            )}]
            versions = (
                SpdxEmitter._parse_go_modules_txt(
                    files
                )
            )
            self.assertEqual(versions, {})


class TestParseGoMod(unittest.TestCase):
    """Tests for SpdxEmitter._parse_go_mod."""

    def test_parse_direct_and_indirect(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repos" / "lazygit"
            repo.mkdir(parents=True)
            (repo / "go.mod").write_text(
                "module github.com/example/app\n"
                "\n"
                "go 1.22\n"
                "\n"
                "require (\n"
                "\tgithub.com/direct/one v1.0.0\n"
                "\tgithub.com/direct/two v2.0.0\n"
                ")\n"
                "\n"
                "require (\n"
                "\tgithub.com/indirect/a "
                "v0.1.0 // indirect\n"
                "\tgithub.com/indirect/b "
                "v0.2.0 // indirect\n"
                ")\n"
            )
            files = [{"file_path": str(
                repo / "main.go"
            )}]
            indirect = SpdxEmitter._parse_go_mod(
                files
            )
            self.assertIn(
                "github.com/indirect/a", indirect
            )
            self.assertIn(
                "github.com/indirect/b", indirect
            )
            self.assertNotIn(
                "github.com/direct/one", indirect
            )
            self.assertNotIn(
                "github.com/direct/two", indirect
            )

    def test_no_project_files(self):
        indirect = SpdxEmitter._parse_go_mod([])
        self.assertEqual(indirect, set())

    def test_no_go_mod_file(self):
        with tempfile.TemporaryDirectory() as td:
            files = [{"file_path": str(
                Path(td) / "main.go"
            )}]
            indirect = SpdxEmitter._parse_go_mod(
                files
            )
            self.assertEqual(indirect, set())


class TestGoStdlibClassification(unittest.TestCase):
    """Tests for go_stdlib classification in parse()."""

    def test_go_stdlib_files_classified(self):
        with tempfile.TemporaryDirectory() as td:
            meta = (
                Path(td) / "bom" / "metadata" / "bomsh"
            )
            meta.mkdir(parents=True)
            treedb = {
                "aaa": {
                    "file_path": (
                        "/usr/local/go/src/fmt/print.go"
                    ),
                },
                "bbb": {
                    "file_path": (
                        "/usr/local/go/src/os/file.go"
                    ),
                    "build_cmd": "compile -p os",
                },
            }
            (
                meta / "bomsh_omnibor_treedb"
            ).write_text(json.dumps(treedb))
            parser = AdgParser(
                Path(td) / "bom", "/repos"
            )
            result = parser.parse()
            self.assertEqual(
                len(result["go_stdlib"]), 2
            )
            # Verify build_cmd preserved
            cmds = [
                a.get("build_cmd")
                for a in result["go_stdlib"]
            ]
            self.assertIn("compile -p os", cmds)


class TestGoModuleEmission(unittest.TestCase):
    """Tests for Go module SPDX emission."""

    def _emitter(self, binary_name="lazygit"):
        return SpdxEmitter(
            repo_name="lazygit",
            repo_version="0.44.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            bomtrace_version="6.11",
            bomsh_version="0.0.1",
            binary_name=binary_name,
        )

    def test_go_stdlib_and_compiler_packages(self):
        """go_stdlib adds Go compiler + stdlib pkgs."""
        emitter = self._emitter()
        go_stdlib = [
            {"file_path": "/usr/local/go/src/a.go"},
            {"file_path": "/usr/local/go/src/b.go"},
        ]
        doc = emitter.emit(
            components=[],
            project_files=[],
            doc_mapping={},
            logfile_hashes={},
            go_stdlib=go_stdlib,
        )
        names = [p["name"] for p in doc["packages"]]
        self.assertIn("go", names)
        self.assertIn("go-stdlib", names)

        # Go compiler is BUILD_TOOL_OF root
        go_pkg = next(
            p for p in doc["packages"]
            if p["name"] == "go"
        )
        build_rels = [
            r for r in doc["relationships"]
            if r["spdxElementId"] == go_pkg["SPDXID"]
            and r["relationshipType"] == "BUILD_TOOL_OF"
        ]
        self.assertEqual(len(build_rels), 1)
        # Go compiler packageSourceInfo
        self.assertIn(
            "packageSourceInfo", go_pkg
        )
        self.assertIn(
            "Go toolchain",
            go_pkg["packageSourceInfo"],
        )

        # Stdlib is DEPENDS_ON from root
        stdlib_pkg = next(
            p for p in doc["packages"]
            if p["name"] == "go-stdlib"
        )
        dep_rels = [
            r for r in doc["relationships"]
            if r["relatedSpdxElement"]
            == stdlib_pkg["SPDXID"]
            and r["relationshipType"] == "DEPENDS_ON"
        ]
        self.assertEqual(len(dep_rels), 1)

        # Stdlib has PURL
        purls = [
            ref["referenceLocator"]
            for ref in stdlib_pkg["externalRefs"]
            if ref["referenceType"] == "purl"
        ]
        self.assertEqual(len(purls), 1)
        self.assertIn("pkg:golang/stdlib", purls[0])
        # Stdlib packageSourceInfo
        self.assertIn(
            "packageSourceInfo", stdlib_pkg
        )
        self.assertIn(
            "Bundled with Go toolchain",
            stdlib_pkg["packageSourceInfo"],
        )

    def test_go_module_vendored_package(self):
        """Go vendor/ files create Go module packages."""
        emitter = self._emitter()
        files = [
            {
                "sha1": "a" * 40,
                "file_path": (
                    "/repos/lazygit/vendor/"
                    "github.com/fatih/color/color.go"
                ),
            },
            {
                "sha1": "b" * 40,
                "file_path": (
                    "/repos/lazygit/vendor/"
                    "github.com/fatih/color/doc.go"
                ),
            },
        ]
        doc = emitter.emit(
            components=[],
            project_files=files,
            doc_mapping={},
            logfile_hashes={},
        )
        names = [p["name"] for p in doc["packages"]]
        self.assertIn(
            "github.com/fatih/color", names
        )

        pkg = next(
            p for p in doc["packages"]
            if p["name"] == "github.com/fatih/color"
        )
        # Go module -> downloadLocation is pkg.go.dev
        self.assertIn(
            "pkg.go.dev", pkg["downloadLocation"]
        )
        # Go module -> DEPENDS_ON (not STATIC_LINK)
        dep_rels = [
            r for r in doc["relationships"]
            if r["relatedSpdxElement"]
            == pkg["SPDXID"]
            and r["relationshipType"] == "DEPENDS_ON"
        ]
        self.assertEqual(len(dep_rels), 1)

    def test_go_module_purl_with_version(self):
        """Go module with version gets PURL."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repos" / "lazygit"
            vendor = repo / "vendor"
            vendor.mkdir(parents=True)
            (vendor / "modules.txt").write_text(
                "# github.com/fatih/color v1.16.0\n"
            )
            emitter = self._emitter()
            files = [{
                "sha1": "a" * 40,
                "file_path": str(
                    repo / "vendor"
                    / "github.com" / "fatih"
                    / "color" / "color.go"
                ),
            }]
            doc = emitter.emit(
                components=[],
                project_files=files,
                doc_mapping={},
                logfile_hashes={},
            )
            pkg = next(
                p for p in doc["packages"]
                if p["name"]
                == "github.com/fatih/color"
            )
            self.assertEqual(
                pkg["versionInfo"], "1.16.0"
            )
            purls = [
                ref["referenceLocator"]
                for ref in pkg["externalRefs"]
                if ref["referenceType"] == "purl"
            ]
            self.assertEqual(len(purls), 1)
            self.assertEqual(
                purls[0],
                "pkg:golang/github.com/fatih/"
                "color@1.16.0",
            )

    def test_go_files_included_in_spdx_files(self):
        """*.go files appear in doc['files']."""
        emitter = self._emitter()
        files = [{
            "sha1": "a" * 40,
            "file_path": (
                "/repos/lazygit/pkg/gui/main.go"
            ),
        }]
        doc = emitter.emit(
            components=[],
            project_files=files,
            doc_mapping={},
            logfile_hashes={},
        )
        fnames = [
            f["fileName"] for f in doc["files"]
        ]
        self.assertTrue(
            any("main.go" in n for n in fnames)
        )

    def test_no_go_stdlib_skips_go_packages(self):
        """Without go_stdlib, no go/go-stdlib pkgs."""
        emitter = self._emitter()
        doc = emitter.emit(
            components=[],
            project_files=[],
            doc_mapping={},
            logfile_hashes={},
        )
        names = [p["name"] for p in doc["packages"]]
        self.assertNotIn("go", names)
        self.assertNotIn("go-stdlib", names)

    def test_spdx_id_no_underscores(self):
        """SPDX IDs must not contain underscores."""
        emitter = self._emitter()
        name = emitter._sanitize_spdx_id(
            "ssh_config"
        )
        self.assertNotIn("_", name)
        self.assertEqual(name, "ssh-config")

    def test_go_module_vendored_detects_vn(self):
        """vendor/ with /v5 suffix groups correctly."""
        emitter = self._emitter()
        files = [{
            "sha1": "a" * 40,
            "file_path": (
                "/repos/lazygit/vendor/"
                "github.com/go-git/go-billy/v5/"
                "osfs/os.go"
            ),
        }]
        doc = emitter.emit(
            components=[],
            project_files=files,
            doc_mapping={},
            logfile_hashes={},
        )
        names = [p["name"] for p in doc["packages"]]
        self.assertIn(
            "github.com/go-git/go-billy/v5",
            names,
        )

    def test_go_module_direct_indirect_comment(self):
        """Direct and indirect Go modules get labels."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repos" / "lazygit"
            vendor = repo / "vendor"
            vendor.mkdir(parents=True)
            (repo / "go.mod").write_text(
                "module github.com/example/app\n"
                "go 1.22\n"
                "require (\n"
                "\tgithub.com/direct/pkg v1.0\n"
                "\tgithub.com/trans/pkg "
                "v2.0 // indirect\n"
                ")\n"
            )
            (vendor / "modules.txt").write_text(
                "# github.com/direct/pkg v1.0.0\n"
                "# github.com/trans/pkg v2.0.0\n"
            )
            emitter = self._emitter()
            files = [
                {
                    "sha1": "a" * 40,
                    "file_path": str(
                        repo / "vendor"
                        / "github.com" / "direct"
                        / "pkg" / "a.go"
                    ),
                },
                {
                    "sha1": "b" * 40,
                    "file_path": str(
                        repo / "vendor"
                        / "github.com" / "trans"
                        / "pkg" / "b.go"
                    ),
                },
            ]
            doc = emitter.emit(
                components=[],
                project_files=files,
                doc_mapping={},
                logfile_hashes={},
            )
            direct_pkg = next(
                p for p in doc["packages"]
                if p["name"]
                == "github.com/direct/pkg"
            )
            indirect_pkg = next(
                p for p in doc["packages"]
                if p["name"]
                == "github.com/trans/pkg"
            )
            self.assertIn(
                "direct", direct_pkg["comment"]
            )
            self.assertIn(
                "indirect",
                indirect_pkg["comment"],
            )
            # packageSourceInfo for Go modules
            self.assertIn(
                "go mod vendor",
                direct_pkg["packageSourceInfo"],
            )
            self.assertIn(
                "vendor/github.com/direct/pkg/",
                direct_pkg["packageSourceInfo"],
            )
            self.assertIn(
                "Indirect dependency",
                indirect_pkg[
                    "packageSourceInfo"
                ],
            )


class TestRustCrateFromRegistryPath(unittest.TestCase):
    """Tests for _rust_crate_from_registry_path."""

    def test_standard_crate_path(self):
        name, ver = (
            SpdxEmitter._rust_crate_from_registry_path(
                "/root/.cargo/registry/src/"
                "index.crates.io-6f17d22bba15001f/"
                "bitvec-1.0.1/src/lib.rs"
            )
        )
        self.assertEqual(name, "bitvec")
        self.assertEqual(ver, "1.0.1")

    def test_crate_with_hyphen(self):
        name, ver = (
            SpdxEmitter._rust_crate_from_registry_path(
                "/root/.cargo/registry/src/"
                "index.crates.io-6f17d22bba15001f/"
                "rustc-hash-2.1.0/src/lib.rs"
            )
        )
        self.assertEqual(name, "rustc-hash")
        self.assertEqual(ver, "2.1.0")

    def test_crate_with_pre_release(self):
        name, ver = (
            SpdxEmitter._rust_crate_from_registry_path(
                "/root/.cargo/registry/src/"
                "index.crates.io-abc123/"
                "serde-1.0.0-beta.1/src/lib.rs"
            )
        )
        self.assertEqual(name, "serde")
        self.assertEqual(ver, "1.0.0-beta.1")

    def test_non_registry_path(self):
        name, ver = (
            SpdxEmitter._rust_crate_from_registry_path(
                "/repos/oxipng/src/main.rs"
            )
        )
        self.assertIsNone(name)
        self.assertIsNone(ver)


class TestParseCargoLock(unittest.TestCase):
    """Tests for _parse_cargo_lock."""

    def test_parse_versions(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repos" / "oxipng"
            repo.mkdir(parents=True)
            lock = repo / "Cargo.lock"
            lock.write_text(
                '# This file is automatically '
                '@generated by Cargo.\n'
                '[[package]]\n'
                'name = "bitvec"\n'
                'version = "1.0.1"\n'
                '\n'
                '[[package]]\n'
                'name = "clap"\n'
                'version = "4.5.0"\n'
            )
            files = [
                {"file_path": str(
                    repo / "src" / "main.rs"
                )},
            ]
            versions = (
                SpdxEmitter._parse_cargo_lock(files)
            )
            self.assertEqual(
                versions["bitvec"], "1.0.1"
            )
            self.assertEqual(
                versions["clap"], "4.5.0"
            )

    def test_empty_project_files(self):
        versions = (
            SpdxEmitter._parse_cargo_lock([])
        )
        self.assertEqual(versions, {})

    def test_no_cargo_lock(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repos" / "oxipng"
            repo.mkdir(parents=True)
            files = [
                {"file_path": str(
                    repo / "src" / "main.rs"
                )},
            ]
            versions = (
                SpdxEmitter._parse_cargo_lock(files)
            )
            self.assertEqual(versions, {})


class TestParseCargoToml(unittest.TestCase):
    """Tests for _parse_cargo_toml."""

    def test_parse_direct_deps(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repos" / "oxipng"
            repo.mkdir(parents=True)
            toml = repo / "Cargo.toml"
            toml.write_text(
                '[package]\n'
                'name = "oxipng"\n'
                'version = "10.1.0"\n'
                '\n'
                '[dependencies]\n'
                'clap = "4.5"\n'
                'rayon = { version = "1.10" }\n'
                'libdeflater = "1.25"\n'
                '\n'
                '[dev-dependencies]\n'
                'criterion = "0.5"\n'
            )
            files = [
                {"file_path": str(
                    repo / "src" / "main.rs"
                )},
            ]
            direct = (
                SpdxEmitter._parse_cargo_toml(files)
            )
            self.assertIn("clap", direct)
            self.assertIn("rayon", direct)
            self.assertIn("libdeflater", direct)
            # dev-dep should NOT be included
            self.assertNotIn("criterion", direct)

    def test_hyphen_underscore_normalization(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repos" / "test"
            repo.mkdir(parents=True)
            toml = repo / "Cargo.toml"
            toml.write_text(
                '[dependencies]\n'
                'libdeflate-sys = "1.25"\n'
            )
            files = [
                {"file_path": str(
                    repo / "src" / "main.rs"
                )},
            ]
            direct = (
                SpdxEmitter._parse_cargo_toml(files)
            )
            self.assertIn(
                "libdeflate-sys", direct
            )
            self.assertIn(
                "libdeflate_sys", direct
            )

    def test_empty_project_files(self):
        direct = (
            SpdxEmitter._parse_cargo_toml([])
        )
        self.assertEqual(direct, set())

    def test_no_cargo_toml(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repos" / "test"
            repo.mkdir(parents=True)
            files = [
                {"file_path": str(
                    repo / "src" / "main.rs"
                )},
            ]
            direct = (
                SpdxEmitter._parse_cargo_toml(files)
            )
            self.assertEqual(direct, set())

    def test_repos_dir_param(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repos" / "oxipng"
            repo.mkdir(parents=True)
            toml = repo / "Cargo.toml"
            toml.write_text(
                '[dependencies]\n'
                'clap = "4.5"\n'
            )
            # Use registry paths (can't walk to
            # Cargo.toml) but pass repos_dir
            files = [
                {"file_path": (
                    "/root/.cargo/registry/src/"
                    "index.crates.io-abc/"
                    "clap-4.5.0/src/lib.rs"
                )},
            ]
            direct = (
                SpdxEmitter._parse_cargo_toml(
                    files,
                    repos_dir=str(
                        Path(td) / "repos"
                    ),
                    repo_name="oxipng",
                )
            )
            self.assertIn("clap", direct)


class TestRustDirectVsTransitive(
    unittest.TestCase
):
    """Tests for direct vs transitive Rust crate
    relationship types."""

    def test_direct_gets_static_link(self):
        """Direct Rust dep gets STATIC_LINK."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repos" / "oxipng"
            repo.mkdir(parents=True)
            (repo / "Cargo.toml").write_text(
                '[dependencies]\n'
                'clap = "4.5"\n'
            )
            (repo / "Cargo.lock").write_text(
                '[[package]]\n'
                'name = "clap"\n'
                'version = "4.5.0"\n'
                '\n'
                '[[package]]\n'
                'name = "clap_builder"\n'
                'version = "4.5.0"\n'
            )
            emitter = SpdxEmitter(
                repo_name="oxipng",
                repo_version="10.1.0",
                distro="Ubuntu 22.04",
                gcc_version="gcc 11.4.0",
                repos_dir=str(
                    Path(td) / "repos"
                ),
            )
            files = [
                {
                    "sha1": "a" * 40,
                    "file_path": (
                        "/root/.cargo/registry/"
                        "src/index.crates.io-abc/"
                        "clap-4.5.0/src/lib.rs"
                    ),
                },
                {
                    "sha1": "b" * 40,
                    "file_path": (
                        "/root/.cargo/registry/"
                        "src/index.crates.io-abc/"
                        "clap_builder-4.5.0/"
                        "src/lib.rs"
                    ),
                },
                {
                    "sha1": "c" * 40,
                    "file_path": str(
                        repo / "src" / "main.rs"
                    ),
                },
            ]
            doc = emitter.emit(
                components=[],
                project_files=files,
                doc_mapping={},
                logfile_hashes={},
            )
            # clap is direct -> STATIC_LINK
            clap_pkg = next(
                p for p in doc["packages"]
                if p["name"] == "clap"
            )
            clap_rels = [
                r for r in doc["relationships"]
                if r["relatedSpdxElement"]
                == clap_pkg["SPDXID"]
            ]
            self.assertEqual(
                clap_rels[0]["relationshipType"],
                "STATIC_LINK",
            )
            # clap_builder is transitive but still
            # STATIC_LINK (all Rust crates are
            # statically compiled into the binary)
            cb_pkg = next(
                p for p in doc["packages"]
                if p["name"] == "clap_builder"
            )
            cb_rels = [
                r for r in doc["relationships"]
                if r["relatedSpdxElement"]
                == cb_pkg["SPDXID"]
            ]
            self.assertEqual(
                cb_rels[0]["relationshipType"],
                "STATIC_LINK",
            )


class TestRustCargoRegistryClassification(
    unittest.TestCase
):
    """Tests for Cargo registry path classification."""

    def _setup_bom_dir(self, td):
        meta = (
            Path(td) / "bom" / "metadata" / "bomsh"
        )
        meta.mkdir(parents=True)
        return meta

    def test_cargo_registry_classified_as_source(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            treedb = {
                "aaa": {
                    "file_path": (
                        "/root/.cargo/registry/src/"
                        "index.crates.io-abc123/"
                        "bitvec-1.0.1/src/lib.rs"
                    ),
                },
                "bbb": {
                    "file_path": (
                        "/repos/oxipng/src/main.rs"
                    ),
                },
            }
            (meta / "bomsh_omnibor_treedb").write_text(
                json.dumps(treedb)
            )
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.parse()
            self.assertEqual(
                len(result["project_source"]), 2
            )
            paths = [
                a["file_path"]
                for a in result["project_source"]
            ]
            self.assertTrue(any(
                "cargo/registry" in p for p in paths
            ))


class TestRustCrateVendoredDetection(
    unittest.TestCase
):
    """Tests for Rust crate detection in vendored."""

    def _emitter(self, binary_name="oxipng"):
        return SpdxEmitter(
            repo_name="oxipng",
            repo_version="10.1.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            binary_name=binary_name,
        )

    def test_cargo_registry_crates_detected(self):
        emitter = self._emitter()
        files = [
            {"sha1": "a1", "file_path":
                "/root/.cargo/registry/src/"
                "index.crates.io-abc/"
                "bitvec-1.0.1/src/lib.rs"},
            {"sha1": "a2", "file_path":
                "/root/.cargo/registry/src/"
                "index.crates.io-abc/"
                "bitvec-1.0.1/src/field.rs"},
            {"sha1": "a3", "file_path":
                "/root/.cargo/registry/src/"
                "index.crates.io-abc/"
                "clap-4.5.0/src/lib.rs"},
            {"sha1": "a4", "file_path":
                "/repos/oxipng/src/main.rs"},
        ]
        vendored, own = (
            emitter._detect_vendored_groups(files)
        )
        self.assertEqual(
            sorted(vendored.keys()),
            ["bitvec", "clap"],
        )
        self.assertEqual(
            len(vendored["bitvec"]), 2
        )
        self.assertEqual(
            len(vendored["clap"]), 1
        )
        self.assertEqual(len(own), 1)
        self.assertEqual(
            own[0]["file_path"],
            "/repos/oxipng/src/main.rs",
        )


class TestRustCrateEmission(unittest.TestCase):
    """Tests for Rust crate SPDX emission."""

    def _emitter(self, binary_name="oxipng"):
        return SpdxEmitter(
            repo_name="oxipng",
            repo_version="10.1.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            binary_name=binary_name,
        )

    def test_rust_crate_static_link(self):
        """Rust crates get STATIC_LINK relationship."""
        emitter = self._emitter()
        files = [
            {
                "sha1": "a" * 40,
                "file_path": (
                    "/root/.cargo/registry/src/"
                    "index.crates.io-abc/"
                    "bitvec-1.0.1/src/lib.rs"
                ),
            },
        ]
        doc = emitter.emit(
            components=[],
            project_files=files,
            doc_mapping={},
            logfile_hashes={},
        )
        names = [p["name"] for p in doc["packages"]]
        self.assertIn("bitvec", names)

        pkg = next(
            p for p in doc["packages"]
            if p["name"] == "bitvec"
        )
        # Rust crate -> crates.io download
        self.assertIn(
            "crates.io", pkg["downloadLocation"]
        )
        # Rust crate -> STATIC_LINK
        static_rels = [
            r for r in doc["relationships"]
            if r["relatedSpdxElement"]
            == pkg["SPDXID"]
            and r["relationshipType"]
            == "STATIC_LINK"
        ]
        self.assertEqual(len(static_rels), 1)
        # Comment mentions Rust crate with linkage
        self.assertIn(
            "Rust crate", pkg["comment"]
        )
        self.assertIn(
            "statically linked", pkg["comment"]
        )
        # packageSourceInfo mentions crates.io
        self.assertIn(
            "packageSourceInfo", pkg
        )
        self.assertIn(
            "crates.io", pkg["packageSourceInfo"]
        )

    def test_rust_crate_purl_with_version(self):
        """Rust crate with Cargo.lock version gets
        PURL."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repos" / "oxipng"
            repo.mkdir(parents=True)
            lock = repo / "Cargo.lock"
            lock.write_text(
                '[[package]]\n'
                'name = "bitvec"\n'
                'version = "1.0.1"\n'
            )
            emitter = SpdxEmitter(
                repo_name="oxipng",
                repo_version="10.1.0",
                distro="Ubuntu 22.04",
                gcc_version="gcc 11.4.0",
                binary_name="oxipng",
            )
            files = [
                {
                    "sha1": "a" * 40,
                    "file_path": (
                        "/root/.cargo/registry/src/"
                        "index.crates.io-abc/"
                        "bitvec-1.0.1/src/lib.rs"
                    ),
                },
                {
                    "sha1": "b" * 40,
                    "file_path": str(
                        repo / "src" / "main.rs"
                    ),
                },
            ]
            doc = emitter.emit(
                components=[],
                project_files=files,
                doc_mapping={},
                logfile_hashes={},
            )
            pkg = next(
                p for p in doc["packages"]
                if p["name"] == "bitvec"
            )
            self.assertEqual(
                pkg["versionInfo"], "1.0.1"
            )
            purls = [
                ref["referenceLocator"]
                for ref in pkg["externalRefs"]
                if ref["referenceType"] == "purl"
            ]
            self.assertEqual(len(purls), 1)
            self.assertEqual(
                purls[0],
                "pkg:cargo/bitvec@1.0.1",
            )

    def test_rs_files_included_in_source(self):
        """*.rs files are included in SPDX file list."""
        emitter = self._emitter()
        files = [
            {
                "sha1": "a" * 40,
                "file_path": (
                    "/repos/oxipng/src/main.rs"
                ),
            },
            {
                "sha1": "b" * 40,
                "file_path": (
                    "/repos/oxipng/src/lib.rs"
                ),
            },
        ]
        doc = emitter.emit(
            components=[],
            project_files=files,
            doc_mapping={},
            logfile_hashes={},
        )
        file_names = [
            f["fileName"]
            for f in doc.get("files", [])
        ]
        self.assertTrue(any(
            "main.rs" in fn for fn in file_names
        ))
        self.assertTrue(any(
            "lib.rs" in fn for fn in file_names
        ))


if __name__ == "__main__":
    unittest.main()
