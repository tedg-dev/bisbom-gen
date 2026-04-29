"""
Version detection strategies — ordered from
most-reliable to broadest-fallback.

Each strategy is a standalone function that takes
specific inputs and returns a version string or None.
This makes strategies independently testable.

Strategy ordering:
  1. VERSION / RELEASE text files
  2. Key-value version files (VERSION.dat)
  3. Structured data files (package.json, Cargo.toml,
     pom.xml, etc.)
  4. configure.ac  AC_INIT
  5. CMakeLists.txt  project(VERSION)
  6. meson.build  project(version:)
  7. .pc.in  Version: field
  8. #define PREFIX_VERSION "x.y.z"
  9. #define MAJOR/MINOR/PATCH split macros
 10. Broad fallback: any #define VERSION semver
 11. Header comment @version
 12. Makefile VERSION = x.y.z
"""

import json
import re
from pathlib import Path

from app.version_detection.patterns import (
    VER_RE,
    KV_MAJOR_RE,
    KV_MINOR_RE,
    KV_PATCH_RE,
    MAJOR_SUFFIXES,
    MINOR_SUFFIXES,
    PATCH_SUFFIXES,
    FOURTH_SUFFIXES,
)


def _safe_read(path):
    """Read file text, returning None on error."""
    try:
        return Path(path).read_text(
            errors="replace"
        )
    except OSError:
        return None


# ── Strategy 1: VERSION text files ──────────────


def parse_version_file(path):
    """Parse a VERSION / RELEASE plain text file.

    Takes the first line and extracts a version
    number. Works for files like:
        1.3.1
        v2.0.0-rc1
    """
    text = _safe_read(path)
    if not text:
        return None
    first_line = text.strip().splitlines()[0]
    m = VER_RE.search(first_line)
    return m.group(1) if m else None


# ── Strategy 2: Key-value version files ─────────


def parse_kv_version_file(path):
    """Parse key-value version files like OpenSSL's
    VERSION.dat:

        MAJOR=3
        MINOR=5
        PATCH=5

    Also handles colon-separated and dotted prefixes:
        version.major: 3
        VERSION.MAJOR = 3
    """
    text = _safe_read(path)
    if not text:
        return None

    major = KV_MAJOR_RE.search(text)
    minor = KV_MINOR_RE.search(text)
    if not major or not minor:
        return None

    patch = KV_PATCH_RE.search(text)
    maj = major.group(1)
    min_ = minor.group(1)
    if patch:
        return f"{maj}.{min_}.{patch.group(1)}"
    return f"{maj}.{min_}"


# ── Strategy 3: Structured data files ───────────


def parse_package_json(path):
    """Parse version from package.json.

    Standard for Node.js/JavaScript projects:
        {"version": "22.14.0"}
    """
    text = _safe_read(path)
    if not text:
        return None
    try:
        data = json.loads(text)
        ver = data.get("version")
        if ver and isinstance(ver, str):
            m = VER_RE.search(ver)
            return m.group(1) if m else None
    except (json.JSONDecodeError, AttributeError):
        pass
    return None


def parse_version_json(path):
    """Parse version.json files.

    Some projects use standalone version.json:
        {"version": "1.2.3"}
    or Node.js-style:
        [{"version": "22.14.0", ...}]
    """
    text = _safe_read(path)
    if not text:
        return None
    try:
        data = json.loads(text)
        # Handle array format (Node.js)
        if isinstance(data, list) and data:
            data = data[0]
        if isinstance(data, dict):
            ver = data.get("version")
            if ver and isinstance(ver, str):
                m = VER_RE.search(ver)
                return m.group(1) if m else None
    except (json.JSONDecodeError, AttributeError):
        pass
    return None


def parse_pyproject_toml(path):
    """Parse version from pyproject.toml.

    Handles the two standard locations:
        [project]
        version = "1.2.3"

        [tool.poetry]
        version = "1.2.3"

    Uses regex to avoid requiring a TOML parser.
    """
    text = _safe_read(path)
    if not text:
        return None
    m = re.search(
        r'^\s*version\s*=\s*["\']'
        rf"({VER_RE.pattern})",
        text,
        re.MULTILINE,
    )
    return m.group(1) if m else None


