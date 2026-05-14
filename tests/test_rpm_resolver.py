"""Tests for RpmResolver — RHEL/CentOS/Fedora package resolver.

All subprocess calls are mocked. No actual rpm commands run.

Covers:
- purl_scheme() returns correct rpm namespace
- resolve() for files owned by a package
- resolve() for unowned files
- resolve() when rpm -q fails
- _source_name_from_srpm() extraction
- Metadata caching
- distro_version_qualifier property
- make_purl() integration
"""

import subprocess
from unittest.mock import patch

from app.spdx.rpm_resolver import (
    RpmResolver,
    _source_name_from_srpm,
)


# ── Helpers ────────────────────────────────────────────────


def _make_resolver(
    distro_id="rhel", distro_version="9.3",
):
    """Create an RpmResolver with mocked distro detection."""
    with patch(
        "app.spdx.rpm_resolver.detect_distro_id",
        return_value=distro_id,
    ), patch(
        "app.spdx.rpm_resolver.detect_distro_version",
        return_value=distro_version,
    ):
        return RpmResolver()


def _rpm_query_output(
    name="openssl-libs", version="3.0.7-24.el9",
    sourcerpm="openssl-3.0.7-24.el9.src.rpm",
    arch="x86_64", packager="Red Hat, Inc.",
    url="https://www.openssl.org/",
    group="System Environment/Libraries",
):
    """Simulate ``rpm -q --queryformat`` pipe-delimited output."""
    return "|".join([
        name, version, sourcerpm, arch,
        packager, url, group,
    ])


# ── _source_name_from_srpm() ──────────────────────────────


class TestSourceNameFromSrpm:
    """Tests for SOURCERPM → source name extraction."""

    def test_standard_srpm(self):
        assert _source_name_from_srpm(
            "openssl-3.0.7-24.el9.src.rpm"
        ) == "openssl"

    def test_glibc(self):
        assert _source_name_from_srpm(
            "glibc-2.34-60.el9.src.rpm"
        ) == "glibc"

    def test_hyphenated_name(self):
        assert _source_name_from_srpm(
            "libxml2-devel-2.9.13-1.el9.src.rpm"
        ) == "libxml2-devel"

    def test_none_string(self):
        assert _source_name_from_srpm("(none)") == ""

    def test_empty_string(self):
        assert _source_name_from_srpm("") == ""

    def test_none_value(self):
        assert _source_name_from_srpm(None) == ""


# ── purl_scheme() ─────────────────────────────────────────


class TestRpmResolverPurlScheme:
    """Tests for purl_scheme() across rpm-family distros."""

    def test_rhel(self):
        r = _make_resolver("rhel", "9.3")
        assert r.purl_scheme() == "pkg:rpm/rhel"

    def test_centos(self):
        r = _make_resolver("centos", "8")
        assert r.purl_scheme() == "pkg:rpm/centos"

    def test_fedora(self):
        r = _make_resolver("fedora", "39")
        assert r.purl_scheme() == "pkg:rpm/fedora"

    def test_rocky(self):
        r = _make_resolver("rocky", "9.3")
        assert r.purl_scheme() == "pkg:rpm/rocky"

    def test_almalinux(self):
        r = _make_resolver("almalinux", "9.3")
        assert r.purl_scheme() == "pkg:rpm/almalinux"

    def test_oracle_linux(self):
        r = _make_resolver("ol", "9.3")
        assert r.purl_scheme() == "pkg:rpm/oracle"


# ── resolve() success ──────────────────────────────────────


class TestRpmResolverResolve:
    """Tests for resolve() with successful rpm lookups."""

    @patch("subprocess.check_output")
    def test_resolves_known_file(self, mock_subproc):
        r = _make_resolver()
        path = "/usr/lib64/libssl.so.3"

        def side_effect(cmd, **kwargs):
            if cmd[0] == "rpm" and cmd[1] == "-qf":
                return "openssl-libs"
            if cmd[0] == "rpm" and cmd[1] == "-q":
                return _rpm_query_output()
            raise ValueError(f"Unexpected cmd: {cmd}")

        mock_subproc.side_effect = side_effect
        result = r.resolve(path)

        assert result is not None
        assert result.name == "openssl-libs"
        assert result.version == "3.0.7-24.el9"
        assert result.source == "openssl"
        assert result.architecture == "x86_64"
        assert result.maintainer == "Red Hat, Inc."
        assert result.homepage == "https://www.openssl.org/"

    @patch("subprocess.check_output")
    def test_none_fields_excluded(self, mock_subproc):
        """Fields with value '(none)' are treated as empty."""
        r = _make_resolver()

        def side_effect(cmd, **kwargs):
            if cmd[0] == "rpm" and cmd[1] == "-qf":
                return "somepkg"
            if cmd[0] == "rpm" and cmd[1] == "-q":
                return (
                    "somepkg|1.0-1.el9|(none)|x86_64"
                    "|(none)|(none)|(none)"
                )
            raise ValueError(f"Unexpected cmd: {cmd}")

        mock_subproc.side_effect = side_effect
        result = r.resolve("/some/path")
        assert result is not None
        assert result.name == "somepkg"
        assert result.source == ""
        assert result.maintainer == ""
        assert result.homepage == ""


# ── resolve() failure ──────────────────────────────────────


