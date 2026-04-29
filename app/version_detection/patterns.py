"""
Regex patterns and constants for version detection.

Centralizes all version-related regular expressions,
file name patterns, and macro suffix aliases used
across detection strategies.
"""

import re

# ── Version number patterns ─────────────────────

# 2-part: X.Y
# 3-part: X.Y.Z
# 4-part: X.Y.Z.W  (V8 style: 12.4.254.21)
VER_RE = re.compile(
    r"(\d+\.\d+(?:\.\d+){0,2})"
)

# Stricter semver: X.Y.Z only (no 2-part)
SEMVER_RE = re.compile(
    r"(\d+\.\d+\.\d+)"
)

# ── Key-value version file patterns ─────────────
# Used by OpenSSL VERSION.dat, version.mk, etc.
# Matches: MAJOR=3, MINOR=5, PATCH=5
KV_MAJOR_RE = re.compile(
    r"^(?:\w*[_.])?MAJOR\s*[:=]\s*(\d+)",
    re.MULTILINE | re.IGNORECASE,
)
KV_MINOR_RE = re.compile(
    r"^(?:\w*[_.])?MINOR\s*[:=]\s*(\d+)",
    re.MULTILINE | re.IGNORECASE,
)
KV_PATCH_RE = re.compile(
    r"^(?:\w*[_.])?PATCH\s*[:=]\s*(\d+)",
    re.MULTILINE | re.IGNORECASE,
)

# ── #define macro suffixes ──────────────────────
# Major version macro suffixes (after prefix)
MAJOR_SUFFIXES = (
    "_MAJOR",
    "_VERSION_MAJOR",
    "_MAJOR_VERSION",
)

# Minor version macro suffixes
MINOR_SUFFIXES = (
    "_MINOR",
    "_VERSION_MINOR",
    "_MINOR_VERSION",
)

# Patch/build/release macro suffixes — broad
# coverage of real-world naming conventions:
#   _PATCH         libuv, OpenSSL
#   _PATCH_VERSION Node.js
#   _PATCH_LEVEL   V8
#   _RELEASE       Lua
#   _MICRO         GLib, GTK
#   _BUILD_NUMBER  V8
#   _BUILD         misc
#   _TEENY         Ruby
#   _SUBMINOR      FreeType
#   _VERSION_PATCH OpenSSL headers
PATCH_SUFFIXES = (
    "_PATCH",
    "_PATCH_VERSION",
    "_PATCH_LEVEL",
    "_VERSION_PATCH",
    "_RELEASE",
    "_VERSION_RELEASE",
    "_MICRO",
    "_VERSION_MICRO",
    "_BUILD_NUMBER",
    "_VERSION_BUILD_NUMBER",
    "_BUILD",
    "_VERSION_BUILD",
    "_TEENY",
    "_VERSION_TEENY",
    "_SUBMINOR",
    "_VERSION_SUBMINOR",
)

# 4th-part suffixes (optional, V8-style)
FOURTH_SUFFIXES = (
    "_PATCH_LEVEL",
    "_BUILD_NUMBER",
    "_TWEAK",
)

# ── Version file names ──────────────────────────
# Plain-text version files (strategy 1)
VERSION_FILE_NAMES = (
    "VERSION",
    "VERSION.txt",
    "RELEASE",
    "version",
    "version.txt",
)

# Key-value version files (strategy 2)
KV_VERSION_FILE_NAMES = (
    "VERSION.dat",
    "version.properties",
    "version.mk",
)

# Structured data files (strategy 3)
STRUCTURED_VERSION_FILES = (
    "package.json",
    "version.json",
    "pyproject.toml",
    "Cargo.toml",
    "pom.xml",
)

# ── Name prefix generation ──────────────────────


def name_prefixes(lib_name):
    """Generate candidate prefixes from a library name
    for #define macro matching.

    e.g. "liblua"  -> ["LIBLUA", "LUA"]
         "libssh2" -> ["LIBSSH2", "SSH2"]
         "openssl" -> ["OPENSSL"]
         "v8"      -> ["V8"]
         "icu-small" -> ["ICU_SMALL", "ICU"]
    """
    base = lib_name.upper().replace("-", "_")
    candidates = [base]

    # Strip "lib" prefix
    if base.startswith("LIB"):
        candidates.append(base[3:])

    # Strip trailing qualifiers
    for suffix in (
        "_STRIPPED", "_NG", "_LITE", "_SMALL",
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
