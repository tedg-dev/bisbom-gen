"""RPM package resolver for RHEL/CentOS/Fedora/Rocky/AlmaLinux.

Resolves file paths to OS package metadata using ``rpm -qf``
(file-to-package lookup) and ``rpm -qi`` / ``rpm -q --queryformat``
(package metadata query). This is the concrete ``PackageResolver``
implementation for any distro in the ``rpm`` family.

RPM query format reference:
    https://rpm-software-management.github.io/rpm/manual/queryformat.html
"""

import subprocess
from typing import Optional

from app.spdx.package_resolver import (
    PackageResolver,
    ResolvedPackage,
    detect_distro_id,
    detect_distro_version,
    purl_namespace_for_distro,
)

# rpm query format — pipe-delimited fields
# %{SOURCERPM} gives "openssl-3.0.7-24.el9.src.rpm" from which
# we extract the source package name.
_RPM_QUERYFORMAT = (
    "%{NAME}|%{VERSION}-%{RELEASE}|%{SOURCERPM}|%{ARCH}"
    "|%{PACKAGER}|%{URL}|%{GROUP}"
)

_RPM_FIELD_NAMES = [
    "name", "version", "sourcerpm", "arch",
    "packager", "url", "group",
]


def _source_name_from_srpm(sourcerpm: str) -> str:
    """Extract source package name from SOURCERPM string.

    ``openssl-3.0.7-24.el9.src.rpm`` → ``openssl``
    ``glibc-2.34-60.el9.src.rpm`` → ``glibc``
    ``(none)`` → ``""``

    The SRPM format is ``name-version-release.src.rpm``.
    We strip from the right: ``.src.rpm``, then the
    release (after last ``-``), then the version (after
    last ``-``), leaving the name.
    """
    if not sourcerpm or sourcerpm == "(none)":
        return ""
    s = sourcerpm
    if s.endswith(".src.rpm"):
        s = s[:-8]
    # Strip release: everything after last '-'
    idx = s.rfind("-")
    if idx > 0:
        s = s[:idx]
    # Strip version: everything after last '-'
    idx = s.rfind("-")
    if idx > 0:
        s = s[:idx]
    return s


class RpmResolver(PackageResolver):
    """RHEL/CentOS/Fedora/Rocky/AlmaLinux package resolver.

    Uses two commands:

    1. ``rpm -qf <path>`` — find which package owns a file
    2. ``rpm -q --queryformat <fmt> <pkg>`` — query metadata

    Caches metadata per package name to avoid redundant
    ``rpm -q`` calls.
    """

    def __init__(self):
        self._distro_id = detect_distro_id()
        self._distro_version = detect_distro_version()
        self._namespace = purl_namespace_for_distro(
            self._distro_id
        )
        self._meta_cache = {}

    def purl_scheme(self) -> str:
        """Return ``pkg:rpm/<namespace>`` for this distro."""
        return f"pkg:rpm/{self._namespace}"

    def resolve(
        self, file_path: str,
    ) -> Optional[ResolvedPackage]:
        """Resolve a file path to its RPM package metadata.

        Args:
            file_path: Absolute path to a file on disk.

        Returns:
            A ``ResolvedPackage`` with RPM metadata, or
            ``None`` if the file is not owned by any package.
        """
        pkg_name = self._file_to_package(file_path)
        if not pkg_name:
            return None
        return self._query_metadata(pkg_name)

    def _file_to_package(self, file_path: str) -> Optional[str]:
        """Run ``rpm -qf <path>`` to find the owning package.

        Returns the package name (without version), or None.
        """
        try:
            out = subprocess.check_output(
                ["rpm", "-qf", "--queryformat",
                 "%{NAME}", file_path],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            if out and "not owned" not in out.lower():
                return out
            return None
        except (subprocess.CalledProcessError, OSError):
            return None

    def _query_metadata(
        self, pkg_name: str,
    ) -> Optional[ResolvedPackage]:
        """Query rpm for package metadata, with caching."""
        if pkg_name in self._meta_cache:
            return self._meta_cache[pkg_name]

        try:
            out = subprocess.check_output(
                ["rpm", "-q", "--queryformat",
                 _RPM_QUERYFORMAT, pkg_name],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (subprocess.CalledProcessError, OSError):
            self._meta_cache[pkg_name] = None
            return None

        parts = out.split("|")
        meta = {}
        for i, field in enumerate(_RPM_FIELD_NAMES):
            if i < len(parts) and parts[i]:
                val = parts[i].strip()
                if val and val != "(none)":
                    meta[field] = val

        if not meta.get("name"):
            self._meta_cache[pkg_name] = None
            return None

        source = _source_name_from_srpm(
            meta.get("sourcerpm", "")
        )

        result = ResolvedPackage(
            name=meta.get("name", pkg_name),
            version=meta.get("version", ""),
            source=source,
            architecture=meta.get("arch", ""),
            maintainer=meta.get("packager", ""),
            homepage=meta.get("url", ""),
            section=meta.get("group", ""),
        )
        self._meta_cache[pkg_name] = result
        return result

    def is_package_installed(self, pkg_name: str) -> bool:
        """Check via ``rpm -q`` whether a package is installed."""
        try:
            subprocess.check_output(
                ["rpm", "-q", pkg_name],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            return True
        except (subprocess.CalledProcessError, OSError):
            return False

    def install_hint(self, packages: list) -> str:
        """Return a ``dnf install`` command."""
        pkgs = " ".join(packages)
        return f"dnf install -y {pkgs}"

    @property
    def distro_version_qualifier(self) -> str:
        """Return distro version string for PURL qualifiers.

        Example: ``"rhel-9.3"``, ``"fedora-39"``.
        """
        if self._distro_version:
            return f"{self._distro_id}-{self._distro_version}"
        return self._distro_id
