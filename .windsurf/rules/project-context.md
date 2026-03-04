---
description: Project context and architecture for omnibor-analysis
---

# Project: OmniBOR Analysis

This project instruments open-source builds with OmniBOR/Bomsh (build interception for C/C++)
or Syft (manifest-based for Go) to generate SPDX 2.3 SBOMs with full dependency breakdown
(vendored static libs, dynamic system libs, build tools), then optionally compares those
against SBOMs from proprietary binary scanning tools (e.g., BDBA) to evaluate accuracy
and completeness.

## Directory Structure

- **app/** — Orchestration scripts, SPDX generation, config.yaml
- **docker/** — Linux container environment (Ubuntu 22.04) with gcc, bomtrace3, syft
- **tests/** — Unit tests (349+ tests, 98% coverage)
- **scripts/** — Helper/utility scripts
- **docs/** — Timestamped results and summary documentation, organized by language (`c-cpp/`, `go/`)
- **repos/** — Cloned target repositories (gitignored)
- **output/** — Generated artifacts organized by language: `output/{category}/{lang}/{repo}/{ts}/` (gitignored)
- **.windsurf/** — Cascade AI rules and workflows

## Key Technologies

- **Bomsh/Bomtrace3** — ptrace-based build interception from omnibor/bomsh (Linux x86_64 only, C/C++)
- **OmniBOR** — Artifact Dependency Graph (ADG) standard (omnibor.io)
- **SPDX 2.3** — SBOM format (JSON output)
- **Syft** — Manifest-based SBOM generation (primary for Go, baseline for C/C++)
- **Go SDK** — Go 1.23+ installed in the container for building Go targets
- **D3.js** — Interactive HTML dependency graph visualization
- **Docker** — Required because bomtrace3 uses Linux ptrace (not available on macOS/Windows)

## Analysis Pipeline (analyze.py)

### C/C++ repos (full OmniBOR instrumentation)
1. Clone target repo
2. Syft baseline SBOM (manifest-based)
3. Validate apt dependencies
4. Instrumented build with bomtrace3
5a. OmniBOR SPDX via bomsh_sbom.py
5b. Metadata collection (collect_metadata.py + collect_dynamic_libs.py)
5c. Per-binary ADG SPDX with vendored detection + HTML visualization
6. SPDX validation (JSON Schema + semantic)
7. Binary collection
8. Documentation generation

### Go repos (Syft-primary, plain build)
1. Clone target repo
2. Syft SBOM (primary — parses go.mod/go.sum)
4. Plain build via PlainBuilder (no bomtrace3)
6. SPDX validation
7. Binary collection
8. Documentation generation

Steps 3, 5a-5c are skipped for Go because bomtrace3 does not intercept `go build`.

## Key Application Files

| File | Purpose |
|------|---------|
| `app/analyze.py` | Main pipeline orchestrator (AnalysisPipeline facade) |
| `app/spdx_from_adg.py` | Per-binary SPDX from ADG: vendored detection, version extraction |
| `app/spdx_visualize.py` | D3.js HTML dependency graph generator |
| `app/collect_metadata.py` | Resolve system files to dpkg packages |
| `app/collect_dynamic_libs.py` | Per-binary ldd/readelf dynamic lib analysis |
| `app/compare.py` | Compare OmniBOR SBOM vs binary scanner SBOM |
| `app/add_repo.py` | Auto-discover and add new target repos from GitHub |
| `app/data_loader.py` | Shared data loading utilities |
| `app/config.yaml` | Single source of truth: repos, build steps, tool paths |

## Target Repositories

### C/C++ (`language: c-cpp`)

| Repo | Binaries | Vendored | Dynamic | Build Time |
|------|----------|----------|---------|------------|
| curl | curl, libcurl.so | — (/deps/) | ~10 | ~5 min |
| redis | redis-server | 8 libs | ~5 | ~3 min |
| ffmpeg | 6 bins/libs | — | 20+ | ~24 min |
| nmap | nmap, ncat, nping | 7 libs | 14 | ~3.3 min |

### Go (`language: go`)

| Repo | Binary | Direct deps | Indirect deps |
|------|--------|-------------|---------------|
| fzf | fzf | ~7 | ~4 |
| lazygit | lazygit | ~15-20 | ~20-30 |
| croc | croc | ~10-15 | ~15 |
| dive | dive | ~15-20 | ~25 |
| gdu | gdu | ~10-15 | ~15-20 |

## Important Constraints

- All builds run inside the Docker container on a Linux x86_64 host, never on macOS
- The container requires `SYS_PTRACE` capability and `seccomp:unconfined` for ptrace
- repos/ and output/ are gitignored — only docs/, app/, tests/, docker/ are tracked
- config.yaml is the single source of truth for repo URLs, build commands, language, and paths
- Each repo has a `language` field (`c-cpp`, `go`) that determines its output subfolder
- Go repos use `PlainBuilder` (no bomtrace3) and Syft as the primary SBOM generator
- C/C++ repos use `BomtraceBuilder` (bomtrace3 instrumentation) and bomsh for OmniBOR SBOMs
- Per-file test coverage must be 95%+, overall 97%+ (enforced in pre-commit.md)
