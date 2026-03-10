"""
Vendored Version Detector — detects versions of vendored libraries.
"""

import re
from pathlib import Path


class VendoredVersionDetector:
    """Detect versions of vendored libraries from source.

    Scans vendored source directories for version info
    using common patterns:
      - VERSION files
      - #define macros (e.g. LIB_VERSION_MAJOR)
      - Header comment version strings
      - .pc.in / CMakeLists.txt / configure.ac
    """

    # Regex for semantic version: X.Y or X.Y.Z
    _VER_RE = re.compile(
        r"(\d+\.\d+(?:\.\d+)?)"
    )

    def detect(self, lib_name, file_paths):
        """Detect version for a vendored library.

        Args:
            lib_name: library name (e.g. "lua")
            file_paths: list of absolute file paths
                belonging to this vendored library

        Returns:
            version string or None
        """
        # Collect unique directories
        dirs = set()
        for fp in file_paths:
            p = Path(fp)
            dirs.add(p.parent)
            if p.parent.name == "src":
                dirs.add(p.parent.parent)

        # Strategy 1: VERSION file
        for d in sorted(dirs):
            vf = d / "VERSION"
            if vf.exists():
                v = self._parse_version_file(vf)
                if v:
                    return v

        # Strategy 2: header #define macros
        headers = [
            fp for fp in file_paths
            if fp.endswith(".h")
        ]
        for h in sorted(headers):
            v = self._parse_header_defines(
                h, lib_name
            )
            if v:
                return v

        # Strategy 3: header comment version
        for h in sorted(headers):
            v = self._parse_header_comment(h)
            if v:
                return v

        # Strategy 4: .pc.in files
        for d in sorted(dirs):
            for pc in sorted(d.glob("*.pc.in")):
                v = self._parse_pc_in(pc)
                if v:
                    return v

        return None

    def _parse_version_file(self, path):
        """Parse a VERSION file for semver."""
        try:
            text = path.read_text().strip()
            m = self._VER_RE.search(text)
            return m.group(1) if m else None
        except OSError:
            return None

    def _parse_header_defines(self, path, lib_name):
        """Parse #define VERSION macros.

        Looks for patterns like:
          #define LIB_MAJOR 1
          #define LIB_MINOR 2
          #define LIB_PATCH 0
        or:
          #define LIB_VERSION "1.2.0"
          #define LIB_RELEASE "Lib 1.2.0"
        """
        try:
            text = Path(path).read_text(
                errors="replace"
            )
        except OSError:
            return None

        # Normalize lib name for matching
        prefix = lib_name.upper().replace("-", "_")

        # Try single-line version string
        for pattern in [
            rf"#define\s+{prefix}_RELEASE\s+"
            rf'"[^"]*?({self._VER_RE.pattern})',
            rf"#define\s+{prefix}_VERSION\s+"
            rf'"({self._VER_RE.pattern})',
            rf"#define\s+\w*VERSION\w*\s+"
            rf'"[^"]*?({self._VER_RE.pattern})',
        ]:
            m = re.search(pattern, text)
            if m:
                return m.group(1)

        # Try MAJOR/MINOR/PATCH defines
        major = minor = patch = None
        for line in text.splitlines():
            line = line.strip()
            m = re.match(
                r"#define\s+\w*"
                r"(?:VERSION_)?MAJOR\s+(\d+)",
                line,
            )
            if m:
                major = m.group(1)
            m = re.match(
                r"#define\s+\w*"
                r"(?:VERSION_)?MINOR\s+(\d+)",
                line,
            )
            if m:
                minor = m.group(1)
            m = re.match(
                r"#define\s+\w*"
                r"(?:VERSION_)?PATCH\s+(\d+)",
                line,
            )
            if m:
                patch = m.group(1)

        if major is not None and minor is not None:
            if patch is not None:
                return f"{major}.{minor}.{patch}"
            return f"{major}.{minor}"

        return None

    def _parse_header_comment(self, path):
        """Parse version from header comment block.

        Looks for patterns like:
          /* lib.h -- VERSION 1.0
        in the first 10 lines.
        """
        try:
            with open(
                str(path), errors="replace"
            ) as f:
                for i, line in enumerate(f):
                    if i >= 10:
                        break
                    m = re.search(
                        r"VERSION\s+"
                        rf"({self._VER_RE.pattern})",
                        line,
                        re.IGNORECASE,
                    )
                    if m:
                        return m.group(1)
        except OSError:
            pass
        return None

    def _parse_pc_in(self, path):
        """Parse Version: from .pc.in file."""
        try:
            for line in path.read_text(
                errors="replace"
            ).splitlines():
                m = re.match(
                    r"Version:\s*(.+)", line
                )
                if m:
                    val = m.group(1).strip()
                    vm = self._VER_RE.search(val)
                    if vm:
                        return vm.group(1)
        except OSError:
            pass
        return None
