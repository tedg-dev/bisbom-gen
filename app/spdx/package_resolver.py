"""Package resolver abstraction for multi-distro support.

Provides a common interface for resolving file paths to OS package
metadata across different Linux distributions. Each concrete
resolver implements the distro-specific query mechanism:

- ``DpkgResolver`` — Debian/Ubuntu (``dpkg-query -S``)
- ``RpmResolver``  — RHEL/CentOS/Fedora (``rpm -qf``)
- ``ApkResolver``  — Alpine (``apk info --who-owns``)

The ``auto_detect_resolver()`` factory reads ``/etc/os-release``
to select the correct implementation at runtime.

Design reference: sidecar-implementation-design.md Section 4.3
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ResolvedPackage:
    """Metadata for a resolved OS package.

    Attributes:
        name: Binary package name (e.g. ``libssl3``).
        version: Full package version string.
        source: Source package name (e.g. ``openssl``).
        architecture: Package architecture (e.g. ``amd64``).
        maintainer: Package maintainer string.
        homepage: Upstream homepage URL.
        section: Package section/group (e.g. ``libs``).
        extra: Additional distro-specific metadata fields.
    """

    name: str
    version: str
    source: str = ""
    architecture: str = ""
    maintainer: str = ""
    homepage: str = ""
    section: str = ""
    extra: dict = field(default_factory=dict)


class PackageResolver(ABC):
    """Resolves file paths to OS package metadata.

    Implementations must provide distro-specific mechanisms
    for two operations:

    1. ``resolve(file_path)`` — given an absolute file path,
       return the owning package's metadata or ``None``.
    2. ``purl_scheme()`` — return the PURL type and namespace
       prefix for this distro (e.g. ``pkg:deb/ubuntu``).

    The interface is deliberately minimal (P4: Interface
    Segregation) so that adding a new distro requires only
    two method implementations.
    """

    @abstractmethod
    def resolve(self, file_path: str) -> Optional[ResolvedPackage]:
        """Return package metadata for a file, or None.

        Args:
            file_path: Absolute path to a file on disk.

        Returns:
            A ``ResolvedPackage`` with the owning package's
            metadata, or ``None`` if the file does not belong
            to any installed package.
        """

    @abstractmethod
    def purl_scheme(self) -> str:
        """Return the PURL type+namespace prefix for this distro.

        Examples:
            - ``"pkg:deb/ubuntu"`` for Debian/Ubuntu
            - ``"pkg:rpm/rhel"`` for RHEL/CentOS
            - ``"pkg:apk/alpine"`` for Alpine

        The caller appends ``/{name}@{version}?qualifiers``
        to build the full PURL string.
        """

    def make_purl(
        self, pkg_name: str, version: str,
        arch: str = "", distro_version: str = "",
    ) -> str:
        """Build a complete PURL from package metadata.

        Args:
            pkg_name: Binary package name.
            version: Package version string.
            arch: Package architecture (optional qualifier).
            distro_version: Distro version (optional qualifier).

        Returns:
            A valid Package URL string.
        """
        purl = f"{self.purl_scheme()}/{pkg_name}@{version}"
        qualifiers = []
        if arch:
            qualifiers.append(f"arch={arch}")
        if distro_version:
            qualifiers.append(f"distro={distro_version}")
        if qualifiers:
            purl += "?" + "&".join(qualifiers)
        return purl


def detect_distro_id() -> str:
    """Read distro ID from ``/etc/os-release``.

    Returns:
        Lowercase distro identifier (e.g. ``"ubuntu"``,
        ``"rhel"``, ``"alpine"``). Returns ``"unknown"``
        if detection fails.
    """
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("ID="):
                    return (
                        line.split("=", 1)[1]
                        .strip()
                        .strip('"')
                        .lower()
                    )
    except OSError:
        pass
    return "unknown"


def detect_distro_version() -> str:
    """Read distro version from ``/etc/os-release``.

    Returns:
        Version string (e.g. ``"22.04"``, ``"9.3"``,
        ``"3.18"``). Returns ``""`` if detection fails.
    """
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VERSION_ID="):
                    return (
                        line.split("=", 1)[1]
                        .strip()
                        .strip('"')
                    )
    except OSError:
        pass
    return ""


# Distro ID → PURL family mapping
_DISTRO_FAMILIES = {
    "ubuntu": "deb",
    "debian": "deb",
    "rhel": "rpm",
    "centos": "rpm",
    "fedora": "rpm",
    "rocky": "rpm",
    "almalinux": "rpm",
    "ol": "rpm",
    "alpine": "apk",
}

# PURL family → distro namespace mapping
_PURL_NAMESPACES = {
    "deb": {
        "ubuntu": "ubuntu",
        "debian": "debian",
    },
    "rpm": {
        "rhel": "rhel",
        "centos": "centos",
        "fedora": "fedora",
        "rocky": "rocky",
        "almalinux": "almalinux",
        "ol": "oracle",
    },
    "apk": {
        "alpine": "alpine",
    },
}


def purl_namespace_for_distro(distro_id: str) -> str:
    """Return the PURL namespace for a distro ID.

    Args:
        distro_id: Lowercase distro identifier from
            ``/etc/os-release`` ``ID=`` field.

    Returns:
        PURL namespace string (e.g. ``"ubuntu"``, ``"rhel"``).
        Falls back to the distro ID itself if unknown.
    """
    family = _DISTRO_FAMILIES.get(distro_id)
    if family:
        ns_map = _PURL_NAMESPACES.get(family, {})
        return ns_map.get(distro_id, distro_id)
    return distro_id


def auto_detect_resolver() -> PackageResolver:
    """Detect the host distro and return the appropriate resolver.

    Reads ``/etc/os-release`` to determine the package manager,
    then instantiates the matching ``PackageResolver`` subclass.

    Returns:
        A concrete ``PackageResolver`` for the detected distro.

    Raises:
        RuntimeError: If the distro is unrecognized or the
            corresponding resolver is not yet implemented.
    """
    distro_id = detect_distro_id()
    distro_ver = detect_distro_version()
    family = _DISTRO_FAMILIES.get(distro_id)

    if family == "deb":
        from app.spdx.dpkg_resolver import DpkgResolver
        resolver = DpkgResolver()
        logger.info(
            "Detected distro: %s %s → DpkgResolver",
            distro_id, distro_ver,
        )
        return resolver

    if family == "rpm":
        from app.spdx.rpm_resolver import RpmResolver
        resolver = RpmResolver()
        logger.info(
            "Detected distro: %s %s → RpmResolver",
            distro_id, distro_ver,
        )
        return resolver

    if family == "apk":
        from app.spdx.apk_resolver import ApkResolver
        resolver = ApkResolver()
        logger.info(
            "Detected distro: %s %s → ApkResolver",
            distro_id, distro_ver,
        )
        return resolver

    raise RuntimeError(
        f"Unsupported distro '{distro_id}'. "
        f"No PackageResolver available. "
        f"Supported families: deb, rpm, apk."
    )
