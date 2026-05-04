"""Tests for DpkgResolver — Debian/Ubuntu package resolver.

All subprocess calls are mocked. No actual dpkg commands run.

Covers:
- purl_scheme() returns correct deb namespace
- resolve() for files owned by a package
- resolve() for files not owned by any package
- resolve() when dpkg-query fails
- Metadata caching (repeated calls reuse cache)
- _file_to_package() edge cases
- distro_version_qualifier property
- make_purl() integration with DpkgResolver
"""

import subprocess
from unittest.mock import patch

from app.spdx.dpkg_resolver import DpkgResolver


# ── Helpers ────────────────────────────────────────────────


def _make_resolver(
    distro_id="ubuntu", distro_version="22.04",
):
    """Create a DpkgResolver with mocked distro detection."""
    with patch(
        "app.spdx.dpkg_resolver.detect_distro_id",
        return_value=distro_id,
    ), patch(
        "app.spdx.dpkg_resolver.detect_distro_version",
        return_value=distro_version,
    ):
        return DpkgResolver()


def _dpkg_s_output(pkg_name, path):
    """Simulate ``dpkg -S <path>`` output."""
    return f"{pkg_name}: {path}"


def _dpkg_query_output(
    name="libssl3", version="3.0.2-0ubuntu1.15",
    source="openssl", arch="amd64",
    maintainer="Ubuntu Developers",
    homepage="https://www.openssl.org/",
    section="libs", priority="optional",
):
    """Simulate ``dpkg-query -W -f`` pipe-delimited output."""
    return "|".join([
        name, version, source, arch,
        maintainer, homepage, section, priority,
    ])


# ── purl_scheme() ─────────────────────────────────────────


class TestDpkgResolverPurlScheme:
    """Tests for purl_scheme() across deb-family distros."""

    def test_ubuntu(self):
        r = _make_resolver("ubuntu", "22.04")
        assert r.purl_scheme() == "pkg:deb/ubuntu"

    def test_debian(self):
        r = _make_resolver("debian", "12")
        assert r.purl_scheme() == "pkg:deb/debian"


# ── resolve() success ──────────────────────────────────────


class TestDpkgResolverResolve:
    """Tests for resolve() with successful dpkg lookups."""

    @patch("subprocess.check_output")
    def test_resolves_known_file(self, mock_subproc):
        r = _make_resolver()
        path = "/usr/lib/x86_64-linux-gnu/libssl.so.3"

        def side_effect(cmd, **kwargs):
            if cmd[0] == "dpkg" and cmd[1] == "-S":
                return _dpkg_s_output("libssl3", path)
            if cmd[0] == "dpkg-query":
                return _dpkg_query_output()
            raise ValueError(f"Unexpected cmd: {cmd}")

        mock_subproc.side_effect = side_effect
        result = r.resolve(path)

        assert result is not None
        assert result.name == "libssl3"
        assert result.version == "3.0.2-0ubuntu1.15"
        assert result.source == "openssl"
        assert result.architecture == "amd64"
        assert result.maintainer == "Ubuntu Developers"
        assert result.homepage == "https://www.openssl.org/"
        assert result.section == "libs"
        assert result.extra == {"Priority": "optional"}

    @patch("subprocess.check_output")
    def test_multi_package_takes_first(self, mock_subproc):
        """When dpkg -S returns multiple packages, take the first."""
        r = _make_resolver()
        path = "/usr/lib/x86_64-linux-gnu/libz.so.1"

        def side_effect(cmd, **kwargs):
            if cmd[0] == "dpkg" and cmd[1] == "-S":
                return f"zlib1g, zlib1g-dev: {path}"
            if cmd[0] == "dpkg-query":
                return _dpkg_query_output(
                    name="zlib1g", version="1.2.11",
                    source="zlib", arch="amd64",
                    maintainer="Mark", homepage="https://zlib.net",
                    section="libs", priority="",
                )
            raise ValueError(f"Unexpected cmd: {cmd}")

        mock_subproc.side_effect = side_effect
        result = r.resolve(path)
        assert result is not None
        assert result.name == "zlib1g"


# ── resolve() failure ──────────────────────────────────────


