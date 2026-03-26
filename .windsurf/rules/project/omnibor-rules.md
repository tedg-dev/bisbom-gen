---
description: Rules for OmniBOR/Bomsh build interception workflow
---

# OmniBOR / Bomsh Rules

## Terminology

- **Build Interception** — instrumenting the compiler/linker to observe what is actually compiled
- **Bomtrace3** — the preferred tracer (20% overhead vs 2-5x for bomtrace2)
- **ADG** — Artifact Dependency Graph (OmniBOR's output format)
- **Treedb** — bomsh's hash-tree database mapping gitoid hashes to file paths
- **Vendored library** — third-party source compiled into the project (STATIC_LINK)
- **Build Metadata Extraction** (Yocto SBOM, Maven plugins) is NOT true build interception;
  it is essentially manifest scanning enhanced with build-system context

## Full Pipeline Sequence (C/C++)

1. Clone target repo into `repos/<name>/`
2. Syft baseline SBOM (manifest-based, for comparison)
3. Validate apt dependencies are installed
4. Run pre-build steps (autoreconf, configure) WITHOUT bomtrace instrumentation
5. Run the final `make` step WITH bomtrace3: `bomtrace3 make -j$(nproc)`
6. `bomsh_create_bom.py` generates ADG from raw logfile → treedb + gitoid mappings
7. `bomsh_sbom.py` generates OmniBOR SPDX SBOM from ADG
8. `collect_metadata.py` resolves system files in treedb to dpkg packages
9. `collect_dynamic_libs.py` identifies per-binary dynamic libs via ldd/readelf
10. `spdx_from_adg.py` generates per-binary ADG SPDX with:
    - Vendored static lib detection (STATIC_LINK)
    - Dynamic system lib resolution (DYNAMIC_LINK)
    - Build tool identification (BUILD_TOOL_OF)
    - Automatic version detection for vendored libs
    - Interactive D3.js HTML dependency graph
11. SPDX validation (JSON Schema + semantic)

## Go Pipeline Sequence

Go repos use **bomtrace2** with a Go-specific `bomtrace_go.conf` that watches
Go's internal compiler tools (`compile`, `link`) and traces the `openat` syscall.
The `go build -a` flag bypasses Go's build cache so bomtrace2 captures all
compilation steps.

1. Clone target repo into `repos/<name>/`
2. Syft SBOM (manifest-based baseline from go.mod/go.sum)
3. (no apt deps for Go)
4. Instrumented build: `bomtrace2 -c bomtrace_go.conf go build -a -o <binary> .`
5a. OmniBOR SPDX via bomsh_sbom.py
5b. Metadata collection
5c. Per-binary ADG SPDX + HTML visualization
6. SPDX validation (JSON Schema + semantic)
7. Collect output binaries
8. Write docs

See: https://github.com/omnibor/bomsh#software-vulnerability-cve-search-for-golang-packages

## Rust Pipeline Sequence

Rust repos use **bomtrace2** with the default `bomtrace.conf` — no special config
needed. `bomsh_hook2.py` has a dedicated `get_all_subfiles_in_rustc_cmdline()`
function that parses `rustc` command lines. Rust statically links all crate
dependencies, so all crates get STATIC_LINK relationships.

1. Clone target repo into `repos/<name>/`
2. Syft SBOM (manifest-based baseline from Cargo.toml/Cargo.lock)
3. (no apt deps for Rust)
4. Instrumented build: `bomtrace2 cargo build --release`
5a. OmniBOR SPDX via bomsh_sbom.py
5b. Metadata collection
5c. Per-binary ADG SPDX + HTML visualization
6. SPDX validation (JSON Schema + semantic)
7. Binary collection
8. Documentation generation

Crate sources are fetched to `~/.cargo/registry/src/index.crates.io-*/crate-version/`
and detected via regex. Versions come from `Cargo.lock`. PURLs use `pkg:cargo/crate@version`.

See: https://github.com/omnibor/bomsh#software-vulnerability-cve-search-for-rust-packages

## Key Paths Inside Container

| Path | Purpose |
|------|---------|
| `/opt/bomsh/bin/bomtrace3` | Bomtrace3 binary (C/C++) |
| `/opt/bomsh/bin/bomtrace2` | Bomtrace2 binary (Go) |
| `/opt/bomsh/bin/bomtrace_go.conf` | Go-specific bomtrace2 config (watches compile, link + openat) |
| `/opt/bomsh/scripts/` | Bomsh Python scripts |
| `/tmp/bomsh_hook_raw_logfile.sha1` | Raw build log (default location) |
| `/tmp/bomsh_createbom_jsonfile` | Generated hash-tree database |
| `/workspace/app/` | Analysis scripts (analyze.py, spdx_from_adg.py, etc.) |
| `/workspace/output/` | All generated artifacts |

## Important Notes

- Only the final `make` step should be instrumented — configure/autoreconf are not builds
- bomtrace3 does NOT need bomsh_hook2.py — it has the functionality built in as C code
- ADG output defaults to `${PWD}/.omnibor` but we redirect to `output/omnibor/<lang>/<repo>/` via `-b` flag
- SPDX v2.3 is the supported version
- `vendored_dirs` in config.yaml allows per-repo vendored directory patterns
- `direct_only` mode prevents duplicate deps when a project has both executables and shared libs
