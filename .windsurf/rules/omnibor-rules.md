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

## Full Pipeline Sequence

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

## Key Paths Inside Container

| Path | Purpose |
|------|---------|
| `/opt/bomsh/bin/bomtrace3` | Bomtrace3 binary |
| `/opt/bomsh/scripts/` | Bomsh Python scripts |
| `/tmp/bomsh_hook_raw_logfile.sha1` | Raw build log (default location) |
| `/tmp/bomsh_createbom_jsonfile` | Generated hash-tree database |
| `/workspace/app/` | Analysis scripts (analyze.py, spdx_from_adg.py, etc.) |
| `/workspace/output/` | All generated artifacts |

## Important Notes

- Only the final `make` step should be instrumented — configure/autoreconf are not builds
- bomtrace3 does NOT need bomsh_hook2.py — it has the functionality built in as C code
- ADG output defaults to `${PWD}/.omnibor` but we redirect to `output/omnibor/<repo>/` via `-b` flag
- SPDX v2.3 is the supported version
- `vendored_dirs` in config.yaml allows per-repo vendored directory patterns
- `direct_only` mode prevents duplicate deps when a project has both executables and shared libs
