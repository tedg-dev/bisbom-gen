# OmniBOR Analysis — Workflow Guide

This guide explains the three core workflows, when to use them, and recommended practices.

## Overview

| Workflow | Purpose | When to Use |
|----------|---------|-------------|
| `/add-repo` | Register a new C/C++ project for analysis | Once per target project |
| `/run-analysis` | Build-intercept a repo and generate SBOMs | Each time you want a fresh SBOM |
| `/run-comparison` | Compare OmniBOR SBOM vs binary scanner SBOM | After analysis + binary scan import |

## Recommended Order

```
1. /add-repo        →  define the target (one-time setup)
2. /docker-build    →  rebuild image if new deps were added
3. /run-analysis    →  instrument the build, produce SBOMs
4. /run-comparison  →  compare against proprietary scan results
```

---

## `/add-repo` — Add a New Target Repository

Registers a new C/C++ project so the analysis pipeline knows how to clone, configure, and build it. Uses `app/add_repo.py` to **auto-discover** repo metadata from GitHub.

### Usage

Just provide a repo name — the script handles everything else:

```bash
# Dry-run (preview only, default)
source .venv/bin/activate && python3 app/add_repo.py curl

# Write to config.yaml + create output dirs
source .venv/bin/activate && python3 app/add_repo.py openssl --write
```

Accepts: repo name (`curl`), owner/repo (`curl/curl`), or full GitHub URL.

### What the script auto-discovers

1. **Canonical GitHub repo** — searches by name, prefers C/C++ repos and exact matches
2. **Build system** — detects autoconf, cmake, meson, or plain make from file presence
3. **Configure flags** — analyzes `configure.ac` or `CMakeLists.txt` for known dependencies
4. **Output binaries** — parses `Makefile.am` for `bin_PROGRAMS` and `lib_LTLIBRARIES`
5. **Dockerfile packages** — cross-checks required `-dev` packages against what's already installed
6. **Description + stats** — pulls GitHub description and language/LoC estimates

### Key rules

- **Last `build_steps` entry must be the `make` command** — `analyze.py` wraps only the final step with `bomtrace3`
- All steps before `make` run uninstrumented (configure, autoreconf, cmake)
- `output_binaries` is used for targeted ADG extraction — list the main executables and shared libs
- If the auto-detection is wrong, edit `app/config.yaml` directly after `--write`

### Currently configured repos

| Repo | Description | Build System | Build Time |
|------|-------------|--------------|------------|
| `curl` | HTTP transfer library and CLI (~170K LoC) | autoconf + make | ~5 min |
| `redis` | In-memory data store with 8 vendored libs | plain make | ~3 min |
| `ffmpeg` | Multimedia framework (~1.2M LoC, 20+ third-party libs) | custom configure + make | ~24 min |
| `nmap` | Network scanner with 7 vendored libs + 14 dynamic | autoconf + make | ~3.3 min |

### Recommendations

- **Start with curl or nmap** — they build fast and produce rich SBOMs with both vendored and dynamic deps
- **Test manually first** — enter the container with `docker-compose run --rm omnibor-env bash`, clone the repo, and verify the build works before running `analyze.py`
- **Review before writing** — always run without `--write` first to verify the generated config

---

## `/run-analysis` — Run Build Interception Analysis

Instruments a C/C++ build with `bomtrace3` to capture every compiler/linker invocation, then generates OmniBOR Artifact Dependency Graphs (ADG) and SPDX SBOMs.

### What it does (7 steps)

1. **Clone** — shallow clone of the target repo into `repos/<name>/`
2. **Dependency check** — validates that required apt packages are installed
3. **Instrumented build** — runs `bomtrace3 make` to intercept all compiler/linker calls, then `bomsh_create_bom.py` processes the raw logfile into OmniBOR ADG
4. **OmniBOR SPDX** — `bomsh_sbom.py` creates SPDX SBOM from ADG with OmniBOR ExternalRef
5. **Metadata + dynamic libs** — `collect_metadata.py` resolves system files to dpkg packages; `collect_dynamic_libs.py` identifies per-binary dynamic dependencies via ldd/readelf
6. **Per-binary ADG SPDX** — `spdx_from_adg.py` generates one SPDX per output binary with vendored (`STATIC_LINK`), dynamic (`DYNAMIC_LINK`), and build tool breakdown + interactive HTML visualization
7. **Validation + docs** — JSON Schema + semantic validation of all SPDX files, binary collection, timestamped build log and runtime metrics

