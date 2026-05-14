"""Tests for ApkResolver — Alpine Linux package resolver.

All subprocess calls are mocked. No actual apk commands run.

Covers:
- purl_scheme() returns correct apk namespace
- resolve() for files owned by a package
- resolve() for unowned files
- resolve() when apk info fails
- _parse_apk_info() output parsing
- _parse_apk_version() extraction
- _strip_apk_version() name/version splitting
- Metadata caching
- distro_version_qualifier property
- make_purl() integration
"""

import subprocess
from unittest.mock import patch

from app.spdx.apk_resolver import (
    ApkResolver,
    _parse_apk_info,
    _parse_apk_version,
    _strip_apk_version,
)


# ── Helpers ────────────────────────────────────────────────


def _make_resolver(
    distro_id="alpine", distro_version="3.18",
):
    """Create an ApkResolver with mocked distro detection."""
    with patch(
        "app.spdx.apk_resolver.detect_distro_id",
        return_value=distro_id,
    ), patch(
        "app.spdx.apk_resolver.detect_distro_version",
        return_value=distro_version,
    ):
        return ApkResolver()


# ── _strip_apk_version() ──────────────────────────────────


class TestStripApkVersion:
    """Tests for version stripping from apk name-version."""

    def test_standard(self):
        assert _strip_apk_version("libssl3-3.1.4-r2") == "libssl3"

    def test_musl(self):
        assert _strip_apk_version("musl-1.2.4-r2") == "musl"

    def test_busybox(self):
        assert _strip_apk_version("busybox-1.36.1-r6") == "busybox"

    def test_no_version(self):
        assert _strip_apk_version("libssl3") == "libssl3"

    def test_hyphenated_name(self):
        assert _strip_apk_version(
            "ca-certificates-20230506-r0"
        ) == "ca-certificates"


# ── _parse_apk_version() ──────────────────────────────────


class TestParseApkVersion:
    """Tests for version extraction from apk info -v."""

    def test_standard(self):
        assert _parse_apk_version(
            "musl", "musl-1.2.4-r2"
        ) == "1.2.4-r2"

    def test_no_prefix_match(self):
        assert _parse_apk_version(
            "other", "musl-1.2.4-r2"
        ) == "musl-1.2.4-r2"

    def test_empty(self):
        assert _parse_apk_version("pkg", "") == ""


# ── _parse_apk_info() ─────────────────────────────────────


class TestParseApkInfo:
    """Tests for parsing apk info -a output."""

    def test_full_output(self):
        output = (
            "musl-1.2.4-r2 description:\n"
            "the musl c library\n"
            "\n"
            "musl-1.2.4-r2 webpage:\n"
            "https://musl.libc.org/\n"
            "\n"
            "musl-1.2.4-r2 license:\n"
            "MIT\n"
            "\n"
            "musl-1.2.4-r2 origin:\n"
            "musl\n"
            "\n"
            "musl-1.2.4-r2 maintainer:\n"
            "Timo Teras <timo.teras@iki.fi>\n"
        )
        meta = _parse_apk_info(output)
        assert meta["description"] == "the musl c library"
        assert meta["webpage"] == "https://musl.libc.org/"
        assert meta["license"] == "MIT"
        assert meta["origin"] == "musl"
        assert meta["maintainer"] == (
            "Timo Teras <timo.teras@iki.fi>"
        )

    def test_partial_output(self):
        output = (
            "pkg-1.0-r0 description:\n"
            "some package\n"
            "\n"
            "pkg-1.0-r0 webpage:\n"
            "https://example.com\n"
        )
        meta = _parse_apk_info(output)
        assert meta["description"] == "some package"
        assert meta["webpage"] == "https://example.com"
        assert "license" not in meta

    def test_empty_output(self):
        assert _parse_apk_info("") == {}


# ── purl_scheme() ─────────────────────────────────────────


class TestApkResolverPurlScheme:

    def test_alpine(self):
        r = _make_resolver("alpine", "3.18")
        assert r.purl_scheme() == "pkg:apk/alpine"


# ── resolve() success ──────────────────────────────────────


class TestApkResolverResolve:

    @patch("subprocess.check_output")
    def test_resolves_known_file(self, mock_subproc):
        r = _make_resolver()
        path = "/usr/lib/libssl.so.3"

        def side_effect(cmd, **kwargs):
            if "--who-owns" in cmd:
                return (
                    f"{path} is owned by libssl3-3.1.4-r2"
                )
            if "-v" in cmd:
                return "libssl3-3.1.4-r2"
            if "-a" in cmd:
                return (
                    "libssl3-3.1.4-r2 description:\n"
                    "SSL shared libraries\n"
                    "\n"
                    "libssl3-3.1.4-r2 webpage:\n"
                    "https://www.openssl.org/\n"
                    "\n"
                    "libssl3-3.1.4-r2 origin:\n"
                    "openssl\n"
                    "\n"
                    "libssl3-3.1.4-r2 maintainer:\n"
                    "Alpine Team\n"
                )
            raise ValueError(f"Unexpected cmd: {cmd}")

        mock_subproc.side_effect = side_effect
        result = r.resolve(path)

        assert result is not None
        assert result.name == "libssl3"
        assert result.version == "3.1.4-r2"
        assert result.source == "openssl"
        assert result.homepage == "https://www.openssl.org/"
        assert result.maintainer == "Alpine Team"
        assert result.extra.get("description") == (
            "SSL shared libraries"
        )


