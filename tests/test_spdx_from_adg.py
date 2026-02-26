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
            "curl_version": "8.19.0-DEV",
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
            resolver = ComponentResolver(path)

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
            resolver = ComponentResolver(path)

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
            resolver = ComponentResolver(path)

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
            resolver = ComponentResolver(path)

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
            resolver = ComponentResolver(path)

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
            resolver = ComponentResolver(path)

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
            resolver = ComponentResolver(path)
            self.assertEqual(
                resolver.distro_codename,
                "ubuntu-22.04",
            )

    def test_no_dynamic_libs_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path)
            # Don't load dynamic libs
            components = (
                resolver.resolve_dynamic_components()
            )
            self.assertEqual(len(components), 0)

    def test_libs_without_version_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path)

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
        # Root + gcc only = 2 (libc6 excluded)
        self.assertEqual(len(doc["packages"]), 2)
        names = [p["name"] for p in doc["packages"]]
        self.assertNotIn("libc6", names)
        # No DYNAMIC_LINK relationships
        dyn_rels = [
            r for r in doc["relationships"]
            if r["relationshipType"]
            == "DYNAMIC_LINK"
        ]
        self.assertEqual(len(dyn_rels), 0)

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
                    "Vendored/statically linked",
                    pkg["comment"],
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

        # server.c should be owned by root
        root_contains = [
            r for r in doc["relationships"]
            if r["spdxElementId"]
            == "SPDXRef-Package-root"
            and r["relationshipType"] == "CONTAINS"
        ]
        self.assertEqual(len(root_contains), 1)

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
        """Detect X.Y when no PATCH define."""
        with tempfile.TemporaryDirectory() as td:
            h = Path(td) / "lib.h"
            h.write_text(
                "#define XXH_VERSION_MAJOR    0\n"
                "#define XXH_VERSION_MINOR    8\n"
                "#define XXH_VERSION_RELEASE  3\n"
            )
            det = VendoredVersionDetector()
            # RELEASE != PATCH, so only MAJOR.MINOR
            ver = det.detect("xxhash", [str(h)])
            self.assertEqual(ver, "0.8")

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
        det = VendoredVersionDetector()
        result = det._parse_version_file(
            Path("/nonexistent/VERSION")
        )
        self.assertIsNone(result)

    def test_header_unreadable(self):
        """Gracefully handle unreadable header."""
        det = VendoredVersionDetector()
        result = det._parse_header_defines(
            "/nonexistent/lib.h", "lib"
        )
        self.assertIsNone(result)

    def test_header_comment_unreadable(self):
        """Gracefully handle unreadable header."""
        det = VendoredVersionDetector()
        result = det._parse_header_comment(
            "/nonexistent/lib.h"
        )
        self.assertIsNone(result)

    def test_pc_in_unreadable(self):
        """Gracefully handle unreadable .pc.in."""
        det = VendoredVersionDetector()
        result = det._parse_pc_in(
            Path("/nonexistent/lib.pc.in")
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
        with tempfile.TemporaryDirectory() as td:
            meta = {
                "distro": "Debian GNU/Linux 12",
                "gcc_version": "gcc 12",
                "curl_version": "8.0",
                "pkg_metadata": {},
                "file_to_pkg": {},
                "unresolved_files": [],
            }
            path = Path(td) / "meta.json"
            path.write_text(json.dumps(meta))
            resolver = ComponentResolver(str(path))
            self.assertEqual(
                resolver.distro_codename, "linux"
            )


class TestAdgSpdxGenerator(unittest.TestCase):
    """Tests for AdgSpdxGenerator facade."""

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
            "curl_version": "8.19.0",
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
                "curl_version": "8.19.0",
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


if __name__ == "__main__":
    unittest.main()
