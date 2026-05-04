"""Tests for PackageResolver ABC and helper functions.

Covers:
- ResolvedPackage dataclass construction
- PackageResolver ABC contract enforcement
- make_purl() helper method
- detect_distro_id() with mocked /etc/os-release
- detect_distro_version() with mocked /etc/os-release
- purl_namespace_for_distro() mapping
- auto_detect_resolver() factory with mocked distro detection
"""

from unittest.mock import mock_open, patch

import pytest

from app.spdx.package_resolver import (
    PackageResolver,
    ResolvedPackage,
    auto_detect_resolver,
    detect_distro_id,
    detect_distro_version,
    purl_namespace_for_distro,
)


# ── ResolvedPackage dataclass ──────────────────────────────


class TestResolvedPackage:
    """Tests for the ResolvedPackage dataclass."""

    def test_minimal_construction(self):
        pkg = ResolvedPackage(name="libssl3", version="3.0.2")
        assert pkg.name == "libssl3"
        assert pkg.version == "3.0.2"
        assert pkg.source == ""
        assert pkg.architecture == ""
        assert pkg.maintainer == ""
        assert pkg.homepage == ""
        assert pkg.section == ""
        assert pkg.extra == {}

    def test_full_construction(self):
        pkg = ResolvedPackage(
            name="libssl3",
            version="3.0.2-0ubuntu1.15",
            source="openssl",
            architecture="amd64",
            maintainer="Ubuntu Developers",
            homepage="https://www.openssl.org/",
            section="libs",
            extra={"Priority": "optional"},
        )
        assert pkg.name == "libssl3"
        assert pkg.source == "openssl"
        assert pkg.architecture == "amd64"
        assert pkg.extra == {"Priority": "optional"}

    def test_extra_defaults_to_empty_dict(self):
        pkg1 = ResolvedPackage(name="a", version="1")
        pkg2 = ResolvedPackage(name="b", version="2")
        # Verify each instance gets its own dict (no shared mutable default)
        pkg1.extra["key"] = "val"
        assert pkg2.extra == {}


# ── PackageResolver ABC contract ───────────────────────────


