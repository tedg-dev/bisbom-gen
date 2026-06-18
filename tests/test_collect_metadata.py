"""Tests for collect_metadata.py refactored to use PackageResolver.

All OS package resolution is mocked via a fake PackageResolver.
No real dpkg/rpm/apk calls are made.

Covers:
- main() resolves system files via injected resolver
- main() handles unresolvable files
- main() populates metadata from ResolvedPackage fields
- main() outputs correct JSON structure
- main() passes through extra metadata fields
- _version_from_tag() parsing
- _detect_repo_version() config branch priority
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from app.collect_metadata import (
    _detect_distro,
    _detect_repo_version,
    _gcc_version,
    _version_from_tag,
    main,
)
from app.spdx.package_resolver import (
    PackageResolver,
    ResolvedPackage,
)


# ── Helpers ────────────────────────────────────────────────


class FakeResolver(PackageResolver):
    """A test resolver that returns canned results."""

    def __init__(self, file_map=None):
        self._file_map = file_map or {}

    def resolve(self, file_path):
        return self._file_map.get(file_path)

    def purl_scheme(self):
        return "pkg:deb/ubuntu"


def _make_treedb(system_files, repos_dir="/workspace/repos"):
    """Create a minimal treedb dict for testing."""
    treedb = {}
    for i, fp in enumerate(system_files):
        sha = f"sha{i:04d}"
        treedb[sha] = {"file_path": fp}
    # Add a repo file (should be excluded)
    treedb["sha_repo"] = {
        "file_path": f"{repos_dir}/curl/src/main.c",
    }
    return treedb


def _run_main(treedb, resolver, repos_dir="/workspace/repos"):
    """Run main() in a temp dir and return parsed output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        treedb_path = os.path.join(tmpdir, "treedb.json")
        with open(treedb_path, "w", encoding="utf-8") as f:
            json.dump(treedb, f)
        out_dir = os.path.join(tmpdir, "out")
        main(
            treedb_path, repos_dir, out_dir,
            resolver=resolver,
        )
        out_path = os.path.join(
            out_dir, "component_metadata.json",
        )
        with open(out_path, encoding="utf-8") as f:
            return json.load(f)


# ── _version_from_tag() ───────────────────────────────────


class TestVersionFromTag:

    def test_v_prefix(self):
        assert _version_from_tag("v0.25.9") == "0.25.9"

    def test_no_prefix(self):
        assert _version_from_tag("7.2.4") == "7.2.4"

    def test_release_prefix(self):
        assert _version_from_tag("release-1.2.3") == "1.2.3"

    def test_main_branch(self):
        assert _version_from_tag("main") is None

    def test_none(self):
        assert _version_from_tag(None) is None

    def test_empty(self):
        assert _version_from_tag("") is None


# ── main() with resolver ──────────────────────────────────