# ── Strategy 3d: Cargo.toml (Rust) ─────────────


def parse_cargo_toml(path):
    """Parse version from Cargo.toml.

    Standard for Rust projects:
        [package]
        version = "10.1.0"
    """
    text = _safe_read(path)
    if not text:
        return None
    m = re.search(
        r'^\s*version\s*=\s*["\']'
        rf"({VER_RE.pattern})",
        text,
        re.MULTILINE,
    )
    return m.group(1) if m else None


# ── Strategy 3e: pom.xml (Java/Maven) ──────────


def parse_pom_xml(path):
    """Parse version from pom.xml.

    Standard for Java/Maven projects:
        <version>1.2.3</version>

    Uses the first <version> under the root
    <project>, skipping parent version.
    """
    text = _safe_read(path)
    if not text:
        return None
    # Skip <parent>...</parent> block
    cleaned = re.sub(
        r"<parent>.*?</parent>",
        "", text, flags=re.DOTALL,
    )
    m = re.search(
        r"<version>\s*"
        rf"({VER_RE.pattern})"
        r"[^<]*</version>",
        cleaned,
    )
    return m.group(1) if m else None


# ── Strategy 4: configure.ac ────────────────────


def parse_configure_ac(path):
    """Parse AC_INIT from configure.ac.

    Patterns:
        AC_INIT([libname],[1.2.3])
        AC_INIT([libname], [1.2.3], [email])
        AC_INIT(name, 1.2.3)
    """
    text = _safe_read(path)
    if not text:
        return None
    m = re.search(
        r"AC_INIT\s*\("
        r"[^)]*?"
        r"[\[,]\s*"
        rf"({VER_RE.pattern})",
        text,
    )
    return m.group(1) if m else None


# ── Strategy 5: CMakeLists.txt ──────────────────


def parse_cmakelists(path):
    """Parse project(... VERSION x.y.z) from
    CMakeLists.txt."""
    text = _safe_read(path)
    if not text:
        return None
    m = re.search(
        r"project\s*\([^)]*?"
        r"VERSION\s+"
        rf"({VER_RE.pattern})",
        text,
        re.IGNORECASE,
    )
    return m.group(1) if m else None


# ── Strategy 6: meson.build ─────────────────────


def parse_meson_build(path):
    """Parse project(... version: 'x.y.z') from
    meson.build."""
    text = _safe_read(path)
    if not text:
        return None
    m = re.search(
        r"project\s*\([^)]*?"
        r"version\s*:\s*['\"]"
        rf"({VER_RE.pattern})",
        text,
    )
    return m.group(1) if m else None


# ── Strategy 7: .pc.in files ────────────────────


def parse_pc_in(path):
    """Parse Version: from .pc.in pkg-config file."""
    text = _safe_read(path)
    if not text:
        return None
    for line in text.splitlines():
        m = re.match(
            r"Version:\s*(.+)", line
        )
        if m:
            val = m.group(1).strip()
            vm = VER_RE.search(val)
            if vm:
                return vm.group(1)
    return None


# ── Strategy 8: #define PREFIX_VERSION "str" ─────


def parse_define_version_str(path, prefixes):
    """Parse #define PREFIX_VERSION "x.y.z" or
    #define PREFIX_RELEASE "Lib x.y.z".

    Tries each prefix candidate. Matches both
    _VERSION and _RELEASE suffixes.
    """
    text = _safe_read(path)
    if not text:
        return None

    for pfx in prefixes:
        for suffix in ("RELEASE", "VERSION"):
            pattern = (
                rf"#\s*define\s+{pfx}_{suffix}"
                r"\s+"
                r'"[^"]*?'
                rf"({VER_RE.pattern})"
            )
            m = re.search(pattern, text)
            if m:
                return m.group(1)
    return None


