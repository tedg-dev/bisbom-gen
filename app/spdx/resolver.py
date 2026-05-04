"""
Component Resolver — maps artifacts to named software components.
"""

import json
import re
from pathlib import Path


class ComponentResolver:
    """Resolve artifacts to named software components.

    Uses component_metadata.json (from collect_metadata.py)
    and dynamic_libs.json (from collect_dynamic_libs.py)
    to identify runtime dependencies with full metadata.
    """

    def __init__(self, metadata_path, resolver=None):
        self.metadata = json.loads(
            Path(metadata_path).read_text()
        )
        self._dynamic_libs = None
        if resolver is None:
            from app.spdx.package_resolver import (
                auto_detect_resolver,
            )
            resolver = auto_detect_resolver()
        self._resolver = resolver

    @property
    def distro(self):
        return self.metadata.get("distro", "unknown")

    @property
    def distro_codename(self):
        """Extract distro version for PURL qualifier.

        Delegates to the resolver's ``distro_version_qualifier``
        when available, falls back to parsing the distro string.
        """
        qualifier = getattr(
            self._resolver, "distro_version_qualifier", None
        )
        if qualifier:
            return qualifier
        d = self.distro.lower()
        m = re.search(r"ubuntu\s+([\d.]+)", d)
        if m:
            parts = m.group(1).split(".")
            ver = ".".join(parts[:2])
            return f"ubuntu-{ver}"
        return "linux"

    @property
    def gcc_version(self):
        return self.metadata.get(
            "gcc_version", "unknown"
        )

    @property
    def repo_version(self):
        """Return repo's own version, or None."""
        return self.metadata.get("repo_version")

    def load_dynamic_libs(self, path):
        """Load dynamic_libs.json."""
        self._dynamic_libs = json.loads(
            Path(path).read_text()
        )

    def resolve_dynamic_components(self):
        """Resolve dynamic libraries to components.

        Groups libraries by upstream source package.
        Each component has:
          name, version, supplier, homepage,
          dpkg_packages, architecture, purl, cpe23,
          sonames, direct (bool).
        """
        if not self._dynamic_libs:
            return []

        libs = self._dynamic_libs.get(
            "dynamic_libs", {}
        )

        # Group by upstream source
        source_groups = {}
        for soname, info in libs.items():
            meta = info.get("metadata", {})
            source = info.get("source", soname)
            if not meta.get("Version"):
                continue
            if source not in source_groups:
                source_groups[source] = {
                    "meta": meta,
                    "sonames": [],
                    "direct": False,
                    "dpkg_packages": set(),
                }
            source_groups[source][
                "sonames"
            ].append(soname)
            if info.get("direct"):
                source_groups[source][
                    "direct"
                ] = True
            dpkg = info.get("dpkg_package")
            if dpkg:
                source_groups[source][
                    "dpkg_packages"
                ].add(dpkg)

        components = []
        for source, group in sorted(
            source_groups.items()
        ):
            meta = group["meta"]
            version = meta.get("Version", "unknown")
            arch = meta.get(
                "Architecture", "amd64"
            )
            dpkg_pkgs = sorted(
                group["dpkg_packages"]
            )
            dpkg_pkg = (
                dpkg_pkgs[0] if dpkg_pkgs
                else source
            )
            cpe_ver = self._clean_version(version)

            comp = {
                "name": dpkg_pkg,
                "source": source,
                "version": version,
                "supplier": meta.get(
                    "Maintainer", "NOASSERTION"
                ),
                "homepage": meta.get(
                    "Homepage", "NOASSERTION"
                ),
                "dpkg_packages": dpkg_pkgs,
                "architecture": arch,
                "purl": self._make_purl(
                    dpkg_pkg, version, arch
                ),
                "cpe23": self._make_cpe(
                    source, cpe_ver
                ),
                "sonames": sorted(
                    group["sonames"]
                ),
                "direct": group["direct"],
            }
            components.append(comp)

        # Project-built shared libraries
        # (e.g. libavcodec.so built by FFmpeg)
        proj_libs = self._dynamic_libs.get(
            "project_built_libs", {}
        )
        for soname, info in sorted(
            proj_libs.items()
        ):
            name = info.get("name", soname)
            comp = {
                "name": name,
                "source": name,
                "sonames": [soname],
                "direct": info.get("direct", True),
                "project_built": True,
            }
            components.append(comp)

        return components

    def _clean_version(self, version):
        """Strip distro-specific suffixes for CPE.

        Handles:
        - Epoch prefix (``1:1.2.11`` → ``1.2.11``)
        - Debian/Ubuntu: dfsg, ubuntu, build suffixes
        - RPM: release suffix (``3.0.7-24.el9`` → ``3.0.7``)
        - Alpine: ``-rN`` suffix (``3.1.4-r2`` → ``3.1.4``)
        """
        v = version
        # Remove epoch (e.g. "1:1.2.11...")
        if ":" in v:
            v = v.split(":", 1)[1]
        # Remove dfsg suffix (Debian)
        v = re.sub(r"[.+]dfsg.*", "", v)
        # Remove ubuntu/build suffix (Ubuntu)
        v = re.sub(r"-\d+ubuntu.*", "", v)
        v = re.sub(r"-\d+build.*", "", v)
        # Remove RPM release (e.g. -24.el9, -1.fc39)
        v = re.sub(r"-\d+\.el\d+.*", "", v)
        v = re.sub(r"-\d+\.fc\d+.*", "", v)
        v = re.sub(r"-\d+\.amzn\d+.*", "", v)
        # Remove Alpine -rN suffix
        v = re.sub(r"-r\d+$", "", v)
        # Generic trailing release number
        v = re.sub(r"-\d+$", "", v)
        return v

    def _make_purl(self, pkg_name, version, arch):
        """Generate Package URL using the resolver's scheme."""
        distro = self.distro_codename
        return self._resolver.make_purl(
            pkg_name, version,
            arch=arch,
            distro_version=distro,
        )

    def _make_cpe(self, source, version):
        """Generate CPE 2.3 identifier."""
        # Normalize vendor: use source name as vendor
        vendor = source.replace("-", "_")
        product = source.replace("-", "_")
        return (
            f"cpe:2.3:a:{vendor}:{product}"
            f":{version}:*:*:*:*:*:*:*"
        )
