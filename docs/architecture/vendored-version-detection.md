# Version Detection

This document describes how bisbom-gen detects version information for
both the **root package** (the project being built) and **vendored (statically
linked) libraries** from source code. It covers root version extraction from
config tags, the 12 vendored detection strategies, real-world patterns that
motivated each one, known limitations, and guidance for handling edge cases.

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [Why Versions Matter in SBOMs](#2-why-versions-matter-in-sboms)
3. [Root Package Version Detection](#3-root-package-version-detection)
4. [Design Principles](#4-design-principles)
5. [The 12 Vendored Detection Strategies](#5-the-12-vendored-detection-strategies)
6. [Library Name Prefix Handling](#6-library-name-prefix-handling)
7. [Real-World Examples](#7-real-world-examples)
8. [Known Limitations](#8-known-limitations)
9. [How to Debug Missing Versions](#9-how-to-debug-missing-versions)
10. [Adding New Strategies](#10-adding-new-strategies)

---

## 1. The Problem

When a C/C++ project vendors a library (copies its source into the project
tree and compiles it statically), there is no package manager to provide
version metadata. Unlike Maven (pom.xml), Cargo (Cargo.lock), or Go (go.sum),
C/C++ vendored libraries declare their version in ad-hoc ways — if at all.

Consider nmap, which vendors 7+ libraries. Each one declares its version
differently:

| Library | Version Pattern | Where |
|---------|----------------|-------|
| liblua 5.4.8 | `#define LUA_VERSION_MAJOR "5"` | lua.h |
| libssh2 1.11.1 | `#define LIBSSH2_VERSION "1.11.1"` | libssh2.h |
| libdnet 1.18.0 | `AC_INIT([libdnet],[1.18.0])` | configure.ac |
| nsock 0.02 | Header comment | nsock.h |
| liblinear | `#define LIBLINEAR_VERSION 250` (flat int) | linear.h |
| nbase | No version at all (nmap-internal) | — |
| libnetutil | No version at all (nmap-internal) | — |

A generic version detector must anticipate all of these patterns and more.

## 2. Why Versions Matter in SBOMs

Without version information, an SBOM package entry is significantly less
useful:

- **Vulnerability matching** requires knowing the exact version to look up
  CVEs in the NVD. "liblua (no version)" cannot be matched against
  CVE-2023-XXXXX which affects "lua < 5.4.6".
- **License compliance** may need specific version checks — a library may
  have changed license between versions.
- **BDBA/Black Duck comparisons** become impossible without versions to
  correlate against binary scan results.
- **SPDX quality** — NTIA minimum elements for SBOMs include version as a
  recommended field.

## 3. Root Package Version Detection

The **root package** is the project being built (e.g., redis, oxipng,
checkstyle). Its version is set via a two-pronged approach:

### Primary: Config tag extraction

The pipeline extracts a semver-like version from the `branch` field in
`config.yaml`. Since every repo is pinned to a stable release tag (see
[Stable Tag Pinning](stable-tag-pinning.md)), the tag usually contains
the version:

| Tag format | Example | Extracted version |
|------------|---------|-------------------|
| `vX.Y.Z` | `v0.25.9` | `0.25.9` |
| `X.Y.Z` | `8.0.6` | `8.0.6` |
| `name-X.Y.Z` | `jsoup-1.22.1` | `1.22.1` |
| `rel/X.Y.Z` | `rel/2.24.3` | `2.24.3` |
| `nX.Y` | `n8.1` | `8.1` |

This covers **20 of 23** configured repos. The three exceptions are:
- `nmap` (`master` — no stable tags exist)
- `bc-java` (`r1rv84` — non-numeric tag)
- `curl` (`curl-8_19_0` — underscores instead of dots)

### Fallback: File-based detection

If no version is found in the tag, the pipeline falls back to
file-based detection using language-specific parsers:

| File | Language | Parser |
|------|----------|--------|
| `Cargo.toml` | Rust | `parse_cargo_toml` — extracts `version = "x.y.z"` |
| `pom.xml` | Java/Maven | `parse_pom_xml` — extracts `<version>`, skips `<parent>` block, handles `-SNAPSHOT` |

These parsers supplement the existing vendored strategies (which also
scan the repo root for VERSION files, `configure.ac`, etc.).

### Implementation

- **`collect_metadata.py`**: `_version_from_tag()` extracts version
  from config branch; `_detect_repo_version()` tries tag first, then
  file-based detection
- **`metadata_collector.py`**: passes `config_branch` from
  `config.yaml` to `collect_metadata.main()`
- **SPDX emitter**: uses the detected version as the root package
  `versionInfo` field

---

## 4. Design Principles

The `VendoredVersionDetector` class in `app/spdx/version_detector.py` follows
these principles:

### Cast a wide net, return the first match

Strategies are ordered from most reliable to least reliable. The detector
tries each one in sequence and returns the first successful match. This means
a VERSION file (highly reliable) will always win over a regex match in a
Makefile (less reliable).

### Be generic, not project-specific

Every strategy targets a pattern used across many C/C++ projects, not just the
ones we've analyzed so far. When we encounter a new project, the detector
should work without modification in most cases.

### Handle version format variations

The same conceptual version "5.4.8" appears as:
- `"5.4.8"` (quoted string)
- `5.4.8` (bare in VERSION file)
- Three separate `#define` macros for MAJOR, MINOR, PATCH
- Quoted strings in macros: `#define LUA_VERSION_MAJOR "5"`
- Inside a longer string: `#define LUA_RELEASE "Lua 5.4.8"`
- In build system metadata: `AC_INIT([libname],[5.4.8])`

### Flexible prefix matching

Library names in `#define` macros often differ from directory names:
- Directory `liblua/` → macros use `LUA_` prefix
- Directory `libdnet-stripped/` → macros use `DNET_` prefix
- Directory `xxhash/` → macros use `XXH_` prefix

The detector generates multiple prefix candidates and falls back to a
prefix-agnostic scan.

## 5. The 12 Vendored Detection Strategies

Strategies are tried in this order. The first match wins.

### Strategy 1: VERSION / RELEASE / VERSION.txt files

**Pattern:** Plain text file containing a semver string.

**Examples:**
```
# jemalloc VERSION file
5.3.0-0-g0

# libpcap VERSION.txt
1.10.5

# ffmpeg RELEASE file
8.0
```

**Why first:** These files exist specifically to declare the version and are
the most unambiguous source.

**File names checked:** `VERSION`, `VERSION.txt`, `RELEASE`

### Strategy 2: Key-value version files

**Pattern:** Structured key-value files like `VERSION.dat`.

**Examples:**
```
# jemalloc VERSION.dat
VERSION=5.3.0
```

### Strategy 3: Structured data files (package.json, Cargo.toml, pom.xml)

**Pattern:** Language-ecosystem files with a version field.

**Parsers:**

| File | Parser | Pattern |
|------|--------|---------|
| `package.json` | `parse_package_json` | `"version": "x.y.z"` |
| `version.json` | `parse_version_json` | `"version": "x.y.z"` |
| `pyproject.toml` | `parse_pyproject_toml` | `version = "x.y.z"` |
| `Cargo.toml` | `parse_cargo_toml` | `version = "x.y.z"` (Rust) |
| `pom.xml` | `parse_pom_xml` | `<version>x.y.z</version>` (Java/Maven) |

**`Cargo.toml` details:** Parses the `[package]` section for
`version = "x.y.z"`. Uses regex to extract the first semver match.

**`pom.xml` details:** Strips the `<parent>` block before extracting
`<version>` to avoid matching the parent POM's version. Handles
`-SNAPSHOT` suffixes by extracting only the numeric prefix.

### Strategy 4: configure.ac AC_INIT

**Pattern:** Autoconf `AC_INIT` macro with version argument.

**Examples:**
```m4
AC_INIT([libdnet],[1.18.0])
AC_INIT([libname], [1.2.3], [maintainer@example.com])
AC_INIT(name, 1.2.3)
```

**Why second:** `configure.ac` is the canonical version source for autotools
projects. The version in `AC_INIT` is what gets substituted into `config.h`,
`.pc` files, and `--version` output.

**Regex:** `AC_INIT\s*\([^)]*?[\[,]\s*(\d+\.\d+(?:\.\d+)?)`

**Real-world hit:** libdnet-stripped in nmap (`AC_INIT([libdnet],[1.18.0])`)

### Strategy 5: CMakeLists.txt project(VERSION)

**Pattern:** CMake `project()` command with VERSION keyword.

**Examples:**
```cmake
project(libssh2 C VERSION 1.11.1)
cmake_minimum_required(VERSION 3.1)  # NOT this one — no project()
project(mylib VERSION 2.0.0 LANGUAGES C CXX)
```

**Regex:** `project\s*\([^)]*?VERSION\s+(\d+\.\d+(?:\.\d+)?)`

**Note:** The regex matches `VERSION` inside `project()` parentheses, avoiding
false matches on `cmake_minimum_required(VERSION ...)`.

### Strategy 6: meson.build project(version:)

**Pattern:** Meson build system `project()` with `version:` keyword argument.

**Examples:**
```meson
project('mylib', 'c',
  version: '2.4.1',
)
```

**Regex:** `project\s*\([^)]*?version\s*:\s*['"](\d+\.\d+(?:\.\d+)?)`

### Strategy 7: .pc.in files

**Pattern:** pkg-config template files with `Version:` field.

**Examples:**
```
Name: hiredis
Version: 1.2.0
```

**Real-world hit:** hiredis in redis (`hiredis.pc.in`)

### Strategy 8: #define PREFIX_VERSION / PREFIX_RELEASE strings

**Pattern:** Single-line `#define` with the library prefix, containing a
quoted version string.

**Examples:**
```c
#define LIBSSH2_VERSION    "1.11.1"
#define LUA_RELEASE        "Lua 5.4.8"
#define REDIS_VERSION      "7.2.4"
#define PCRE2_RELEASE      "PCRE2 10.42"
```

**Key detail:** RELEASE is checked **before** VERSION because RELEASE
typically includes the patch level. For example, Lua defines:
```c
#define LUA_VERSION   "Lua 5.4"        // only major.minor
#define LUA_RELEASE   "Lua 5.4.8"      // full version with patch
```

If we checked VERSION first, we'd get `5.4` instead of `5.4.8`.

**Prefix candidates:** Generated by `_name_prefixes()` — see
[Section 5](#5-library-name-prefix-handling).

### Strategy 9: #define MAJOR / MINOR / PATCH|RELEASE|MICRO parts

**Pattern:** Separate `#define` macros for each version component.

**Examples:**
```c
// Bare integers (hiredis)
#define HIREDIS_MAJOR 1
#define HIREDIS_MINOR 2
#define HIREDIS_PATCH 0

// Quoted strings (Lua 5.4+)
#define LUA_VERSION_MAJOR   "5"
#define LUA_VERSION_MINOR   "4"
#define LUA_VERSION_RELEASE "8"

// MICRO instead of PATCH (ffmpeg libavcodec)
#define LIBAVCODEC_VERSION_MAJOR  61
#define LIBAVCODEC_VERSION_MINOR  23
#define LIBAVCODEC_VERSION_MICRO 103
```

**Aliases for PATCH:** The detector recognizes `PATCH`, `RELEASE`, and `MICRO`
as the third version component. This is critical — many real projects use
non-standard names:

| Project | Third component name |
|---------|---------------------|
| Most libraries | PATCH |
| Lua | RELEASE |
| ffmpeg/libav* | MICRO |
| xxhash | RELEASE |

**Quoted vs. bare:** The regex `(?:"(\d+)"|(\d+))` matches both `"5"` and `5`.

**Prefix-agnostic fallback:** After trying all known prefix candidates, the
detector tries a wildcard `\w*` prefix. This handles cases like xxhash where
the library name is "xxhash" but the macros use `XXH_` — a prefix that cannot
be algorithmically derived from the name.

### Strategy 10: Broad #define fallback

**Pattern:** Any `#define` with `VERSION` or `VER` in its name containing a
quoted semver string.

**Examples:**
```c
#define REDIS_VERSION "7.2.4"
#define MY_LIB_VER "1.0.3"
```

**Why a fallback:** This is intentionally broad and runs late in the strategy
order to avoid false matches. It does not require the macro name to match the
library name at all.

### Strategy 11: Header comment version

**Pattern:** Version string in a comment block in the first 20 lines of a
header file.

**Examples:**
```c
/* linenoise.h -- VERSION 1.0
 * A readline replacement.
 */

/* nsock -- @version 0.02 */
```

**Scans:** First 20 lines only, to avoid matching version strings deep in the
file that may refer to something else (protocol versions, format versions,
etc.).

### Strategy 12: Makefile VERSION variables

**Pattern:** VERSION assignment in a Makefile.

**Examples:**
```makefile
VERSION = 3.7.2
LIB_VERSION = 1.0.0
VERSION := 2.1.0
```

**Regex:** `^\w*VERSION\s*[:?]?=\s*(\d+\.\d+(?:\.\d+)?)` (multiline)

**Why last:** Makefile version variables are less reliable because they may
refer to ABI versions, SO versions, or other non-semantic version numbers.

## 6. Library Name Prefix Handling

The `_name_prefixes()` method generates multiple prefix candidates from the
library directory name, accounting for common naming conventions:

```
Input: "liblua"
Output: ["LIBLUA", "LUA"]

Input: "libssh2"
Output: ["LIBSSH2", "SSH2"]

Input: "libdnet-stripped"
Output: ["LIBDNET_STRIPPED", "DNET_STRIPPED", "LIBDNET", "DNET"]

Input: "hiredis"
Output: ["HIREDIS"]
```

**Transformations applied:**

1. **Uppercase + hyphen-to-underscore:** `libdnet-stripped` → `LIBDNET_STRIPPED`
2. **Strip `lib` prefix:** `LIBLUA` → `LUA`
3. **Strip trailing qualifiers:** `_STRIPPED`, `_NG`, `_LITE`

Each transformation is applied to all existing candidates, and duplicates are
removed while preserving order (most specific first).

After all named prefixes are exhausted, Strategy 7 falls back to `\w*` as a
wildcard prefix to catch completely unpredictable naming.

## 7. Real-World Examples

### nmap Vendored Libraries (March 2026)

| Library | Strategy Used | Version Found |
|---------|--------------|---------------|
| liblua | #7 (quoted MAJOR/MINOR/RELEASE with LUA prefix) | 5.4.8 |
| libssh2 | #6 (#define LIBSSH2_VERSION "1.11.1") | 1.11.1 |
| libdnet-stripped | #2 (AC_INIT in configure.ac) | 1.18.0 |
| nsock | #9 (header comment) | 0.02 |
| liblinear | None — flat integer `#define LIBLINEAR_VERSION 250` | (none) |
| nbase | None — nmap-internal, no version | (none) |
| libnetutil | None — nmap-internal, no version | (none) |

### redis Vendored Libraries (March 2026)

| Library | Strategy Used | Version Found |
|---------|--------------|---------------|
| jemalloc | #1 (VERSION file) | 5.3.0 |
| lua | #6 (#define LUA_RELEASE "Lua 5.1.5") | 5.1.5 |
| hiredis | #7 (MAJOR/MINOR/PATCH defines) | 1.2.0 |
| xxhash | #7 (MAJOR/MINOR/RELEASE with wildcard prefix) | 0.8.3 |
| linenoise | #9 (header comment "VERSION 1.0") | 1.0 |
| fpconv | #9 (header comment) | 1.0 |
| fast_float | None — header-only, version in namespace | (none) |
| hdr_histogram | None — no standard version marker | (none) |

### Improvement Over Previous Detector

| Package | Before (4 strategies) | After (12 strategies) |
|---------|----------------------|----------------------|
| liblua (nmap) | (none) | **5.4.8** |
| nsock (nmap) | (none) | **0.02** |
| lua (redis) | 5.1 | **5.1.5** |
| xxhash (redis) | 0.8 | **0.8.3** |
| fpconv (redis) | (none) | **1.0** |
| linenoise (redis) | (none) | **1.0** |

The improvements came from: quoted string support, RELEASE-as-PATCH alias,
lib prefix stripping, prefix-agnostic fallback, expanded header comment
scanning window, and configure.ac/CMakeLists.txt parsing.

## 8. Known Limitations

### Flat integer versions

Some libraries use a single integer for their version:

```c
#define LIBLINEAR_VERSION 250
```

This could mean 2.5.0, 25.0, or something else entirely. Without a standard
interpretation, the detector does not attempt to parse flat integers. This is
a conscious design decision — guessing wrong is worse than not guessing at all.

### Internal sub-libraries

Projects like nmap have internal components (nbase, libnetutil, nsock) that do
not have independent version numbers. They are versioned implicitly with the
parent project. The detector correctly returns `None` for these — they could
inherit the parent project version, but that would be misleading in an SBOM
because these are not independently released components.

### Non-standard version locations

Some projects hide version information in places the detector does not check:

- Inline in a namespace: `namespace fast_float::v6_3_0`
- In a changelog or NEWS file
- In a git tag (not available in vendored copies)
- In a Python script that generates headers

### Multi-version headers

A header file may contain version macros for multiple things:

```c
#define OPENSSL_VERSION_NUMBER 0x30000000L
#define LIBSSH2_VERSION "1.11.1"
```

The prefix-based matching (Strategy 6-7) handles this by only matching macros
with the library's prefix. The broad fallback (Strategy 8) could
theoretically match the wrong one, but since it runs last, a prefix-specific
match will win first.

## 9. How to Debug Missing Versions

If a vendored library is showing `(none)` for its version:

1. **Check what files the library provides:**
   ```bash
   find repos/project/vendored-lib -name '*.h' -o -name 'VERSION*' \
     -o -name 'configure.ac' -o -name 'CMakeLists.txt'
   ```

2. **Search for version patterns in headers:**
   ```bash
   grep -rn 'VERSION\|MAJOR\|MINOR\|PATCH\|RELEASE' \
     repos/project/vendored-lib/*.h
   ```

3. **Check build system files:**
   ```bash
   head -5 repos/project/vendored-lib/configure.ac
   grep -i 'project.*version' repos/project/vendored-lib/CMakeLists.txt
   ```

4. **Run the detector in isolation:**
   ```python
   from app.spdx.version_detector import VendoredVersionDetector
   det = VendoredVersionDetector()
   files = ["/path/to/lib/header.h", "/path/to/lib/src/code.c"]
   print(det.detect("libname", files))
   ```

5. **Check prefix generation:**
   ```python
   print(det._name_prefixes("libname"))
   ```

## 10. Adding New Strategies

To add a new detection strategy:

1. Add a `parse_*` function in `app/version_detection/strategies.py`
2. For structured data files (e.g., `Cargo.toml`), register the parser
   in `_STRUCTURED_PARSERS` in `app/version_detection/detector.py` and
   add the filename to `STRUCTURED_VERSION_FILES` in
   `app/version_detection/patterns.py`
3. For other strategies, add the call in `detect()` in the appropriate
   position (more reliable strategies earlier)
4. Use `_safe_read()` for file I/O (handles OSError gracefully)
5. Match against `VER_RE` for consistent semver extraction
6. Add tests in `tests/test_version_detection.py`
7. Add an unreadable-file test for graceful error handling

The test suite currently has 80+ version detector tests covering all 12
strategies, root version extraction, and prefix generation.

---

*Last updated: April 29, 2026*