class TestMainWithResolver:

    def test_resolves_system_files(self):
        """System files are resolved via the injected resolver."""
        pkg = ResolvedPackage(
            name="libssl3", version="3.0.2-0ubuntu1.15",
            source="openssl", architecture="amd64",
            maintainer="Ubuntu", homepage="https://openssl.org",
            section="libs",
        )
        resolver = FakeResolver({
            "/usr/lib/x86_64-linux-gnu/libssl.so.3": pkg,
        })
        treedb = _make_treedb([
            "/usr/lib/x86_64-linux-gnu/libssl.so.3",
        ])
        result = _run_main(treedb, resolver)

        assert "libssl3" in result["pkg_metadata"]
        meta = result["pkg_metadata"]["libssl3"]
        assert meta["Package"] == "libssl3"
        assert meta["Version"] == "3.0.2-0ubuntu1.15"
        assert meta["Source"] == "openssl"
        assert meta["Architecture"] == "amd64"
        assert meta["Maintainer"] == "Ubuntu"
        assert meta["Homepage"] == "https://openssl.org"
        assert meta["Section"] == "libs"

    def test_unresolvable_files_in_failed(self):
        """Files not owned by any package go to unresolved."""
        resolver = FakeResolver({})
        treedb = _make_treedb([
            "/tmp/custom/lib.so",
        ])
        result = _run_main(treedb, resolver)

        assert len(result["unresolved_files"]) >= 1
        assert len(result["pkg_metadata"]) == 0

    def test_file_to_pkg_mapping(self):
        """file_to_pkg maps treedb paths to package names."""
        pkg = ResolvedPackage(
            name="libc6", version="2.35",
        )
        resolver = FakeResolver({
            "/usr/lib/x86_64-linux-gnu/libc.so.6": pkg,
        })
        treedb = _make_treedb([
            "/usr/lib/x86_64-linux-gnu/libc.so.6",
        ])
        result = _run_main(treedb, resolver)

        assert result["file_to_pkg"][
            "/usr/lib/x86_64-linux-gnu/libc.so.6"
        ] == "libc6"

    def test_extra_fields_passed_through(self):
        """Extra fields from ResolvedPackage.extra appear in metadata."""
        pkg = ResolvedPackage(
            name="testpkg", version="1.0",
            extra={"Priority": "optional", "Custom": "value"},
        )
        resolver = FakeResolver({
            "/usr/lib/libtest.so": pkg,
        })
        treedb = _make_treedb(["/usr/lib/libtest.so"])
        result = _run_main(treedb, resolver)

        meta = result["pkg_metadata"]["testpkg"]
        assert meta["Priority"] == "optional"
        assert meta["Custom"] == "value"

    def test_empty_optional_fields_omitted(self):
        """Empty optional fields are not included in metadata."""
        pkg = ResolvedPackage(
            name="minimal", version="1.0",
        )
        resolver = FakeResolver({
            "/usr/lib/libmin.so": pkg,
        })
        treedb = _make_treedb(["/usr/lib/libmin.so"])
        result = _run_main(treedb, resolver)

        meta = result["pkg_metadata"]["minimal"]
        assert meta["Package"] == "minimal"
        assert meta["Version"] == "1.0"
        assert "Source" not in meta
        assert "Maintainer" not in meta
        assert "Homepage" not in meta

    def test_repo_files_excluded(self):
        """Files under repos_dir are not resolved."""
        resolver = FakeResolver({})
        treedb = _make_treedb([])
        result = _run_main(treedb, resolver)

        assert len(result["pkg_metadata"]) == 0
        assert len(result["file_to_pkg"]) == 0

    def test_multiple_files_same_package(self):
        """Multiple files from the same package produce one metadata entry."""
        pkg = ResolvedPackage(
            name="libssl3", version="3.0.2",
        )
        resolver = FakeResolver({
            "/usr/lib/libssl.so.3": pkg,
            "/usr/lib/libcrypto.so.3": pkg,
        })
        treedb = _make_treedb([
            "/usr/lib/libssl.so.3",
            "/usr/lib/libcrypto.so.3",
        ])
        result = _run_main(treedb, resolver)

        assert len(result["pkg_metadata"]) == 1
        assert "libssl3" in result["pkg_metadata"]

    def test_output_json_structure(self):
        """Output JSON has all required top-level keys."""
        resolver = FakeResolver({})
        treedb = _make_treedb([])
        result = _run_main(treedb, resolver)

        assert "distro" in result
        assert "gcc_version" in result
        assert "pkg_metadata" in result
        assert "file_to_pkg" in result
        assert "unresolved_files" in result

    def test_default_resolver_auto_detected(self):
        """main() falls back to auto_detect_resolver when none given."""
        treedb = _make_treedb([])
        with tempfile.TemporaryDirectory() as tmpdir:
            treedb_path = os.path.join(tmpdir, "treedb.json")
            with open(treedb_path, "w", encoding="utf-8") as f:
                json.dump(treedb, f)
            out_dir = os.path.join(tmpdir, "out")
            with mock.patch(
                "app.spdx.package_resolver.auto_detect_resolver",
                return_value=FakeResolver({}),
            ) as auto:
                main(treedb_path, "/workspace/repos", out_dir)
            auto.assert_called_once()

    def test_repo_version_printed(self):
        """repo_name + config_branch flows through to repo_version."""
        treedb = _make_treedb([])
        with tempfile.TemporaryDirectory() as tmpdir:
            treedb_path = os.path.join(tmpdir, "treedb.json")
            with open(treedb_path, "w", encoding="utf-8") as f:
                json.dump(treedb, f)
            out_dir = os.path.join(tmpdir, "out")
            main(
                treedb_path, "/workspace/repos", out_dir,
                repo_name="curl", config_branch="v7.88.0",
                resolver=FakeResolver({}),
            )
            with open(
                os.path.join(out_dir, "component_metadata.json"),
                encoding="utf-8",
            ) as f:
                result = json.load(f)
        assert result["repo_version"] == "7.88.0"


