"""
Vendored Version Detector — orchestrates version
detection strategies for vendored libraries.

Strategies (ordered most-reliable first):
  1. VERSION / RELEASE text files
  2. Key-value version files (VERSION.dat, etc.)
  3. Structured data files (package.json,
     Cargo.toml, pom.xml, etc.)
  4. configure.ac  AC_INIT([name],[ver])
  5. CMakeLists.txt  project(... VERSION x.y.z)
  6. meson.build  project(... version: 'x.y.z')
  7. .pc.in  Version: field
  8. #define PREFIX_VERSION "x.y.z" (exact prefix)
  9. #define MAJOR/MINOR/PATCH split macros
     (broad suffix aliases, up to 4-part)
 10. Broad fallback: any #define VERSION semver
 11. Header comment @version in first 20 lines
 12. Makefile VERSION = x.y.z variables
"""

from pathlib import Path

from app.version_detection.patterns import (
    VERSION_FILE_NAMES,
    KV_VERSION_FILE_NAMES,
    STRUCTURED_VERSION_FILES,
    name_prefixes,
)
from app.version_detection.strategies import (
    parse_version_file,
    parse_kv_version_file,
    parse_package_json,
    parse_version_json,
    parse_pyproject_toml,
    parse_cargo_toml,
    parse_pom_xml,
    parse_configure_ac,
    parse_cmakelists,
    parse_meson_build,
    parse_pc_in,
    parse_define_version_str,
    parse_define_parts,
    parse_define_any_version,
    parse_header_comment,
    parse_makefile,
)

# Dispatch table for structured data files
_STRUCTURED_PARSERS = {
    "package.json": parse_package_json,
    "version.json": parse_version_json,
    "pyproject.toml": parse_pyproject_toml,
    "Cargo.toml": parse_cargo_toml,
    "pom.xml": parse_pom_xml,
}


class VendoredVersionDetector:
    """Detect versions of vendored libraries from
    source directories.

    Given a library name and its file paths, tries
    multiple strategies to find the version string.
    Returns the first match or None.

    Handles version numbering conventions across:
    - C/C++ (autotools, CMake, meson, #define macros)
    - JavaScript/Node.js (package.json)
    - Python (pyproject.toml)
    - Key-value files (OpenSSL VERSION.dat)
    - Split #define macros with broad suffix aliases
      covering V8, Node.js, OpenSSL, libuv, Lua,
      GLib, FreeType, Ruby, and more
    """

    def detect(self, lib_name, file_paths):
        """Detect version for a vendored library.

        Args:
            lib_name: library name (e.g. "openssl")
            file_paths: list of absolute file paths
                belonging to this vendored library

        Returns:
            version string or None
        """
        dirs = self._collect_dirs(file_paths)
        headers = sorted(
            fp for fp in file_paths
            if fp.endswith(".h")
        )
        prefixes = name_prefixes(lib_name)

        # 1. VERSION / RELEASE text files
        for name in VERSION_FILE_NAMES:
            for d in sorted(dirs):
                vf = d / name
                if vf.exists():
                    v = parse_version_file(vf)
                    if v:
                        return v

        # 2. Key-value version files
        for name in KV_VERSION_FILE_NAMES:
            for d in sorted(dirs):
                vf = d / name
                if vf.exists():
                    v = parse_kv_version_file(vf)
                    if v:
                        return v

        # 3. Structured data files
        for name in STRUCTURED_VERSION_FILES:
            parser = _STRUCTURED_PARSERS.get(name)
            if not parser:
                continue
            for d in sorted(dirs):
                sf = d / name
                if sf.exists():
                    v = parser(sf)
                    if v:
                        return v

        # 4. configure.ac  AC_INIT
        for d in sorted(dirs):
            ac = d / "configure.ac"
            if ac.exists():
                v = parse_configure_ac(ac)
                if v:
                    return v

        # 5. CMakeLists.txt  project(VERSION)
        for d in sorted(dirs):
            cm = d / "CMakeLists.txt"
            if cm.exists():
                v = parse_cmakelists(cm)
                if v:
                    return v

        # 6. meson.build  project(version:)
        for d in sorted(dirs):
            mb = d / "meson.build"
            if mb.exists():
                v = parse_meson_build(mb)
                if v:
                    return v

        # 7. .pc.in files
        for d in sorted(dirs):
            for pc in sorted(d.glob("*.pc.in")):
                v = parse_pc_in(pc)
                if v:
                    return v

        # 8. #define PREFIX_VERSION "x.y.z"
        for h in headers:
            v = parse_define_version_str(
                h, prefixes
            )
            if v:
                return v

        # 9. #define MAJOR/MINOR/PATCH split macros
        for h in headers:
            v = parse_define_parts(h, prefixes)
            if v:
                return v

        # 10. Broad fallback: any #define VERSION
        for h in headers:
            v = parse_define_any_version(h)
            if v:
                return v

        # 11. Header comment @version
        for h in headers:
            v = parse_header_comment(h)
            if v:
                return v

        # 12. Makefile VERSION = x.y.z
        for d in sorted(dirs):
            for name in (
                "Makefile", "Makefile.in",
            ):
                mf = d / name
                if mf.exists():
                    v = parse_makefile(mf)
                    if v:
                        return v

        return None

    # ----- Helpers -----

    @staticmethod
    def _collect_dirs(file_paths):
        """Collect unique directories from file paths.

        Includes:
        - Direct parent of each file
        - Parent of common subdirs (src/, include/, lib/)
        - Common ancestor of all files (the vendored
          library root — e.g. deps/openssl/openssl/)
        - One level above the common ancestor (catches
          version files placed at the vendored entry)
        """
        dirs = set()
        parents = []
        for fp in file_paths:
            p = Path(fp)
            dirs.add(p.parent)
            parents.append(p.parent)
            # Many vendored libs put code in src/
            if p.parent.name in (
                "src", "include", "lib",
            ):
                dirs.add(p.parent.parent)

        # Common ancestor of all input files
        if parents:
            common = parents[0]
            for other in parents[1:]:
                # Walk up until common is a parent
                # of both
                while (
                    common != other
                    and common
                    not in other.parents
                ):
                    common = common.parent
            dirs.add(common)
            # One level up from common (vendored
            # entry directory)
            if common.parent != common:
                dirs.add(common.parent)

        return dirs