### Commands

```bash
# Full analysis (clone + build + SBOM)
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo curl

# Skip clone (repo already in repos/)
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo curl --skip-clone

# List available repos
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --list
```

### Output locations

| Artifact | Path |
|----------|------|
| OmniBOR ADG | `output/omnibor/<repo>/` |
| Component metadata | `output/omnibor/<repo>/metadata/component_metadata.json` |
| Dynamic libs (per binary) | `output/omnibor/<repo>/metadata/<binary>/dynamic_libs.json` |
| SPDX SBOM (OmniBOR) | `output/spdx/<repo>/<repo>_omnibor_<timestamp>.spdx.json` |
| ADG SPDX (per binary) | `output/spdx/<repo>/<binary>_adg.spdx.json` |
| Visualization (per binary) | `output/spdx/<repo>/<binary>_adg.spdx.html` |
| Build log | `docs/<repo>/<timestamp>_build.md` |
| Runtime metrics | `docs/runtime/<timestamp>_<repo>_runtime.md` |

### Recommendations

- **Use `--skip-clone` for re-runs** — avoids re-downloading the repo each time
- **Check build logs** — if the SBOM looks incomplete, review `docs/<repo>/<timestamp>_build.md` for build warnings or missing deps
- **Review SPDX output** — the primary output is `<binary>_adg.spdx.json` with full build-time dependency data
- **Build times** — curl ~5 min, FFmpeg ~20+ min (under QEMU on Apple Silicon, roughly double)

---

## `/run-comparison` — Compare OmniBOR vs Binary Scan SBOMs

Compares an OmniBOR-generated SPDX SBOM against a proprietary binary scanner's SPDX SBOM (e.g., from Black Duck BDBA, Snyk, etc.).

### What it does

1. Reads both SPDX JSON files
2. Matches packages by name (normalized)
3. Produces a markdown report with overlap analysis, version mismatches, and method-specific findings

### Prerequisites

- Run `/run-analysis` first to generate the OmniBOR SBOM
- Place the binary scanner's SPDX export in `output/binary-scan/<repo>/`

### Commands

```bash
# Auto-detect latest files
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/compare.py --repo curl

# Specify files explicitly
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/compare.py \
    --repo curl \
    --omnibor-file /workspace/output/spdx/curl/curl_omnibor_2026-02-10_1430.spdx.json \
    --binary-file /workspace/output/binary-scan/curl/bdba_export.spdx.json
```

### Report contents (`docs/<repo>/<timestamp>_comparison.md`)

- **Summary table** — package counts, overlap percentage, version agreement
- **Common packages** — detected by both methods, with version match/mismatch
- **OmniBOR only** — build-time dependencies not found by binary scanner
- **Binary scan only** — pre-compiled/commercial components not seen during build
- **Version mismatches** — same package, different version detected
- **Analysis notes** — strengths of each method

### Interpreting results

| Finding | Meaning |
|---------|---------|
| High OmniBOR-only count | Build interception sees transitive/header-only deps binary scanner misses |
| High binary-only count | Pre-compiled SDKs, static libs, or vendor binaries not compiled from source |
| Version mismatches | Different detection methods resolve versions differently |
| High overlap + version agreement | Both methods are consistent — high confidence in SBOM accuracy |

### Recommendations

- **Binary scanner export format** — must be SPDX 2.3 JSON. If your scanner exports CycloneDX or CSV, convert to SPDX first
- **Run comparison after every analysis** — comparing OmniBOR build-time SBOMs against binary scan SBOMs is valuable for validating completeness
- **Version mismatches are normal** — binary scanners detect runtime versions while OmniBOR sees source versions

---

## Quick Start (End-to-End Example)

```bash
# 1. Build the Docker environment (one-time, or after Dockerfile changes)
docker-compose -f docker/docker-compose.yml build

# 2. Run analysis on curl
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo curl

# 3. (Optional) Place a binary scan SBOM
cp ~/downloads/bdba_curl.spdx.json output/binary-scan/curl/

# 4. Run comparison
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/compare.py --repo curl

# 5. Review results
ls output/spdx/curl/          # SPDX SBOMs
ls output/omnibor/curl/        # OmniBOR ADG
ls docs/curl/                  # Build logs and comparison reports
```
