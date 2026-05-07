"""
Docker integration tests for RpmResolver (#104 A10).

Runs inside the RHEL (Rocky Linux 9) container to validate
that RpmResolver correctly resolves file paths to RPM
package metadata and produces valid PURLs.

Requirements:
  - Docker daemon running
  - omnibor-env:rhel9 image built

Run::

    docker compose -f docker/docker-compose.yml run --rm \\
        omnibor-rhel python3 -m pytest \\
        tests/test_resolver_rpm_integration.py -v

Skip in normal test runs::

    pytest tests/ -m "not docker_integration"
"""

import shutil
import subprocess
import unittest

import pytest

# ── Skip conditions ──────────────────────────────────

_has_rpm = shutil.which("rpm") is not None

skip_no_rpm = pytest.mark.skipif(
    not _has_rpm,
    reason="rpm not available (not on RPM-based distro)",
)


def _on_rhel_family():
    """True if running on RHEL/Rocky/CentOS/AlmaLinux."""
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("ID="):
                    distro = (
                        line.split("=", 1)[1]
                        .strip().strip('"').lower()
                    )
                    return distro in {
                        "rhel", "rocky", "centos",
                        "almalinux", "fedora",
                    }
    except OSError:
        pass
    return False


skip_not_rhel = pytest.mark.skipif(
    not _on_rhel_family(),
    reason="Not running on RHEL-family distro",
)


@pytest.mark.docker_integration
@skip_no_rpm
@skip_not_rhel
class TestRpmResolver(unittest.TestCase):
    """Integration test: RpmResolver on Rocky Linux 9.

    Validates:
    - auto_detect_resolver() returns RpmResolver
    - File → package resolution works
    - PURL scheme is pkg:rpm/rocky
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

    def test_auto_detect_returns_rpm_resolver(self):
        """auto_detect_resolver() should return RpmResolver."""
        from app.spdx.rpm_resolver import RpmResolver
        self.assertIsInstance(
            self._resolver, RpmResolver,
        )

    def test_purl_scheme_is_rpm(self):
        """PURL scheme should be pkg:rpm/<namespace>."""
        scheme = self._resolver.purl_scheme()
        self.assertTrue(
            scheme.startswith("pkg:rpm/"),
            f"Expected pkg:rpm/*, got {scheme}",
        )

    # ── File resolution ─────────────────────────────

    def test_resolve_libssl(self):
        """Resolve libssl.so to openssl-libs package."""
        # Find libssl on the system
        libssl = _find_lib("libssl.so")
        if not libssl:
            self.skipTest("libssl.so not found")

        result = self._resolver.resolve(libssl)
        self.assertIsNotNone(
            result,
            f"Failed to resolve {libssl}",
        )
        self.assertIn(
            "openssl", result.name.lower(),
            f"Expected openssl-related package, "
            f"got {result.name}",
        )

    def test_resolve_libc(self):
        """Resolve libc.so to glibc package."""
        libc = _find_lib("libc.so")
        if not libc:
            self.skipTest("libc.so not found")

        result = self._resolver.resolve(libc)
        self.assertIsNotNone(
            result,
            f"Failed to resolve {libc}",
        )
        self.assertIn(
            "glibc", result.name.lower(),
            f"Expected glibc, got {result.name}",
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

    def test_resolved_package_has_source(self):
        """Resolved package should have source name."""
        gcc = shutil.which("gcc")
        if not gcc:
            self.skipTest("gcc not installed")

        result = self._resolver.resolve(gcc)
        self.assertIsNotNone(result)
        # RPM source is extracted from SOURCERPM field
        self.assertTrue(
            len(result.source) > 0,
            "Expected non-empty source package name",
        )

    # ── PURL generation ─────────────────────────────

    def test_make_purl_format(self):
        """PURL should follow pkg:rpm/<ns>/<name>@<ver>."""
        purl = self._resolver.make_purl(
            "openssl-libs", "3.0.7-24.el9",
            arch="x86_64",
            distro_version=(
                self._resolver.distro_version_qualifier
            ),
        )
        self.assertTrue(
            purl.startswith("pkg:rpm/"),
            f"Expected pkg:rpm prefix, got {purl}",
        )
        self.assertIn("openssl-libs", purl)
        self.assertIn("3.0.7-24.el9", purl)
        self.assertIn("arch=x86_64", purl)

    # ── Package check ───────────────────────────────

    def test_is_package_installed_true(self):
        """Installed package should return True."""
        self.assertTrue(
            self._resolver.is_package_installed("glibc")
        )

    def test_is_package_installed_false(self):
        """Non-existent package should return False."""
        self.assertFalse(
            self._resolver.is_package_installed(
                "nonexistent-pkg-12345"
            )
        )

    def test_install_hint_uses_dnf(self):
        """Install hint should use dnf."""
        hint = self._resolver.install_hint(
            ["gcc", "make"]
        )
        self.assertIn("dnf", hint)
        self.assertIn("gcc", hint)


def _find_lib(name):
    """Find a shared library on the system."""
    try:
        out = subprocess.check_output(
            ["find", "/usr/lib64", "/usr/lib",
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
