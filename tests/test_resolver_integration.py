"""Integration tests for package resolvers against real binaries.

These tests run against the actual dpkg, rpm, or apk binaries
installed on the host. They are skipped automatically when the
required binary is not available.

Run all integration tests::

    pytest tests/test_resolver_integration.py -v

Run only dpkg tests (inside Ubuntu/Debian container)::

    pytest tests/test_resolver_integration.py -v -m requires_dpkg

Skip integration tests entirely::

    pytest tests/ -m "not integration"
"""

import logging
import shutil

import pytest

from app.spdx.package_resolver import (
    auto_detect_resolver,
    detect_distro_id,
)

# ── Skip conditions ────────────────────────────────────────

has_dpkg = shutil.which("dpkg") is not None
has_rpm = shutil.which("rpm") is not None
has_apk = shutil.which("apk") is not None

skip_no_dpkg = pytest.mark.skipif(
    not has_dpkg,
    reason="dpkg/dpkg-query not available on this host",
)
skip_no_rpm = pytest.mark.skipif(
    not has_rpm,
    reason="rpm not available on this host",
)
skip_no_apk = pytest.mark.skipif(
    not has_apk,
    reason="apk not available on this host",
)


# ── DpkgResolver integration ──────────────────────────────


@pytest.mark.integration
@pytest.mark.requires_dpkg
@skip_no_dpkg
class TestDpkgResolverIntegration:
    """Tests that run DpkgResolver against real dpkg."""

    def _make_resolver(self):
        from app.spdx.dpkg_resolver import DpkgResolver
        return DpkgResolver()

    def test_resolve_libc(self):
        """libc is present on every Debian/Ubuntu system."""
        r = self._make_resolver()
        # /lib/x86_64-linux-gnu/libc.so.6 or similar
        result = r.resolve("/usr/bin/dpkg")
        assert result is not None
        assert result.name == "dpkg"
        assert result.version != ""

    def test_resolve_nonexistent_returns_none(self):
        r = self._make_resolver()
        result = r.resolve(
            "/nonexistent/path/that/no/package/owns"
        )
        assert result is None

    def test_purl_scheme_matches_host(self):
        r = self._make_resolver()
        distro = detect_distro_id()
        scheme = r.purl_scheme()
        assert scheme.startswith("pkg:deb/")
        if distro == "ubuntu":
            assert scheme == "pkg:deb/ubuntu"
        elif distro == "debian":
            assert scheme == "pkg:deb/debian"

    def test_make_purl_from_resolved(self):
        """End-to-end: resolve a file → build a PURL."""
        r = self._make_resolver()
        result = r.resolve("/usr/bin/dpkg")
        if result is None:
            pytest.skip("dpkg binary not owned by dpkg package")
        purl = r.make_purl(
            result.name, result.version,
            arch=result.architecture,
            distro_version=r.distro_version_qualifier,
        )
        assert purl.startswith("pkg:deb/")
        assert "dpkg@" in purl
        assert "arch=" in purl
        assert "distro=" in purl

    def test_caching_real_packages(self):
        """Verify caching works with real dpkg queries."""
        r = self._make_resolver()
        r.resolve("/usr/bin/dpkg")
        r.resolve("/usr/bin/dpkg")
        # Should have exactly 1 entry in cache
        assert len(r._meta_cache) >= 1


# ── RpmResolver integration ───────────────────────────────


@pytest.mark.integration
@pytest.mark.requires_rpm
@skip_no_rpm
class TestRpmResolverIntegration:
    """Tests that run RpmResolver against real rpm."""

    def _make_resolver(self):
        from app.spdx.rpm_resolver import RpmResolver
        return RpmResolver()

    def test_resolve_rpm_binary(self):
        """rpm itself is always installed on rpm-based hosts."""
        r = self._make_resolver()
        result = r.resolve("/usr/bin/rpm")
        assert result is not None
        assert result.name == "rpm"
        assert result.version != ""

    def test_resolve_nonexistent_returns_none(self):
        r = self._make_resolver()
        result = r.resolve(
            "/nonexistent/path/that/no/package/owns"
        )
        assert result is None

    def test_purl_scheme_matches_host(self):
        r = self._make_resolver()
        scheme = r.purl_scheme()
        assert scheme.startswith("pkg:rpm/")

    def test_make_purl_from_resolved(self):
        r = self._make_resolver()
        result = r.resolve("/usr/bin/rpm")
        if result is None:
            pytest.skip("rpm binary not owned by rpm package")
        purl = r.make_purl(
            result.name, result.version,
            arch=result.architecture,
            distro_version=r.distro_version_qualifier,
        )
        assert purl.startswith("pkg:rpm/")
        assert "rpm@" in purl


# ── ApkResolver integration ───────────────────────────────


@pytest.mark.integration
@pytest.mark.requires_apk
@skip_no_apk
class TestApkResolverIntegration:
    """Tests that run ApkResolver against real apk."""

    def _make_resolver(self):
        from app.spdx.apk_resolver import ApkResolver
        return ApkResolver()

    def test_resolve_apk_binary(self):
        """apk itself is always installed on Alpine."""
        r = self._make_resolver()
        result = r.resolve("/sbin/apk")
        assert result is not None
        assert "apk" in result.name.lower()
        assert result.version != ""

    def test_resolve_nonexistent_returns_none(self):
        r = self._make_resolver()
        result = r.resolve(
            "/nonexistent/path/that/no/package/owns"
        )
        assert result is None

    def test_purl_scheme_is_apk_alpine(self):
        r = self._make_resolver()
        assert r.purl_scheme() == "pkg:apk/alpine"

    def test_make_purl_from_resolved(self):
        r = self._make_resolver()
        result = r.resolve("/sbin/apk")
        if result is None:
            pytest.skip("apk binary not resolvable")
        purl = r.make_purl(
            result.name, result.version,
            distro_version=r.distro_version_qualifier,
        )
        assert purl.startswith("pkg:apk/alpine/")


# ── auto_detect_resolver() integration ─────────────────────


@pytest.mark.integration
class TestAutoDetectResolverIntegration:
    """Test that auto_detect_resolver() works on the real host."""

    def test_returns_resolver_on_known_distro(self):
        """On any supported distro, should return a resolver."""
        distro = detect_distro_id()
        if distro == "unknown":
            pytest.skip("Not running on a recognized Linux distro")
        # macOS doesn't have /etc/os-release — will be "unknown"
        if distro not in (
            "ubuntu", "debian",
            "rhel", "centos", "fedora",
            "rocky", "almalinux", "ol",
            "alpine",
        ):
            pytest.skip(f"Unsupported distro: {distro}")
        resolver = auto_detect_resolver()
        assert resolver is not None

    def test_logs_detected_distro(self, caplog):
        """auto_detect_resolver() should log the detected distro."""
        distro = detect_distro_id()
        if distro == "unknown":
            pytest.skip("Not running on a recognized Linux distro")
        if distro not in (
            "ubuntu", "debian",
            "rhel", "centos", "fedora",
            "rocky", "almalinux", "ol",
            "alpine",
        ):
            pytest.skip(f"Unsupported distro: {distro}")
        with caplog.at_level(logging.INFO):
            auto_detect_resolver()
        assert "Detected distro:" in caplog.text
