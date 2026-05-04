"""Dpkg package resolver for Debian/Ubuntu systems.

Resolves file paths to OS package metadata using ``dpkg -S``
(file-to-package lookup) and ``dpkg-query -W`` (package metadata
query). This is the concrete ``PackageResolver`` implementation
for any distro in the ``deb`` family (Debian, Ubuntu, etc.).

The two subprocess calls mirror the existing patterns in
``collect_metadata.py`` and ``collect_dynamic_libs.py``, which
will be refactored to use this resolver in issue #100/#101.
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

# Fields queried from dpkg-query, pipe-delimited
_DPKG_FIELDS = [
    "Package", "Version", "Source", "Architecture",
    "Maintainer", "Homepage", "Section", "Priority",
]
_DPKG_FORMAT = "|".join(
    ["${" + f + "}" for f in _DPKG_FIELDS]
)


class DpkgResolver(PackageResolver):
    """Debian/Ubuntu package resolver using dpkg.

    Uses two commands:

    1. ``dpkg -S <path>`` — find which package owns a file
    2. ``dpkg-query -W -f <fmt> <pkg>`` — query package metadata

    The resolver caches metadata per package name to avoid
    redundant ``dpkg-query`` calls when multiple files belong
    to the same package.
    """

    def __init__(self):
        self._distro_id = detect_distro_id()
        self._distro_version = detect_distro_version()
        self._namespace = purl_namespace_for_distro(
            self._distro_id
        )
        self._meta_cache = {}

    def purl_scheme(self) -> str:
        """Return ``pkg:deb/<namespace>`` for this distro."""
        return f"pkg:deb/{self._namespace}"

    def resolve(
        self, file_path: str,
    ) -> Optional[ResolvedPackage]:
        """Resolve a file path to its dpkg package metadata.

        Args:
            file_path: Absolute path to a file on disk.

        Returns:
            A ``ResolvedPackage`` with dpkg metadata, or
            ``None`` if the file is not owned by any package.
        """
        pkg_name = self._file_to_package(file_path)
        if not pkg_name:
            return None
        return self._query_metadata(pkg_name)

    def _file_to_package(self, file_path: str) -> Optional[str]:
        """Run ``dpkg -S <path>`` to find the owning package.

        Returns the first package name, or None.
        """
        try:
            out = subprocess.check_output(
                ["dpkg", "-S", file_path],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            # Format: "pkg1, pkg2: /path/to/file"
            pkg_part = out.split(":")[0]
            return pkg_part.split(",")[0].strip()
        except (subprocess.CalledProcessError, OSError):
            return None

    def _query_metadata(
        self, pkg_name: str,
    ) -> Optional[ResolvedPackage]:
        """Query dpkg-query for package metadata, with caching.

        Returns a ``ResolvedPackage`` or None if the query fails.
        """
        if pkg_name in self._meta_cache:
            return self._meta_cache[pkg_name]

        try:
            out = subprocess.check_output(
                [
                    "dpkg-query", "-W", "-f",
                    _DPKG_FORMAT, pkg_name,
                ],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            parts = out.split("|")
            meta = {}
            for i, field in enumerate(_DPKG_FIELDS):
                if i < len(parts) and parts[i]:
                    meta[field] = parts[i]
        except (subprocess.CalledProcessError, OSError):
            self._meta_cache[pkg_name] = None
            return None

        if not meta.get("Package"):
            self._meta_cache[pkg_name] = None
            return None

        result = ResolvedPackage(
            name=meta.get("Package", pkg_name),
            version=meta.get("Version", ""),
            source=meta.get("Source", ""),
            architecture=meta.get("Architecture", ""),
            maintainer=meta.get("Maintainer", ""),
            homepage=meta.get("Homepage", ""),
            section=meta.get("Section", ""),
            extra={
                k: v for k, v in meta.items()
                if k not in {
                    "Package", "Version", "Source",
                    "Architecture", "Maintainer",
                    "Homepage", "Section",
                }
            },
        )
        self._meta_cache[pkg_name] = result
        return result

    @property
    def distro_version_qualifier(self) -> str:
        """Return distro version string for PURL qualifiers.

        Example: ``"ubuntu-22.04"``, ``"debian-12"``.
        """
        if self._distro_version:
            return f"{self._distro_id}-{self._distro_version}"
        return self._distro_id
