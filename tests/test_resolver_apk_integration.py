"""
Docker integration tests for ApkResolver (#105 A11).

Runs inside the Alpine 3.19 container to validate that
ApkResolver correctly resolves file paths to apk package
metadata and produces valid PURLs.

Requirements:
  - Docker daemon running
  - omnibor-env:alpine image built

Run::

    docker compose -f docker/docker-compose.yml run --rm \\
        omnibor-alpine python3 -m pytest \\
        tests/test_resolver_apk_integration.py -v

Skip in normal test runs::

    pytest tests/ -m "not docker_integration"
"""

import shutil
import subprocess
import unittest

import pytest

# ── Skip conditions ──────────────────────────────────

_has_apk = shutil.which("apk") is not None

skip_no_apk = pytest.mark.skipif(
    not _has_apk,
    reason="apk not available (not on Alpine)",
)


def _on_alpine():
    """True if running on Alpine Linux."""
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("ID="):
                    distro = (
                        line.split("=", 1)[1]
                        .strip().strip('"').lower()
                    )
                    return distro == "alpine"
    except OSError:
        pass
    return False


skip_not_alpine = pytest.mark.skipif(
    not _on_alpine(),
    reason="Not running on Alpine Linux",
)


@pytest.mark.docker_integration
@skip_no_apk
@skip_not_alpine
class TestApkResolver(unittest.TestCase):
    """Integration test: ApkResolver on Alpine 3.19.

    Validates:
    - auto_detect_resolver() returns ApkResolver
    - File → package resolution works
    - PURL scheme is pkg:apk/alpine
    - Package metadata is populated
    - Known files resolve to expected packages
    """

    _resolver = None

    @classmethod
    def setUpClass(cls):
        """Create resolver instance."""
        from app.spdx.package_resolver import (
            auto_detect_resolver,
        )
        cls._resolver = auto_detect_resolver()

    # ── Auto-detection ──────────────────────────────

    def test_auto_detect_returns_apk_resolver(self):
        """auto_detect_resolver() should return ApkResolver."""
        from app.spdx.apk_resolver import ApkResolver
        self.assertIsInstance(
            self._resolver, ApkResolver,
        )

    def test_purl_scheme_is_apk(self):
        """PURL scheme should be pkg:apk/alpine."""
        scheme = self._resolver.purl_scheme()
        self.assertEqual(
            scheme, "pkg:apk/alpine",
            f"Expected pkg:apk/alpine, got {scheme}",
        )

    # ── File resolution ─────────────────────────────

    def test_resolve_libssl(self):
        """Resolve libssl to openssl package."""
        libssl = _find_lib("libssl.so")
        if not libssl:
            self.skipTest("libssl.so not found")

        result = self._resolver.resolve(libssl)
        self.assertIsNotNone(
            result,
            f"Failed to resolve {libssl}",
        )
        self.assertTrue(
            "ssl" in result.name.lower()
            or "openssl" in result.name.lower(),
            f"Expected ssl-related package, "
            f"got {result.name}",
        )

    def test_resolve_musl(self):
        """Resolve musl libc (Alpine's libc)."""
        musl = _find_lib("libc.musl")
        if not musl:
            # Try the ld-musl linker path
            musl = _find_lib("ld-musl")
        if not musl:
            self.skipTest("musl libc not found")

        result = self._resolver.resolve(musl)
        self.assertIsNotNone(
            result,
            f"Failed to resolve {musl}",
        )
        self.assertIn(
            "musl", result.name.lower(),
            f"Expected musl package, got {result.name}",
        )

    def test_resolve_gcc(self):
        """Resolve gcc binary to gcc package."""
        gcc = shutil.which("gcc")
        if not gcc:
            self.skipTest("gcc not installed")

        result = self._resolver.resolve(gcc)
        self.assertIsNotNone(
            result,
            f"Failed to resolve {gcc}",
        )
        self.assertIn(
            "gcc", result.name.lower(),
            f"Expected gcc package, got {result.name}",
        )

    def test_resolve_nonexistent_returns_none(self):
        """Non-existent file should return None."""
        result = self._resolver.resolve(
            "/nonexistent/path/to/file.so"
        )
        self.assertIsNone(result)

    # ── Metadata quality ────────────────────────────

    def test_resolved_package_has_version(self):
        """Resolved package should have a version."""
        gcc = shutil.which("gcc")
        if not gcc:
            self.skipTest("gcc not installed")

        result = self._resolver.resolve(gcc)
        self.assertIsNotNone(result)
        self.assertTrue(
            len(result.version) > 0,
            "Expected non-empty version",
        )

    def test_resolved_package_has_origin(self):
        """Resolved package should have origin (source)."""
        gcc = shutil.which("gcc")
        if not gcc:
            self.skipTest("gcc not installed")

        result = self._resolver.resolve(gcc)
        self.assertIsNotNone(result)
        # Alpine 'origin' is the source package name
        self.assertTrue(
            len(result.source) > 0,
            "Expected non-empty source/origin",
        )

    # ── PURL generation ─────────────────────────────

    def test_make_purl_format(self):
        """PURL should follow pkg:apk/alpine/<name>@<ver>."""
        purl = self._resolver.make_purl(
            "musl", "1.2.4-r2",
            distro_version=(
                self._resolver.distro_version_qualifier
            ),
        )
        self.assertTrue(
            purl.startswith("pkg:apk/alpine/"),
            f"Expected pkg:apk/alpine prefix, got {purl}",
        )
        self.assertIn("musl", purl)
        self.assertIn("1.2.4-r2", purl)

    # ── Package check ───────────────────────────────

    def test_is_package_installed_true(self):
        """Installed package should return True."""
        self.assertTrue(
            self._resolver.is_package_installed("musl")
        )

    def test_is_package_installed_false(self):
        """Non-existent package should return False."""
        self.assertFalse(
            self._resolver.is_package_installed(
                "nonexistent-pkg-12345"
            )
        )

    def test_install_hint_uses_apk(self):
        """Install hint should use apk add."""
        hint = self._resolver.install_hint(
            ["gcc", "make"]
        )
        self.assertIn("apk", hint)
        self.assertIn("gcc", hint)


def _find_lib(name):
    """Find a shared library on the system."""
    try:
        out = subprocess.check_output(
            ["find", "/usr/lib", "/lib",
             "-name", f"{name}*", "-type", "f"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        if out:
            return out.splitlines()[0]
    except (subprocess.CalledProcessError, OSError):
        pass
    return None


if __name__ == "__main__":
    unittest.main()