class TestPackageResolverABC:
    """Tests for the PackageResolver abstract base class."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            PackageResolver()

    def test_subclass_must_implement_resolve(self):
        class Incomplete(PackageResolver):
            def purl_scheme(self):
                return "pkg:test/test"

        with pytest.raises(TypeError):
            Incomplete()

    def test_subclass_must_implement_purl_scheme(self):
        class Incomplete(PackageResolver):
            def resolve(self, file_path):
                return None

        with pytest.raises(TypeError):
            Incomplete()

    def test_complete_subclass_instantiates(self):
        class Complete(PackageResolver):
            def resolve(self, file_path):
                return None

            def purl_scheme(self):
                return "pkg:test/test"

        resolver = Complete()
        assert resolver.resolve("/usr/lib/libfoo.so") is None
        assert resolver.purl_scheme() == "pkg:test/test"


# ── make_purl() ────────────────────────────────────────────


class TestMakePurl:
    """Tests for the make_purl() helper on PackageResolver."""

    def _make_resolver(self, scheme):
        """Create a minimal concrete resolver for testing."""

        class Stub(PackageResolver):
            def resolve(self, file_path):
                return None

            def purl_scheme(self):
                return scheme

        return Stub()

    def test_basic_purl(self):
        r = self._make_resolver("pkg:deb/ubuntu")
        purl = r.make_purl("libssl3", "3.0.2")
        assert purl == "pkg:deb/ubuntu/libssl3@3.0.2"

    def test_purl_with_arch(self):
        r = self._make_resolver("pkg:deb/ubuntu")
        purl = r.make_purl("libssl3", "3.0.2", arch="amd64")
        assert purl == (
            "pkg:deb/ubuntu/libssl3@3.0.2?arch=amd64"
        )

    def test_purl_with_distro_version(self):
        r = self._make_resolver("pkg:rpm/rhel")
        purl = r.make_purl(
            "openssl-libs", "3.0.7-24.el9",
            distro_version="rhel-9.3",
        )
        assert purl == (
            "pkg:rpm/rhel/openssl-libs@3.0.7-24.el9"
            "?distro=rhel-9.3"
        )

    def test_purl_with_all_qualifiers(self):
        r = self._make_resolver("pkg:apk/alpine")
        purl = r.make_purl(
            "libssl3", "3.1.4-r2",
            arch="x86_64", distro_version="alpine-3.18",
        )
        assert purl == (
            "pkg:apk/alpine/libssl3@3.1.4-r2"
            "?arch=x86_64&distro=alpine-3.18"
        )

    def test_purl_no_qualifiers(self):
        r = self._make_resolver("pkg:deb/debian")
        purl = r.make_purl("libc6", "2.36-9")
        assert purl == "pkg:deb/debian/libc6@2.36-9"


# ── detect_distro_id() ─────────────────────────────────────


class TestDetectDistroId:
    """Tests for detect_distro_id() with mocked os-release."""

    def test_ubuntu(self):
        content = (
            'NAME="Ubuntu"\n'
            'VERSION="22.04.3 LTS"\n'
            'ID=ubuntu\n'
        )
        with patch("builtins.open", mock_open(read_data=content)):
            assert detect_distro_id() == "ubuntu"

    def test_rhel(self):
        content = (
            'NAME="Red Hat Enterprise Linux"\n'
            'ID="rhel"\n'
            'VERSION_ID="9.3"\n'
        )
        with patch("builtins.open", mock_open(read_data=content)):
            assert detect_distro_id() == "rhel"

    def test_alpine(self):
        content = 'ID=alpine\nVERSION_ID=3.18.4\n'
        with patch("builtins.open", mock_open(read_data=content)):
            assert detect_distro_id() == "alpine"

    def test_centos(self):
        content = 'ID="centos"\nVERSION_ID="8"\n'
        with patch("builtins.open", mock_open(read_data=content)):
            assert detect_distro_id() == "centos"

    def test_fedora(self):
        content = 'ID=fedora\nVERSION_ID=39\n'
        with patch("builtins.open", mock_open(read_data=content)):
            assert detect_distro_id() == "fedora"

    def test_rocky(self):
        content = 'ID="rocky"\nVERSION_ID="9.3"\n'
        with patch("builtins.open", mock_open(read_data=content)):
            assert detect_distro_id() == "rocky"

    def test_missing_file(self):
        with patch("builtins.open", side_effect=OSError):
            assert detect_distro_id() == "unknown"

    def test_no_id_line(self):
        content = 'NAME="Some Linux"\nVERSION="1.0"\n'
        with patch("builtins.open", mock_open(read_data=content)):
            assert detect_distro_id() == "unknown"

    def test_quoted_id(self):
        content = 'ID="debian"\n'
        with patch("builtins.open", mock_open(read_data=content)):
            assert detect_distro_id() == "debian"


# ── detect_distro_version() ────────────────────────────────


class TestDetectDistroVersion:
    """Tests for detect_distro_version() with mocked os-release."""

    def test_ubuntu(self):
        content = 'ID=ubuntu\nVERSION_ID="22.04"\n'
        with patch("builtins.open", mock_open(read_data=content)):
            assert detect_distro_version() == "22.04"

    def test_rhel(self):
        content = 'ID="rhel"\nVERSION_ID="9.3"\n'
        with patch("builtins.open", mock_open(read_data=content)):
            assert detect_distro_version() == "9.3"

    def test_alpine_unquoted(self):
        content = 'ID=alpine\nVERSION_ID=3.18.4\n'
        with patch("builtins.open", mock_open(read_data=content)):
            assert detect_distro_version() == "3.18.4"

    def test_missing_file(self):
        with patch("builtins.open", side_effect=OSError):
            assert detect_distro_version() == ""

    def test_no_version_line(self):
        content = 'ID=ubuntu\nNAME="Ubuntu"\n'
        with patch("builtins.open", mock_open(read_data=content)):
            assert detect_distro_version() == ""


# ── purl_namespace_for_distro() ────────────────────────────


class TestPurlNamespaceForDistro:
    """Tests for the distro ID to PURL namespace mapping."""

    @pytest.mark.parametrize(
        "distro_id,expected",
        [
            ("ubuntu", "ubuntu"),
            ("debian", "debian"),
            ("rhel", "rhel"),
            ("centos", "centos"),
            ("fedora", "fedora"),
            ("rocky", "rocky"),
            ("almalinux", "almalinux"),
            ("ol", "oracle"),
            ("alpine", "alpine"),
        ],
    )
    def test_known_distros(self, distro_id, expected):
        assert purl_namespace_for_distro(distro_id) == expected

    def test_unknown_distro_returns_id(self):
        assert purl_namespace_for_distro("nixos") == "nixos"

    def test_empty_string(self):
        assert purl_namespace_for_distro("") == ""


# ── auto_detect_resolver() ─────────────────────────────────


class TestAutoDetectResolver:
    """Tests for the auto_detect_resolver() factory."""

    def test_unsupported_distro_raises(self):
        with patch(
            "app.spdx.package_resolver.detect_distro_id",
            return_value="nixos",
        ):
            with pytest.raises(RuntimeError, match="Unsupported"):
                auto_detect_resolver()

    def test_unknown_distro_raises(self):
        with patch(
            "app.spdx.package_resolver.detect_distro_id",
            return_value="unknown",
        ):
            with pytest.raises(RuntimeError, match="Unsupported"):
                auto_detect_resolver()

    def test_deb_family_returns_dpkg_resolver(self):
        with patch(
            "app.spdx.package_resolver.detect_distro_id",
            return_value="ubuntu",
        ):
            from app.spdx.dpkg_resolver import DpkgResolver
            resolver = auto_detect_resolver()
            assert isinstance(resolver, DpkgResolver)

    def test_rpm_family_imports_rpm(self):
        with patch(
            "app.spdx.package_resolver.detect_distro_id",
            return_value="rhel",
        ):
            with pytest.raises(
                (ImportError, ModuleNotFoundError),
            ):
                # RpmResolver module doesn't exist yet (#97)
                auto_detect_resolver()

    def test_apk_family_imports_apk(self):
        with patch(
            "app.spdx.package_resolver.detect_distro_id",
            return_value="alpine",
        ):
            with pytest.raises(
                (ImportError, ModuleNotFoundError),
            ):
                # ApkResolver module doesn't exist yet (#98)
                auto_detect_resolver()