# ── resolve() failure ──────────────────────────────────────


class TestApkResolverResolveFailure:

    @patch("subprocess.check_output")
    def test_unowned_file_returns_none(self, mock_subproc):
        r = _make_resolver()
        mock_subproc.side_effect = subprocess.CalledProcessError(
            1, "apk"
        )
        assert r.resolve("/tmp/random/file") is None

    @patch("subprocess.check_output")
    def test_no_owned_by_message(self, mock_subproc):
        r = _make_resolver()
        mock_subproc.return_value = (
            "ERROR: /tmp/foo: Could not find owner package"
        )
        assert r.resolve("/tmp/foo") is None

    @patch("subprocess.check_output")
    def test_version_and_info_both_fail(self, mock_subproc):
        """File is owned but all metadata queries fail."""
        r = _make_resolver()

        def side_effect(cmd, **kwargs):
            if "--who-owns" in cmd:
                return "/some/file is owned by pkg-1.0-r0"
            raise subprocess.CalledProcessError(1, "apk")

        mock_subproc.side_effect = side_effect
        assert r.resolve("/some/file") is None

    @patch("subprocess.check_output")
    def test_oserror_returns_none(self, mock_subproc):
        r = _make_resolver()
        mock_subproc.side_effect = OSError("not found")
        assert r.resolve("/usr/lib/libfoo.so") is None


# ── Caching ────────────────────────────────────────────────


class TestApkResolverCaching:

    @patch("subprocess.check_output")
    def test_second_resolve_uses_cache(self, mock_subproc):
        r = _make_resolver()

        def side_effect(cmd, **kwargs):
            if "--who-owns" in cmd:
                return "/x is owned by musl-1.2.4-r2"
            if "-v" in cmd:
                return "musl-1.2.4-r2"
            if "-a" in cmd:
                return (
                    "musl-1.2.4-r2 origin:\nmusl\n"
                )
            raise ValueError(f"Unexpected: {cmd}")

        mock_subproc.side_effect = side_effect

        r.resolve("/usr/lib/ld-musl-x86_64.so.1")
        r.resolve("/usr/lib/libc.musl-x86_64.so.1")

        # apk info -v should only be called once (cached)
        info_v_calls = [
            c for c in mock_subproc.call_args_list
            if "-v" in c[0][0]
        ]
        assert len(info_v_calls) == 1

    @patch("subprocess.check_output")
    def test_failed_lookup_cached(self, mock_subproc):
        r = _make_resolver()

        def side_effect(cmd, **kwargs):
            if "--who-owns" in cmd:
                return "/x is owned by badpkg-1.0-r0"
            raise subprocess.CalledProcessError(1, "apk")

        mock_subproc.side_effect = side_effect

        assert r.resolve("/some/path") is None
        assert r.resolve("/other/path") is None

        info_calls = [
            c for c in mock_subproc.call_args_list
            if "-v" in c[0][0] or "-a" in c[0][0]
        ]
        # Only the first resolve should attempt metadata queries
        # (2 calls: -v and -a), second is cached
        assert len(info_calls) == 2


# ── distro_version_qualifier ───────────────────────────────


class TestApkDistroVersionQualifier:

    def test_with_version(self):
        r = _make_resolver("alpine", "3.18")
        assert r.distro_version_qualifier == "alpine-3.18"

    def test_without_version(self):
        r = _make_resolver("alpine", "")
        assert r.distro_version_qualifier == "alpine"


# ── make_purl() integration ────────────────────────────────


class TestApkResolverMakePurl:

    def test_full_purl(self):
        r = _make_resolver("alpine", "3.18")
        purl = r.make_purl(
            "libssl3", "3.1.4-r2",
            arch="x86_64",
            distro_version="alpine-3.18",
        )
        assert purl == (
            "pkg:apk/alpine/libssl3@3.1.4-r2"
            "?arch=x86_64&distro=alpine-3.18"
        )

    def test_minimal_purl(self):
        r = _make_resolver("alpine", "3.18")
        purl = r.make_purl("musl", "1.2.4-r2")
        assert purl == "pkg:apk/alpine/musl@1.2.4-r2"


# ── is_package_installed ───────────────────────────────────


class TestApkIsPackageInstalled:

    @patch("subprocess.check_output")
    def test_installed_returns_true(self, mock_sub):
        mock_sub.return_value = "musl-1.2.4-r2"
        r = _make_resolver()
        assert r.is_package_installed("musl") is True

    @patch("subprocess.check_output")
    def test_error_returns_false(self, mock_sub):
        mock_sub.side_effect = (
            subprocess.CalledProcessError(1, "apk")
        )
        r = _make_resolver()
        assert r.is_package_installed("nope") is False

    @patch("subprocess.check_output")
    def test_oserror_returns_false(self, mock_sub):
        mock_sub.side_effect = OSError("no apk")
        r = _make_resolver()
        assert r.is_package_installed("x") is False


# ── install_hint ───────────────────────────────────────────


class TestApkInstallHint:

    def test_returns_apk_command(self):
        r = _make_resolver()
        assert r.install_hint(["a", "b"]) == (
            "apk add a b"
        )
