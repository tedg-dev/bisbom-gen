"""
Vendored dependency detection and sub-component splitting.

Detects vendored/embedded third-party source code in project
file trees and splits sub-components that declare their own
version identifiers distinct from the parent library.
"""

import re
from pathlib import Path

from app.spdx.lang_parsers import (
    go_module_from_vendor_path,
    rust_crate_from_registry_path,
)

# Regex for #define PREFIX_VERSION "x.y.z"
# Captures (prefix, version_string)
_SUB_VERSION_RE = re.compile(
    r'#define\s+(\w+?)_VERSION\s+'
    r'"[^"]*?(\d+\.\d+(?:\.\d+)?)'
)

# Directories that indicate vendored/embedded
# third-party source code.
VENDORED_DIRS = (
    "/deps/", "/vendor/", "/third_party/",
    "/thirdparty/", "/external/", "/contrib/",
)


def detect_vendored_groups(
    project_files, vendored_dirs=None, repo_name=None,
):
    """Group source files by vendored library.

    Scans project_files for paths matching
    VENDORED_DIRS patterns, then splits out
    embedded sub-components that declare their
    own version identifiers.

    For Go vendor directories, extracts full
    Go module names (e.g. github.com/fatih/color)
    instead of just the first path component.

    Args:
        project_files: list of artifact dicts with
            'file_path' keys
        vendored_dirs: tuple of directory patterns
            to match. Defaults to VENDORED_DIRS.
        repo_name: repository name (unused, reserved)

    Returns:
      (vendored, own, sub_versions) where:
        vendored: dict[lib_name] -> list[artifact]
        own: list[artifact]  (non-vendored)
        sub_versions: dict[lib_name] -> version
    """
    vdirs = vendored_dirs or VENDORED_DIRS

    vendored = {}
    own = []
    for art in project_files:
        # Normalize path to resolve ../ components
        # (e.g. /libnetutil/../nbase/x.h -> /nbase/x.h)
        fp = str(Path(art["file_path"]).resolve())
        matched = False
        # Skip Rust build output directories —
        # target/release/deps/ and target/debug/deps/
        # contain .rlib intermediates that falsely
        # match the /deps/ vendored pattern.
        if "/target/release/" in fp or (
            "/target/debug/" in fp
        ):
            own.append(art)
            continue
        # Try Rust crate from Cargo registry first
        crate_name, _ = (
            rust_crate_from_registry_path(fp)
        )
        if crate_name:
            vendored.setdefault(
                crate_name, []
            ).append(art)
            continue
        for vdir in vdirs:
            idx = fp.find(vdir)
            if idx < 0:
                continue
            rest = fp[idx + len(vdir):]
            # Try Go module extraction first
            go_mod = go_module_from_vendor_path(
                rest
            )
            if go_mod:
                vendored.setdefault(
                    go_mod, []
                ).append(art)
                matched = True
                break
            # C/C++ fallback: generic patterns use
            # first component; specific dirs use
            # the directory name itself
            if vdir in VENDORED_DIRS:
                lib = rest.split("/")[0]
            else:
                lib = (
                    vdir.strip("/").split("/")[-1]
                )
            if lib:
                vendored.setdefault(
                    lib, []
                ).append(art)
                matched = True
                break
        if not matched:
            own.append(art)

    # Split out sub-components (C/C++ only)
    vendored, sub_versions = (
        _split_sub_components(vendored)
    )
    return vendored, own, sub_versions


def _split_sub_components(vendored):
    """Split embedded sub-libraries out of
    vendored groups.

    Scans .c files in each vendored group for
    #define PREFIX_VERSION "x.y.z" where PREFIX
    does not match the parent library name.
    Files whose basename matches the sub-component
    prefix are moved to a new group.

    Example: deps/lua/src/lua_cjson.c defines
    CJSON_VERSION "2.1.0" -> split into a new
    "lua-cjson" group.

    Returns:
        (result, versions) where result is the
        updated vendored dict and versions is
        {full_name: version} for sub-components.
    """
    result = {}
    versions = {}
    for lib_name, arts in vendored.items():
        parent_prefix = (
            lib_name.upper()
            .replace("-", "_")
            .replace(".", "_")
        )
        sub_map = {}  # key -> (name, ver, [arts])
        remaining = []

        for art in arts:
            fp = art["file_path"]
            ext = Path(fp).suffix.lower()
            if ext not in (".c", ".h"):
                remaining.append(art)
                continue

            sub = _detect_sub_component(
                fp, parent_prefix
            )
            if sub:
                sub_name, sub_ver = sub
                key = sub_name.lower()
                if key not in sub_map:
                    sub_map[key] = (
                        sub_name, sub_ver, []
                    )
                sub_map[key][2].append(art)
            else:
                remaining.append(art)

        # Assign remaining files that match a
        # sub-component by basename prefix
        still_remaining = []
        for art in remaining:
            basename = Path(
                art["file_path"]
            ).stem.lower()
            assigned = False
            for key in sub_map:
                if key in basename:
                    sub_map[key][2].append(art)
                    assigned = True
                    break
            if not assigned:
                still_remaining.append(art)

        # Keep parent group with remaining files
        if still_remaining:
            result[lib_name] = still_remaining

        # Add sub-component groups
        for key, (name, ver, sub_arts) in (
            sub_map.items()
        ):
            full_name = f"{lib_name}-{name}"
            result[full_name] = sub_arts
            if ver:
                versions[full_name] = ver

    return result, versions


def _detect_sub_component(
    file_path, parent_prefix
):
    """Check if a source file defines its own
    version distinct from the parent library.

    Returns (sub_name, version) or None.
    """
    try:
        text = Path(file_path).read_text(
            errors="replace"
        )
    except OSError:
        return None

    for m in _SUB_VERSION_RE.finditer(text):
        prefix = m.group(1)
        version = m.group(2)
        norm = prefix.upper().replace(
            "-", "_"
        )
        # Skip if this is the parent lib's own
        # version define (e.g. LUA_VERSION,
        # LUA_VERSION_NUM) but NOT a different
        # library that starts with the parent
        # name (e.g. LUA_BITOP is lua-bitop)
        if norm == parent_prefix:
            continue
        # Skip generic names
        if norm in (
            "VERSION", "LIB", "PACKAGE",
            "MODULE",
        ):
            continue
        # Derive readable name from prefix
        name = prefix.lower().replace("_", "-")
        # Strip leading "lua-" etc. if parent
        # is already in the name
        lp = parent_prefix.lower()
        if name.startswith(lp + "-"):
            name = name[len(lp) + 1:]
        return (name, version)

    return None
