# Go Language Support in OmniBOR Analysis

This document describes all changes made to support Go (Golang)
projects in the omnibor-analysis pipeline.

## Overview

Go support extends the existing C/C++ build interception pipeline
to handle Go's compiler toolchain, vendored module dependencies,
and standard library. The pipeline uses **bomtrace2** (not
bomtrace3) to intercept Go compile and link commands, then
generates SPDX 2.3 SBOMs with full dependency breakdown.

## SPDX Output Files

Each analysis run produces **three** SPDX files per binary:

| File | Purpose |
|------|---------|
| `<binary>_adg.spdx.json` | **Primary output.** Built from bomtrace2's build interception data. Contains all dependency relationships (DEPENDS_ON, BUILD_TOOL_OF, DYNAMIC_LINK), source file listings, Go module packages with versions and PURLs. |
| `<binary>_omnibor.spdx.json` | OmniBOR artifact identity document. Lists cryptographic identifiers (gitoid hashes) for the binary and its build inputs. **Intentionally has no dependency relationships** — its purpose is provenance tracking, not dependency analysis. |
| `<binary>_syft.spdx.json` | Syft baseline SBOM. Generated from `go.mod`/`go.sum` manifest files as a comparison baseline. |

Each `.spdx.json` file has a corresponding `.spdx.html`
interactive D3.js visualization.

## How Go Builds Are Intercepted

### Why bomtrace2 (not bomtrace3)

Go's internal compiler (`compile`) and linker (`link`) are
invoked by the `go` tool, not by the system shell. bomtrace3
only intercepts `execve` syscalls from forked processes, which
misses Go's internal tool invocations. bomtrace2 uses a
different hooking mechanism that can trace these tools when
configured to watch them explicitly.

### Go-specific bomtrace2 configuration

File: `docker/bomtrace_go.conf`

Key settings:
- **`-n` flag**: Prevents BOM section embedding. Go's compiler
  verifies source file checksums; modifying `.go` files after
  interception causes build failures.
- **`-w` flag**: Explicitly watches
  `/usr/local/go/pkg/tool/linux_amd64/compile` and `link`.
  bomtrace2 does not auto-discover Go tools.
- **`syscalls=openat`**: Go tools use `openat` instead of
  `open` for file I/O. Without this, bomtrace2 sees no file
  operations.
- **`go build -a`**: The `-a` flag is required to bypass Go's
  build cache so that bomtrace2 captures all compilation steps.

### Upstream bomsh patch required

File: `docker/patches/bomsh_hook2_golang_path.patch`

The upstream `bomsh_hook2.py` function `is_golang_prog()` only
matches Go tools under `/usr/lib/go-*` and `/usr/lib/golang/`.
The official Go installer (go.dev/dl) installs to
`/usr/local/go/`, which is not matched. Our patch adds
`"local/go"` to the path check. See `docs/upstream-changes.md`
for details on proposing this fix upstream.

## Go Module Resolution in ADG SPDX

### Source: `app/spdx_from_adg.py`

The ADG SPDX generator was extended with Go-specific logic:

### 1. File classification (`AdgParser.parse()`)

Files under `/usr/local/go/src/` are classified as `go_stdlib`
(Go standard library). All other classification rules (system
libs, headers, project source, etc.) remain unchanged.

### 2. Go module name extraction (`SpdxEmitter._go_module_from_vendor_path()`)

Go vendor directories use multi-segment module paths. The
extraction logic handles:

| Pattern | Example | Extracted module |
|---------|---------|-----------------|
| 3-segment hosts | `github.com/fatih/color/color.go` | `github.com/fatih/color` |
| Major version suffix | `github.com/gdamore/tcell/v2/screen.go` | `github.com/gdamore/tcell/v2` |
| golang.org | `golang.org/x/crypto/ssh/keys.go` | `golang.org/x/crypto` |
| gopkg.in (dotted) | `gopkg.in/yaml.v3/yaml.go` | `gopkg.in/yaml.v3` |
| gopkg.in (3-segment) | `gopkg.in/ozeidan/fuzzy-patricia.v3/p.go` | `gopkg.in/ozeidan/fuzzy-patricia.v3` |
| Other domains | `dario.cat/mergo/merge.go` | `dario.cat/mergo` |

Three-segment hosts: `github.com`, `gitlab.com`,
`bitbucket.org`, `golang.org`.

### 3. Module version extraction (`SpdxEmitter._parse_go_modules_txt()`)

Parses `vendor/modules.txt` to extract module versions. Lines
like `# github.com/fatih/color v1.16.0` are parsed into a
`{module_path: version}` dictionary.

### 4. Direct vs indirect classification (`SpdxEmitter._parse_go_mod()`)

Parses `go.mod` to classify dependencies as direct or indirect.
Lines with `// indirect` comment are indirect (transitive)
dependencies. This mirrors what GitHub's Dependency Graph shows.

