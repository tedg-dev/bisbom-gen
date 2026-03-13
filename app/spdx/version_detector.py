"""
Vendored Version Detector — detects versions of
vendored libraries from source code.

Strategies (ordered most-reliable first):
  1. VERSION / RELEASE text files
  2. configure.ac  AC_INIT([name],[ver])
  3. CMakeLists.txt  project(... VERSION x.y.z)
  4. meson.build  project(... version: 'x.y.z')
  5. .pc.in  Version: field
  6. #define PREFIX_VERSION "x.y.z" (exact prefix)
  7. #define MAJOR/MINOR/PATCH|RELEASE (quoted or
     bare integers, flexible prefix)
  8. #define with any VERSION macro containing a
     semver string (broad fallback)
  9. Header comment version in first 20 lines
 10. Makefile VERSION = x.y.z variables
"""

import re
from pathlib import Path


class VendoredVersionDetector:
    """Detect versions of vendored libraries from
    source directories.

    Given a library name and its file paths, tries
    multiple strategies to find the version string.
    Returns the first match or None.
    """

    # Semver: X.Y or X.Y.Z (no leading zeros
    # on major to avoid matching dates/IPs)
    _VER_RE = re.compile(
        r"(\d+\.\d+(?:\.\d+)?)"
    )

    def detect(self, lib_name, file_paths):
        """Detect version for a vendored library.

        Args:
            lib_name: library name (e.g. "liblua")
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
        prefixes = self._name_prefixes(lib_name)

        # 1. VERSION / RELEASE text files
        for name in (
            "VERSION", "VERSION.txt", "RELEASE",
        ):
            for d in sorted(dirs):
                vf = d / name
                if vf.exists():
                    v = self._parse_version_file(
                        vf
                    )
                    if v:
                        return v

        # 2. configure.ac  AC_INIT
        for d in sorted(dirs):
            ac = d / "configure.ac"
            if ac.exists():
                v = self._parse_configure_ac(ac)
                if v:
                    return v

        # 3. CMakeLists.txt  project(VERSION)
        for d in sorted(dirs):
            cm = d / "CMakeLists.txt"
            if cm.exists():
                v = self._parse_cmakelists(cm)
                if v:
                    return v

        # 4. meson.build  project(version:)
        for d in sorted(dirs):
            mb = d / "meson.build"
            if mb.exists():
                v = self._parse_meson_build(mb)
                if v:
                    return v

        # 5. .pc.in files
        for d in sorted(dirs):
            for pc in sorted(d.glob("*.pc.in")):
                v = self._parse_pc_in(pc)
                if v:
                    return v

        # 6. #define PREFIX_VERSION "x.y.z"
        #    (prefixed single-line string)
        for h in headers:
            v = self._parse_define_version_str(
                h, prefixes
            )
            if v:
                return v

        # 7. #define MAJOR/MINOR/PATCH|RELEASE
        #    (quoted or bare, flexible prefix)
        for h in headers:
            v = self._parse_define_parts(
                h, prefixes
            )
            if v:
                return v

        # 8. Broad fallback: any #define with
        #    VERSION in its name containing semver
        for h in headers:
            v = self._parse_define_any_version(h)
            if v:
                return v

        # 9. Header comment version (first 20
        #    lines)
        for h in headers:
            v = self._parse_header_comment(h)
            if v:
                return v

        # 10. Makefile VERSION = x.y.z
        for d in sorted(dirs):
            for name in ("Makefile", "Makefile.in"):
                mf = d / name
                if mf.exists():
                    v = self._parse_makefile(mf)
                    if v:
                        return v

        return None

    # ----- Helpers -----

    @staticmethod
    def _collect_dirs(file_paths):
        """Collect unique directories from file
        paths, including parent of src/ dirs."""
        dirs = set()
        for fp in file_paths:
            p = Path(fp)
            dirs.add(p.parent)
            # Many vendored libs put code in src/
            if p.parent.name in ("src", "include"):
                dirs.add(p.parent.parent)
        return dirs

    @staticmethod
    def _name_prefixes(lib_name):
        """Generate candidate prefixes from a
        library name for #define matching.

        e.g. "liblua" -> ["LIBLUA", "LUA"]
             "libssh2" -> ["LIBSSH2", "SSH2"]
             "libdnet-stripped" ->
                 ["LIBDNET_STRIPPED", "DNET_STRIPPED",
                  "LIBDNET", "DNET"]
        """
        base = lib_name.upper().replace("-", "_")
        candidates = [base]

        # Strip "lib" prefix
        if base.startswith("LIB"):
            candidates.append(base[3:])

        # Strip trailing qualifiers like _STRIPPED
        for suffix in (
            "_STRIPPED", "_NG", "_LITE",
        ):
            for c in list(candidates):
                if c.endswith(suffix):
                    candidates.append(
                        c[: -len(suffix)]
                    )

        # Deduplicate preserving order
        seen = set()
        result = []
        for c in candidates:
            if c and c not in seen:
                seen.add(c)
                result.append(c)
        return result

    @staticmethod
    def _safe_read(path):
        """Read file text, returning None on error.
        """
        try:
            return Path(path).read_text(
                errors="replace"
            )
        except OSError:
            return None

    def _parse_version_file(self, path):
        """Parse a VERSION / RELEASE text file."""
        text = self._safe_read(path)
        if not text:
            return None
        # Take first line only (some VERSION files
        # have changelogs below)
        first_line = text.strip().splitlines()[0]
        m = self._VER_RE.search(first_line)
        return m.group(1) if m else None

    def _parse_configure_ac(self, path):
        """Parse AC_INIT from configure.ac.

        Patterns:
          AC_INIT([libname],[1.2.3])
          AC_INIT([libname], [1.2.3], [email])
          AC_INIT(name, 1.2.3)
        """
        text = self._safe_read(path)
        if not text:
            return None
        m = re.search(
            r"AC_INIT\s*\("
            r"[^)]*?"
            r"[\[,]\s*"
            rf"({self._VER_RE.pattern})",
            text,
        )
        return m.group(1) if m else None

    def _parse_cmakelists(self, path):
        """Parse project(... VERSION x.y.z) from
        CMakeLists.txt."""
        text = self._safe_read(path)
        if not text:
            return None
        m = re.search(
            r"project\s*\([^)]*?"
            r"VERSION\s+"
            rf"({self._VER_RE.pattern})",
            text,
            re.IGNORECASE,
        )
        return m.group(1) if m else None

    def _parse_meson_build(self, path):
        """Parse project(... version: 'x.y.z')
        from meson.build."""
        text = self._safe_read(path)
        if not text:
            return None
        m = re.search(
            r"project\s*\([^)]*?"
            r"version\s*:\s*['\"]"
            rf"({self._VER_RE.pattern})",
            text,
        )
        return m.group(1) if m else None

    def _parse_pc_in(self, path):
        """Parse Version: from .pc.in file."""
        text = self._safe_read(path)
        if not text:
            return None
        for line in text.splitlines():
            m = re.match(
                r"Version:\s*(.+)", line
            )
            if m:
                val = m.group(1).strip()
                vm = self._VER_RE.search(val)
                if vm:
                    return vm.group(1)
        return None

    def _parse_define_version_str(
        self, path, prefixes
    ):
        """Parse #define PREFIX_VERSION "x.y.z"
        or #define PREFIX_RELEASE "Lib x.y.z".

        Tries each prefix candidate. Matches both
        _VERSION and _RELEASE suffixes.
        """
        text = self._safe_read(path)
        if not text:
            return None

        for pfx in prefixes:
            # RELEASE before VERSION — RELEASE is
            # typically more specific (includes
            # patch level).
            for suffix in (
                "RELEASE", "VERSION",
            ):
                pattern = (
                    rf"#define\s+{pfx}_{suffix}"
                    r"\s+"
                    r'"[^"]*?'
                    rf"({self._VER_RE.pattern})"
                )
                m = re.search(pattern, text)
                if m:
                    return m.group(1)
        return None

    def _parse_define_parts(
        self, path, prefixes
    ):
        """Parse #define MAJOR/MINOR/PATCH|RELEASE.

        Handles both bare integers and quoted
        strings:
          #define LUA_VERSION_MAJOR "5"
          #define LUA_VERSION_MINOR "4"
          #define LUA_VERSION_RELEASE "8"
        or:
          #define PCRE2_MAJOR 10
          #define PCRE2_MINOR 42
        """
        text = self._safe_read(path)
        if not text:
            return None

        # Value: bare int or quoted int
        val_re = r'(?:"(\d+)"|(\d+))'

        # Try each known prefix, then fall back
        # to a prefix-agnostic scan (handles cases
        # like xxhash using XXH_ prefix).
        all_prefixes = list(prefixes) + [r"\w*"]
        for pfx in all_prefixes:
            major = minor = patch = None
            for line in text.splitlines():
                stripped = line.strip()
                # MAJOR
                m = re.match(
                    rf"#define\s+{pfx}"
                    r"(?:_VERSION)?_MAJOR\s+"
                    + val_re,
                    stripped,
                )
                if m:
                    major = m.group(1) or m.group(
                        2
                    )
                # MINOR
                m = re.match(
                    rf"#define\s+{pfx}"
                    r"(?:_VERSION)?_MINOR\s+"
                    + val_re,
                    stripped,
                )
                if m:
                    minor = m.group(1) or m.group(
                        2
                    )
                # PATCH or RELEASE or MICRO
                m = re.match(
                    rf"#define\s+{pfx}"
                    r"(?:_VERSION)?_"
                    r"(?:PATCH|RELEASE|MICRO)"
                    r"\s+" + val_re,
                    stripped,
                )
                if m:
                    patch = m.group(1) or m.group(
                        2
                    )

            if (
                major is not None
                and minor is not None
            ):
                if patch is not None:
                    return (
                        f"{major}.{minor}.{patch}"
                    )
                return f"{major}.{minor}"

        return None

    def _parse_define_any_version(self, path):
        """Broad fallback: any #define with VERSION
        in its name that contains a semver string.

        e.g. #define REDIS_VERSION "7.2.4"
             #define MY_LIB_VER "1.0.3"
        """
        text = self._safe_read(path)
        if not text:
            return None

        m = re.search(
            r'#define\s+\w*(?:VERSION|VER)\w*\s+'
            r'"'
            rf"({self._VER_RE.pattern})"
            r'"',
            text,
        )
        return m.group(1) if m else None

    def _parse_header_comment(self, path):
        """Parse version from header comment block.

        Looks for patterns like:
          /* lib.h -- version 1.0
          * @version 2.3.1
        in the first 20 lines.
        """
        try:
            with open(
                str(path), errors="replace"
            ) as f:
                for i, line in enumerate(f):
                    if i >= 20:
                        break
                    m = re.search(
                        r"(?:@version|VERSION)"
                        r"\s+"
                        rf"({self._VER_RE.pattern})"
                        r"",
                        line,
                        re.IGNORECASE,
                    )
                    if m:
                        return m.group(1)
        except OSError:
            pass
        return None

    def _parse_makefile(self, path):
        """Parse VERSION variable from Makefile.

        Patterns:
          VERSION = 1.2.3
          VERSION=1.2.3
          LIB_VERSION = 1.2.3
        """
        text = self._safe_read(path)
        if not text:
            return None
        m = re.search(
            r"^\w*VERSION\s*[:?]?=\s*"
            rf"({self._VER_RE.pattern})",
            text,
            re.MULTILINE,
        )
        return m.group(1) if m else None