# ── _detect_distro() ──────────────────────────────────────


class TestDetectDistro:

    def test_reads_pretty_name(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "os-release")
            with open(p, "w", encoding="utf-8") as f:
                f.write('NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 22.04.3 LTS"\n')
            assert _detect_distro(p) == "Ubuntu 22.04.3 LTS"

    def test_no_pretty_name(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "os-release")
            with open(p, "w", encoding="utf-8") as f:
                f.write("NAME=Foo\n")
            assert _detect_distro(p) == "unknown"

    def test_missing_file(self):
        assert _detect_distro("/no/such/os-release") == "unknown"


# ── _gcc_version() ────────────────────────────────────────


class TestGccVersion:

    def test_first_line(self):
        with mock.patch(
            "app.collect_metadata.subprocess.check_output",
            return_value="gcc (Ubuntu) 11.4.0\nCopyright\n",
        ):
            assert _gcc_version() == "gcc (Ubuntu) 11.4.0"

    def test_missing_gcc(self):
        with mock.patch(
            "app.collect_metadata.subprocess.check_output",
            side_effect=FileNotFoundError,
        ):
            assert _gcc_version() == "unknown"

    def test_subprocess_error(self):
        with mock.patch(
            "app.collect_metadata.subprocess.check_output",
            side_effect=subprocess.CalledProcessError(1, "gcc"),
        ):
            assert _gcc_version() == "unknown"


# ── _detect_repo_version() ────────────────────────────────


class TestDetectRepoVersion:

    def test_config_branch_wins(self):
        # Config tag is used without touching the filesystem.
        assert _detect_repo_version(
            "curl", "/no/such/dir", config_branch="v7.88.0",
        ) == "7.88.0"

    def test_missing_repo_dir(self):
        assert _detect_repo_version("ghost", "/no/such/dir") is None

    def test_import_error_returns_none(self):
        with mock.patch.dict(
            sys.modules, {"app.version_detection": None}
        ):
            assert _detect_repo_version(
                "curl", "/no/such/dir",
            ) is None

    def test_empty_repo_returns_none(self):
        with tempfile.TemporaryDirectory() as repos:
            (Path(repos) / "curl").mkdir()
            assert _detect_repo_version("curl", repos) is None

    def test_collects_root_include_src_files(self):
        with tempfile.TemporaryDirectory() as repos:
            repo = Path(repos) / "curl"
            (repo / "include").mkdir(parents=True)
            (repo / "src").mkdir()
            (repo / "VERSION").write_text("1.0\n", encoding="utf-8")
            (repo / "include" / "v.h").write_text(
                "#define V 1\n", encoding="utf-8"
            )
            (repo / "src" / "s.h").write_text(
                "#define S 1\n", encoding="utf-8"
            )

            captured = {}

            class FakeDetector:
                def detect(self, name, files):
                    captured["name"] = name
                    captured["files"] = files
                    return "9.9.9"

            with mock.patch(
                "app.version_detection.VendoredVersionDetector",
                FakeDetector,
            ):
                result = _detect_repo_version("curl", repos)

        assert result == "9.9.9"
        assert captured["name"] == "curl"
        assert any(f.endswith("include/v.h") for f in captured["files"])
        assert any(f.endswith("src/s.h") for f in captured["files"])