### 5. Go version detection (`SpdxEmitter._detect_go_version()`)

Detects the Go compiler version via two strategies:
1. Look for `-goversion` flag in build commands
2. Read `/usr/local/go/VERSION` file (first line only — file
   is multi-line)

Falls back to `"unknown"` if neither source is available.

### 6. SPDX packages emitted for Go builds

| Package | Purpose | Relationship |
|---------|---------|-------------|
| Root binary (e.g. `lazygit`) | The built binary | DESCRIBES |
| Go modules (direct) | Direct dependencies from go.mod | DEPENDS_ON |
| Go modules (indirect) | Transitive dependencies (go.mod `// indirect`) | DEPENDS_ON |
| `go` | Go compiler/toolchain | BUILD_TOOL_OF |
| `go-stdlib` | Go standard library | DEPENDS_ON |
| `gcc` | GCC (always present, used by cgo) | BUILD_TOOL_OF |
| Dynamic libs (e.g. `libc6`) | Runtime shared libraries | DYNAMIC_LINK |

Each Go module package includes:
- **Version** from `vendor/modules.txt`
- **PURL** in format `pkg:golang/<module>@<version>`
- **Download location** pointing to `https://pkg.go.dev/<module>`
- **Comment** indicating `"Go module (direct)"` or
  `"Go module (indirect)"`
- **Source file count** compiled into the binary

## Visualization

### Source: `app/spdx_visualize.py`

The D3.js visualization supports five relationship types:

| Relationship | Color | Line style |
|-------------|-------|-----------|
| STATIC_LINK | Teal (#4ecdc4) | Solid |
| DYNAMIC_LINK | Red (#ff6b6b) | Solid |
| BUILD_TOOL_OF | Yellow (#ffd93d) | Dashed |
| DEPENDS_ON | Blue (#56b6f7) | Solid |

Node groups: root (purple), static (teal), dynamic (red),
build tool (yellow), dependency (blue), other (gray).

## SPDX ID Sanitization

SPDX 2.3 requires identifiers to match `[a-zA-Z0-9.-]+`.
Underscores are not allowed. The `_sanitize_spdx_id()` method
replaces underscores with hyphens and strips other invalid
characters. This is important for Go modules whose names often
contain underscores (e.g., `jibber_jabber` → `jibber-jabber`).

## Files Changed for Go Support

### New files

| File | Purpose |
|------|---------|
| `docker/bomtrace_go.conf` | Go-specific bomtrace2 configuration |
| `docker/patches/bomsh_hook2_golang_path.patch` | Upstream fix for `is_golang_prog()` |
| `docs/go-language-support.md` | This document |
| `docs/upstream-changes.md` | Tracking upstream bomsh issues |

### Modified files

| File | Changes |
|------|---------|
| `app/spdx_from_adg.py` | Go stdlib classification, Go module extraction from vendor paths, modules.txt version parsing, go.mod direct/indirect parsing, Go version detection, Go compiler + stdlib + module SPDX packages, PURL generation, DEPENDS_ON relationships, SPDX ID underscore fix |
| `app/spdx_visualize.py` | Added DEPENDS_ON edge rendering, dependency node group (blue), legend entries |
| `app/analyze.py` | Go build pipeline (bomtrace2), Go-specific config, language-aware output paths |
| `app/config.yaml` | lazygit repo entry with `language: go` |
| `docker/Dockerfile` | Go SDK install, bomsh_hook2.py patch application, bomtrace_go.conf copy |
| `tests/test_spdx_from_adg.py` | 31 new Go-specific tests covering module extraction, version detection, go.mod parsing, SPDX emission |

## Test Coverage

Go module resolution is tested with 31 dedicated tests across
5 test classes:

- `TestGoModuleFromVendorPath` — 11 tests for module name
  extraction (3-segment hosts, /vN suffix, gopkg.in, etc.)
- `TestDetectGoVersion` — 4 tests (build cmd, VERSION file,
  fallback, empty)
- `TestParseGoModulesTxt` — 3 tests
- `TestParseGoMod` — 3 tests (direct/indirect classification)
- `TestGoStdlibClassification` — 1 test
- `TestGoModuleEmission` — 9 tests (SPDX packages, PURLs,
  DEPENDS_ON, BUILD_TOOL_OF, direct/indirect comments)

`spdx_from_adg.py` has **100% test coverage**.

## Example: lazygit Analysis Results

| Metric | Value |
|--------|-------|
| Total packages | 67 |
| Direct Go modules | 33 |
| Indirect Go modules | 29 |
| Go compiler + stdlib | 2 |
| GCC build tool | 1 |
| Dynamic libs (libc6) | 1 |
| Root binary | 1 |
| Source files | 1,179 |
| DEPENDS_ON edges | 63 |
| BUILD_TOOL_OF edges | 2 |
| DYNAMIC_LINK edges | 1 |
| Semantic validation | PASS |
