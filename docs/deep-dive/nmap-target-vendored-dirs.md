# Nmap Analysis Target + Vendored Directory Detection

**Date:** 2026-02-26
**PR:** #19 (commit 1 of 3)

## Summary

Added Nmap as a new OmniBOR analysis target with a rich mix of vendored static
libraries and dynamic system dependencies. To support Nmap's non-standard
directory layout, introduced a configurable `vendored_dirs` option per
repository in `config.yaml`.

Also added detection of project-built shared objects (`.so` files) that `ldd`
reports as "not found" — these are libraries built by the project itself rather
than installed system packages.

## Nmap Configuration

```yaml
nmap:
  url: https://github.com/nmap/nmap.git
  branch: master
  build_steps:
  - ./configure --with-libpcre=/usr --with-libz=/usr --with-libssh2=/usr
    --with-openssl=/usr --with-libdnet=included --with-liblua=included
    --with-liblinear=included --without-zenmap --without-ndiff
  - make -j$(nproc)
  output_binaries: [nmap, ncat/ncat, nping/nping]
  apt_deps: [libpcap-dev, flex, bison]
  vendored_dirs:
  - /libdnet-stripped/
  - /liblinear/
  - /liblua/
  - /libnetutil/
  - /libpcap/
  - /libpcre/
  - /libssh2/
  - /libz/
  - /nbase/
  - /nsock/
```

### Configure Flag Strategy

The `--with-<lib>=/usr` flags tell Nmap to use the system-installed version
of that library (dynamically linked). The `--with-<lib>=included` flags tell
Nmap to use its vendored copy (statically compiled in). This produces exactly
the mixed dependency profile needed for comprehensive SBOM generation.

## Vendored Directory Detection: The Problem

Previously, `SpdxEmitter._detect_vendored_groups()` only recognized files
under generic container directories like `/deps/`, `/vendor/`, `/third_party/`,
etc. It would look for the library name as the **first path component after**
the container directory (e.g., `/deps/lua/src/lapi.c` → library name `lua`).

Nmap structures its vendored libraries differently — each library lives in a
**top-level directory** named after itself:

```
nmap/
├── liblua/           ← vendored Lua 5.4.8
│   ├── lapi.c
│   ├── lua.h
│   └── ...
├── libdnet-stripped/ ← vendored libdnet 1.18.0
│   └── src/
├── libssh2/          ← vendored libssh2 1.11.1
│   ├── src/
│   └── include/
├── nmap.cc           ← project's own source
└── ...
```

There is no `/deps/` or `/vendor/` container. The directory IS the library.

## Vendored Directory Detection: The Solution

Added a `vendored_dirs` config option per repository. When provided, these
patterns override the class-level `VENDORED_DIRS` defaults:

- **Generic patterns** (`/deps/`, `/vendor/`): library name = first component
  after the pattern (existing behavior, unchanged)
- **Specific patterns** (`/liblua/`, `/libssh2/`): library name = the
  directory name from the pattern itself

The distinction is made by checking whether the pattern is in the class-level
`VENDORED_DIRS` tuple. If not, it's a specific library directory and the
library name is extracted from `vdir.strip("/").split("/")[-1]`.

### Implementation

```python
# In SpdxEmitter._detect_vendored_groups():
if vdir in self.VENDORED_DIRS:
    # Generic: /deps/lua/src/file.c → "lua"
    rest = fp[idx + len(vdir):]
    lib = rest.split("/")[0]
else:
    # Specific: /liblua/src/file.c → "liblua"
    lib = vdir.strip("/").split("/")[-1]
```

The `vendored_dirs` parameter is threaded through:
1. `config.yaml` → per-repo `vendored_dirs` list
2. `AdgSpdxStep.generate()` → reads from config
3. `AdgSpdxGenerator.__init__()` → stores and passes to emitter
4. `SpdxEmitter.__init__()` → uses `_vendored_dirs` instance attribute

## Project-Built Shared Object Detection

Added detection in `collect_dynamic_libs.py` for `.so` files that `ldd`
reports as "not found". These are `NEEDED` entries from `readelf -d` that
don't resolve to system paths — they're shared libraries built by the project
itself (e.g., `libavcodec.so.62` built by FFmpeg).

These are recorded with `project_built=true` in `dynamic_libs.json` and
emitted as SPDX packages with `DYNAMIC_LINK` relationships in
`spdx_from_adg.py`.

## Analysis Results

Build time: **197.5s** (~3.3 min) on 1-vCPU droplet — much faster than
FFmpeg's 24 min.

### nmap SPDX: 23 packages

| Category | Count | Examples |
|---|---|---|
| Root binary | 1 | nmap |
| STATIC_LINK (vendored) | 7 | libdnet-stripped (1.18.0), liblinear, liblua, libnetutil, libssh2 (1.11.1), nbase, nsock |
| DYNAMIC_LINK (system) | 14 | libc6, libssl3, libpcap0.8, libpcre2-8-0, zlib1g, libgcc-s1, ... |
| BUILD_TOOL_OF | 1 | gcc |

### ncat SPDX: 20 packages

5 direct + 8 transitive dynamic libs, plus vendored libs

### nping SPDX: 21 packages

6 direct + 10 transitive dynamic libs, plus vendored libs

### Version Detection

VendoredVersionDetector found versions for 2 of 7 vendored libs:
- libdnet-stripped: **1.18.0** (from `#define DNET_VERSION`)
- libssh2: **1.11.1** (from `#define LIBSSH2_VERSION`)

## Files Changed

- `app/config.yaml` — nmap entry with vendored_dirs
- `app/spdx_from_adg.py` — vendored_dirs parameter, specific dir detection,
  project-built .so emission
- `app/analyze.py` — pass vendored_dirs from config to AdgSpdxGenerator
- `app/collect_dynamic_libs.py` — project-built .so detection
- `docker/Dockerfile` — libpcap-dev, flex, bison
- `tests/test_spdx_from_adg.py` — 6 new tests for vendored_dirs
- `tests/test_analyze.py` — AdgSpdxStep tests