# ── Strategy 9: #define MAJOR/MINOR/PATCH ────────


def parse_define_parts(path, prefixes):
    """Parse split #define MAJOR/MINOR/PATCH macros.

    Handles both bare integers and quoted strings:
        #define LUA_VERSION_MAJOR "5"
        #define LUA_VERSION_MINOR "4"
        #define LUA_VERSION_RELEASE "8"
    or:
        #define V8_MAJOR_VERSION 12
        #define V8_MINOR_VERSION 4
        #define V8_BUILD_NUMBER 254
        #define V8_PATCH_LEVEL 21
    or:
        #define NODE_MAJOR_VERSION 22
        #define NODE_MINOR_VERSION 14
        #define NODE_PATCH_VERSION 0
    or:
        #define OPENSSL_VERSION_MAJOR 3
        #define OPENSSL_VERSION_MINOR 0
        #define OPENSSL_VERSION_PATCH 15

    Returns up to 4-part version when a fourth
    component is found (e.g. V8: 12.4.254.21).
    """
    text = _safe_read(path)
    if not text:
        return None

    # Value: bare int or quoted int
    val_re = r'(?:"(\d+)"|(\d+))'

    # Try each known prefix, then fall back
    # to a prefix-agnostic scan.
    all_prefixes = list(prefixes) + [r"\w*"]
    for pfx in all_prefixes:
        major = minor = patch = fourth = None
        for line in text.splitlines():
            stripped = line.strip()

            # MAJOR
            for sfx in MAJOR_SUFFIXES:
                m = re.match(
                    rf"#\s*define\s+{pfx}{sfx}\s+"
                    + val_re,
                    stripped,
                )
                if m:
                    major = m.group(1) or m.group(2)

            # MINOR
            for sfx in MINOR_SUFFIXES:
                m = re.match(
                    rf"#\s*define\s+{pfx}{sfx}\s+"
                    + val_re,
                    stripped,
                )
                if m:
                    minor = m.group(1) or m.group(2)

            # PATCH (broad aliases)
            for sfx in PATCH_SUFFIXES:
                m = re.match(
                    rf"#\s*define\s+{pfx}{sfx}\s+"
                    + val_re,
                    stripped,
                )
                if m:
                    val = m.group(1) or m.group(2)
                    # Prefer the first match unless
                    # this is a 4th-part suffix
                    if sfx in FOURTH_SUFFIXES:
                        if patch is not None:
                            fourth = val
                        else:
                            patch = val
                    else:
                        if patch is None:
                            patch = val

        if (
            major is not None
            and minor is not None
        ):
            parts = [major, minor]
            if patch is not None:
                parts.append(patch)
            if fourth is not None:
                parts.append(fourth)
            return ".".join(parts)

    return None


# ── Strategy 10: Broad #define VERSION fallback ──


def parse_define_any_version(path):
    """Broad fallback: any #define with VERSION in
    its name that contains a semver string.

    e.g. #define REDIS_VERSION "7.2.4"
         #define MY_LIB_VER "1.0.3"
    """
    text = _safe_read(path)
    if not text:
        return None

    m = re.search(
        r'#\s*define\s+\w*(?:VERSION|VER)\w*\s+'
        r'"'
        rf"({VER_RE.pattern})"
        r'"',
        text,
    )
    return m.group(1) if m else None


# ── Strategy 11: Header comment @version ─────────


def parse_header_comment(path):
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
                    rf"({VER_RE.pattern})",
                    line,
                    re.IGNORECASE,
                )
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None


# ── Strategy 12: Makefile VERSION = x.y.z ────────


def parse_makefile(path):
    """Parse VERSION variable from Makefile.

    Patterns:
        VERSION = 1.2.3
        VERSION=1.2.3
        LIB_VERSION = 1.2.3
    """
    text = _safe_read(path)
    if not text:
        return None
    m = re.search(
        r"^\w*VERSION\s*[:?]?=\s*"
        rf"({VER_RE.pattern})",
        text,
        re.MULTILINE,
    )
    return m.group(1) if m else None