class TestRpmResolverResolveFailure:
    """Tests for resolve() when files aren't in any package."""

    @patch("subprocess.check_output")
    def test_unowned_file_returns_none(self, mock_subproc):
        r = _make_resolver()
        mock_subproc.side_effect = subprocess.CalledProcessError(
            1, "rpm"
        )
        assert r.resolve("/tmp/random/file") is None

    @patch("subprocess.check_output")
    def test_not_owned_message_returns_none(self, mock_subproc):
        """rpm -qf prints 'not owned by any package'."""
        r = _make_resolver()
        mock_subproc.return_value = (
            "file /tmp/foo is not owned by any package"
        )
        assert r.resolve("/tmp/foo") is None

    @patch("subprocess.check_output")
    def test_rpm_query_failure_returns_none(self, mock_subproc):
        """rpm -qf succeeds but rpm -q fails."""
        r = _make_resolver()

        def side_effect(cmd, **kwargs):
            if cmd[0] == "rpm" and cmd[1] == "-qf":
                return "somepkg"
            raise subprocess.CalledProcessError(1, "rpm")

        mock_subproc.side_effect = side_effect
        assert r.resolve("/some/path") is None

    @patch("subprocess.check_output")
    def test_oserror_returns_none(self, mock_subproc):
        r = _make_resolver()
        mock_subproc.side_effect = OSError("not found")
        assert r.resolve("/usr/lib64/libfoo.so") is None


# ── Caching ────────────────────────────────────────────────


class TestRpmResolverCaching:
    """Tests for metadata caching behavior."""

    @patch("subprocess.check_output")
    def test_second_resolve_uses_cache(self, mock_subproc):
        r = _make_resolver()

        def side_effect(cmd, **kwargs):
            if cmd[0] == "rpm" and cmd[1] == "-qf":
                return "openssl-libs"
            if cmd[0] == "rpm" and cmd[1] == "-q":
                return _rpm_query_output()
            raise ValueError(f"Unexpected cmd: {cmd}")

        mock_subproc.side_effect = side_effect

        r.resolve("/usr/lib64/libssl.so.3")
        r.resolve("/usr/lib64/libcrypto.so.3")

        rpm_q_calls = [
            c for c in mock_subproc.call_args_list
            if c[0][0][0] == "rpm" and c[0][0][1] == "-q"
            and c[0][0][2] == "--queryformat"
        ]
        assert len(rpm_q_calls) == 1

    @patch("subprocess.check_output")
    def test_failed_lookup_cached(self, mock_subproc):
        r = _make_resolver()

        def side_effect(cmd, **kwargs):
            if cmd[0] == "rpm" and cmd[1] == "-qf":
                return "badpkg"
            raise subprocess.CalledProcessError(1, "rpm")

        mock_subproc.side_effect = side_effect

        assert r.resolve("/some/path") is None
        assert r.resolve("/other/path") is None

        rpm_q_calls = [
            c for c in mock_subproc.call_args_list
            if c[0][0][0] == "rpm" and c[0][0][1] == "-q"
            and c[0][0][2] == "--queryformat"
        ]
        assert len(rpm_q_calls) == 1


# ── distro_version_qualifier ───────────────────────────────


class TestRpmDistroVersionQualifier:
    """Tests for the distro_version_qualifier property."""

    def test_with_version(self):
        r = _make_resolver("rhel", "9.3")
        assert r.distro_version_qualifier == "rhel-9.3"

    def test_without_version(self):
        r = _make_resolver("fedora", "")
        assert r.distro_version_qualifier == "fedora"


# ── make_purl() integration ────────────────────────────────


class TestRpmResolverMakePurl:
    """Tests for make_purl() inherited from PackageResolver."""

    def test_full_purl(self):
        r = _make_resolver("rhel", "9.3")
        purl = r.make_purl(
            "openssl-libs", "3.0.7-24.el9",
            arch="x86_64",
            distro_version="rhel-9.3",
        )
        assert purl == (
            "pkg:rpm/rhel/openssl-libs@3.0.7-24.el9"
            "?arch=x86_64&distro=rhel-9.3"
        )

    def test_minimal_purl(self):
        r = _make_resolver("fedora", "39")
        purl = r.make_purl("glibc", "2.38-6.fc39")
        assert purl == "pkg:rpm/fedora/glibc@2.38-6.fc39"


# ── is_package_installed ───────────────────────────────────


class TestRpmIsPackageInstalled:
    """Tests for is_package_installed()."""

    @patch("subprocess.check_output")
    def test_installed_returns_true(self, mock_sub):
        mock_sub.return_value = "openssl-libs-3.0.7"
        r = _make_resolver()
        assert r.is_package_installed("openssl-libs")

    @patch("subprocess.check_output")
    def test_not_installed_returns_false(self, mock_sub):
        mock_sub.side_effect = (
            subprocess.CalledProcessError(1, "rpm")
        )
        r = _make_resolver()
        assert r.is_package_installed("nope") is False

    @patch("subprocess.check_output")
    def test_oserror_returns_false(self, mock_sub):
        mock_sub.side_effect = OSError("no rpm")
        r = _make_resolver()
        assert r.is_package_installed("x") is False


# ── install_hint ───────────────────────────────────────────


class TestRpmInstallHint:

    def test_returns_dnf_command(self):
        r = _make_resolver()
        assert r.install_hint(["a", "b"]) == (
            "dnf install -y a b"
        )


# ── resolve metadata with empty name ──────────────────────


class TestRpmResolveEmptyName:
    """Test resolve_metadata returns None for empty name."""

    @patch("subprocess.check_output")
    def test_empty_name_field(self, mock_sub):
        # rpm returns empty name field
        mock_sub.return_value = (
            "|||x86_64||"
        )
        r = _make_resolver()
        result = r._query_metadata("badpkg")
        assert result is None