class TestDpkgResolverResolveFailure:
    """Tests for resolve() when files aren't in any package."""

    @patch("subprocess.check_output")
    def test_unowned_file_returns_none(self, mock_subproc):
        r = _make_resolver()
        mock_subproc.side_effect = subprocess.CalledProcessError(
            1, "dpkg"
        )
        result = r.resolve("/tmp/some/random/file")
        assert result is None

    @patch("subprocess.check_output")
    def test_dpkg_query_failure_returns_none(self, mock_subproc):
        """dpkg -S succeeds but dpkg-query fails."""
        r = _make_resolver()
        call_count = [0]

        def side_effect(cmd, **kwargs):
            call_count[0] += 1
            if cmd[0] == "dpkg" and cmd[1] == "-S":
                return "somepkg: /some/path"
            raise subprocess.CalledProcessError(
                1, "dpkg-query"
            )

        mock_subproc.side_effect = side_effect
        result = r.resolve("/some/path")
        assert result is None

    @patch("subprocess.check_output")
    def test_oserror_returns_none(self, mock_subproc):
        """OSError (dpkg not installed) returns None."""
        r = _make_resolver()
        mock_subproc.side_effect = OSError("not found")
        result = r.resolve("/usr/lib/libfoo.so")
        assert result is None


# ── Caching ────────────────────────────────────────────────


class TestDpkgResolverCaching:
    """Tests for metadata caching behavior."""

    @patch("subprocess.check_output")
    def test_second_resolve_uses_cache(self, mock_subproc):
        r = _make_resolver()

        def side_effect(cmd, **kwargs):
            if cmd[0] == "dpkg" and cmd[1] == "-S":
                return "libssl3: /some/path"
            if cmd[0] == "dpkg-query":
                return _dpkg_query_output()
            raise ValueError(f"Unexpected cmd: {cmd}")

        mock_subproc.side_effect = side_effect

        # First call — hits subprocess
        r.resolve("/usr/lib/x86_64-linux-gnu/libssl.so.3")
        # Second call for different file, same package
        r.resolve("/usr/lib/x86_64-linux-gnu/libcrypto.so.3")

        # dpkg-query should only be called once (cached)
        dpkg_query_calls = [
            c for c in mock_subproc.call_args_list
            if c[0][0][0] == "dpkg-query"
        ]
        assert len(dpkg_query_calls) == 1

    @patch("subprocess.check_output")
    def test_failed_lookup_cached(self, mock_subproc):
        """A failed dpkg-query is cached as None."""
        r = _make_resolver()

        def side_effect(cmd, **kwargs):
            if cmd[0] == "dpkg" and cmd[1] == "-S":
                return "badpkg: /some/path"
            raise subprocess.CalledProcessError(
                1, "dpkg-query"
            )

        mock_subproc.side_effect = side_effect

        assert r.resolve("/some/path") is None
        assert r.resolve("/other/path") is None

        # dpkg-query called only once — second was cached
        dpkg_query_calls = [
            c for c in mock_subproc.call_args_list
            if c[0][0][0] == "dpkg-query"
        ]
        assert len(dpkg_query_calls) == 1


# ── distro_version_qualifier ───────────────────────────────


class TestDistroVersionQualifier:
    """Tests for the distro_version_qualifier property."""

    def test_with_version(self):
        r = _make_resolver("ubuntu", "22.04")
        assert r.distro_version_qualifier == "ubuntu-22.04"

    def test_without_version(self):
        r = _make_resolver("debian", "")
        assert r.distro_version_qualifier == "debian"


# ── make_purl() integration ────────────────────────────────


class TestDpkgResolverMakePurl:
    """Tests for make_purl() inherited from PackageResolver."""

    def test_full_purl(self):
        r = _make_resolver("ubuntu", "22.04")
        purl = r.make_purl(
            "libssl3", "3.0.2-0ubuntu1.15",
            arch="amd64",
            distro_version="ubuntu-22.04",
        )
        assert purl == (
            "pkg:deb/ubuntu/libssl3@3.0.2-0ubuntu1.15"
            "?arch=amd64&distro=ubuntu-22.04"
        )

    def test_minimal_purl(self):
        r = _make_resolver("debian", "12")
        purl = r.make_purl("libc6", "2.36-9")
        assert purl == "pkg:deb/debian/libc6@2.36-9"
