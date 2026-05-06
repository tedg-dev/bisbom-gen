"""Alpine apk package resolver.

Resolves file paths to OS package metadata using
``apk info --who-owns`` (file-to-package lookup) and
``apk info`` / ``apk info --webpage`` / ``apk info --size``
(package metadata query). This is the concrete
``PackageResolver`` implementation for Alpine Linux.

Alpine apk reference:
    https://wiki.alpinelinux.org/wiki/Alpine_Package_Keeper
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


def _parse_apk_info(output: str) -> dict:
    """Parse ``apk info -a <pkg>`` output into a dict.

    apk info outputs key-value lines like::

        <pkg>-<ver> description:
        <description text>

        <pkg>-<ver> webpage:
        https://example.com

        <pkg>-<ver> installed size:
        1234

    We extract: description, webpage, installed size, license.
    """
    meta = {}
    lines = output.strip().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if " description:" in line:
            if i + 1 < len(lines):
                meta["description"] = lines[i + 1].strip()
            i += 2
        elif " webpage:" in line:
            if i + 1 < len(lines):
                meta["webpage"] = lines[i + 1].strip()
            i += 2
        elif " license:" in line:
            if i + 1 < len(lines):
                meta["license"] = lines[i + 1].strip()
            i += 2
        elif " origin:" in line:
            if i + 1 < len(lines):
                meta["origin"] = lines[i + 1].strip()
            i += 2
        elif " maintainer:" in line:
            if i + 1 < len(lines):
                meta["maintainer"] = lines[i + 1].strip()
            i += 2
        else:
            i += 1
    return meta


def _parse_apk_version(pkg_name: str, output: str) -> str:
    """Extract version from ``apk info -v <pkg>`` output.

    Output is ``<pkg>-<version>\\n``. We strip the package name
    prefix to get just the version.

    Example: ``musl-1.2.4-r2`` → ``1.2.4-r2``
    """
    line = output.strip()
    prefix = pkg_name + "-"
    if line.startswith(prefix):
        return line[len(prefix):]
    return line


class ApkResolver(PackageResolver):
    """Alpine Linux package resolver using apk.

    Uses:

    1. ``apk info --who-owns <path>`` — find owning package
    2. ``apk info -v <pkg>`` — get version
    3. ``apk info -a <pkg>`` — get full metadata

    Caches metadata per package name to avoid redundant
    ``apk info`` calls.
    """

    def __init__(self):
        self._distro_id = detect_distro_id()
        self._distro_version = detect_distro_version()
        self._namespace = purl_namespace_for_distro(
            self._distro_id
        )
        self._meta_cache = {}

    def purl_scheme(self) -> str:
        """Return ``pkg:apk/alpine`` for this distro."""
        return f"pkg:apk/{self._namespace}"

    def resolve(
        self, file_path: str,
    ) -> Optional[ResolvedPackage]:
        """Resolve a file path to its apk package metadata.

        Args:
            file_path: Absolute path to a file on disk.

        Returns:
            A ``ResolvedPackage`` with apk metadata, or
            ``None`` if the file is not owned by any package.
        """
        pkg_name = self._file_to_package(file_path)
        if not pkg_name:
            return None
        return self._query_metadata(pkg_name)

    def _file_to_package(self, file_path: str) -> Optional[str]:
        """Run ``apk info --who-owns <path>``.

        Output format: ``<path> is owned by <pkg>-<ver>``
        We extract the package name (without version).

        Returns the package name, or None.
        """
        try:
            out = subprocess.check_output(
                ["apk", "info", "--who-owns", file_path],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            # Format: "/usr/lib/libssl.so.3 is owned by libssl3-3.1.4-r2"
            if "is owned by" in out:
                owned_part = out.split("is owned by")[-1].strip()
                # Strip version: find last hyphen before a digit
                # e.g. "libssl3-3.1.4-r2" → "libssl3"
                return _strip_apk_version(owned_part)
            return None
        except (subprocess.CalledProcessError, OSError):
            return None

    def _query_metadata(
        self, pkg_name: str,
    ) -> Optional[ResolvedPackage]:
        """Query apk for package metadata, with caching."""
        if pkg_name in self._meta_cache:
            return self._meta_cache[pkg_name]

        # Get version
        version = ""
        try:
            out = subprocess.check_output(
                ["apk", "info", "-v", pkg_name],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            version = _parse_apk_version(pkg_name, out)
        except (subprocess.CalledProcessError, OSError):
            pass

        # Get full metadata
        meta = {}
        try:
            out = subprocess.check_output(
                ["apk", "info", "-a", pkg_name],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            meta = _parse_apk_info(out)
        except (subprocess.CalledProcessError, OSError):
            pass

        if not version and not meta:
            self._meta_cache[pkg_name] = None
            return None

        result = ResolvedPackage(
            name=pkg_name,
            version=version,
            source=meta.get("origin", ""),
            architecture="",
            maintainer=meta.get("maintainer", ""),
            homepage=meta.get("webpage", ""),
            section="",
            extra={
                k: v for k, v in meta.items()
                if k not in {
                    "origin", "maintainer", "webpage",
                }
            },
        )
        self._meta_cache[pkg_name] = result
        return result

    def is_package_installed(self, pkg_name: str) -> bool:
        """Check via ``apk info -e`` whether a package is installed."""
        try:
            subprocess.check_output(
                ["apk", "info", "-e", pkg_name],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            return True
        except (subprocess.CalledProcessError, OSError):
            return False

    def install_hint(self, packages: list) -> str:
        """Return an ``apk add`` command."""
        pkgs = " ".join(packages)
        return f"apk add {pkgs}"

    @property
    def distro_version_qualifier(self) -> str:
        """Return distro version string for PURL qualifiers.

        Example: ``"alpine-3.18"``.
        """
        if self._distro_version:
            return f"{self._distro_id}-{self._distro_version}"
        return self._distro_id


def _strip_apk_version(name_version: str) -> str:
    """Strip version suffix from an apk package-version string.

    ``libssl3-3.1.4-r2`` → ``libssl3``
    ``musl-1.2.4-r2`` → ``musl``
    ``busybox-1.36.1-r6`` → ``busybox``

    Alpine versions start with a digit after a hyphen.
    We find the first ``-`` followed by a digit and split there.
    """
    for i, ch in enumerate(name_version):
        if ch == "-" and i + 1 < len(name_version):
            if name_version[i + 1].isdigit():
                return name_version[:i]
    return name_version
