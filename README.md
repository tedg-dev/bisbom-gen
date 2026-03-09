# OmniBOR Analysis

> SPDX SBOM generation via [OmniBOR](https://omnibor.io/) build interception for C/C++ and Rust projects.

[![License](https://img.shields.io/badge/license-TBD-lightgrey.svg)](#license)

## Table of Contents

- [Overview](#overview)
- [Background](#background)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
- [Usage](#usage)
- [Target Repositories](#target-repositories)
- [Output and Reports](#output-and-reports)
- [Contributing](#contributing)
- [License](#license)

## Overview

This project instruments C/C++ and Rust open-source builds with [OmniBOR/Bomsh](https://github.com/omnibor/bomsh) to generate **SPDX 2.3 SBOMs** via build interception. For each compiled binary, it produces a full dependency graph capturing:

- **Static dependencies** (STATIC_LINK) — vendored libraries compiled into the binary
- **Dynamic dependencies** (DYNAMIC_LINK) — system shared libraries resolved via ldd/readelf
- **Transitive dependencies** (DEPENDS_ON) — indirect dependencies from lock files
- **Build tools** (BUILD_TOOL_OF) — compiler/linker version tracking
- **Interactive HTML visualizations** — D3.js force-directed dependency graphs

## Background

### What is Build Interception?

Build interception hooks into the compiler and linker during a software build to observe exactly which source files are compiled into which output artifacts. [OmniBOR's Bomtrace](https://github.com/omnibor/bomsh) uses `strace` to intercept these calls and produce an **Artifact Dependency Graph (ADG)** — a cryptographically verifiable record of what was built from what. C/C++ builds use bomtrace3; Rust builds use bomtrace2 with default configuration. Go support is experimental (see [Go Language Support](docs/go-language-support.md)).

## Project Structure

```
omnibor-analysis/
├── docker/                 Docker environment (Linux + gcc + Rust + Go + bomtrace)
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── bomtrace_go.conf    Go-specific bomtrace2 configuration
│   ├── patches/            Upstream bomsh patches
│   └── README.md
├── repos/                  Cloned target repositories (not tracked in git)
├── output/                 Raw SBOM and ADG artifacts (not tracked in git)
│   ├── omnibor/{lang}/{repo}/{ts}/  ADG documents from bomsh
│   ├── spdx/{lang}/{repo}/{ts}/     SPDX SBOMs + HTML visualizations
│   ├── binaries/{lang}/{repo}/{ts}/ Collected output binaries
├── docs/                   Timestamped results and reports
│   ├── {lang}/{repo}/{ts}/     Per-repo build logs
│   ├── runtime/{lang}/{repo}/{ts}/  Build time and performance metrics
│   ├── go-language-support.md  Go support documentation (experimental)
│   ├── upstream-changes.md     Tracking upstream bomsh fixes
│   └── summary/            Cross-repo findings and methodology
├── app/                    Orchestration scripts and configuration
│   ├── analyze.py          Clone, build, instrument, generate SBOMs
│   ├── spdx_from_adg.py    Per-binary SPDX from ADG with vendored detection
│   ├── spdx_visualize.py   D3.js interactive HTML dependency graph generator
│   ├── collect_metadata.py Resolve system files to dpkg packages
│   ├── collect_dynamic_libs.py  Per-binary ldd/readelf dynamic lib analysis
│   ├── add_repo.py         Auto-discover and add repos from GitHub
│   ├── data_loader.py      Shared data loading utilities
│   ├── config.yaml         Repo definitions, build commands, paths
│   └── templates/          Report templates
├── terraform/              AWS EC2 infrastructure as code
├── tests/                  Unit tests (427 tests, 99% coverage)
├── .windsurf/              Cascade AI rules and workflows
├── .github/                GitHub templates and CI configuration
├── LICENSE                 License file
└── README.md               This file
```

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| **Docker Desktop** | Latest | Required — bomtrace3 runs on Linux only (uses strace) |
| **Python** | 3.11+ | For orchestration scripts |
| **Git** | 2.x+ | For cloning target repositories |

> **Note:** All C/C++ compilation and OmniBOR instrumentation happens inside the Docker container. You do **not** need gcc, clang, or any build tools installed on your host machine.

## Getting Started

### 1. Clone this repository

```bash
git clone https://github.com/tedg-dev/omnibor-analysis.git
cd omnibor-analysis
```

### 2. Build the Docker environment

```bash
docker-compose -f docker/docker-compose.yml build
```

This builds an Ubuntu 22.04 container with:
- gcc, clang, make, cmake, autoconf
- Rust toolchain (rustup + stable)
- Go SDK 1.26.0
- bomtrace2 and bomtrace3 (compiled from [omnibor/bomsh](https://github.com/omnibor/bomsh))
- [Syft](https://github.com/anchore/syft) for manifest-based SBOM generation
- All build dependencies for target repositories

First build takes **10-20 minutes** (compiles bomtrace from patched strace source). Subsequent builds use Docker layer cache.

### 3. Verify the environment

```bash
# Check bomtrace3
docker-compose -f docker/docker-compose.yml run --rm omnibor-env bomtrace3 --version

# Check syft
docker-compose -f docker/docker-compose.yml run --rm omnibor-env syft version
```

## Usage

### Run analysis on a target repository

```bash
# List available repos
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --list

# Full analysis: clone → build → instrument → generate SBOMs → write docs
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo curl

# Re-run without cloning (repo already exists)
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo curl --skip-clone

# Syft-only mode (manifest SBOM, no build instrumentation)
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo curl --syft-only
```

### Interactive container access

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env bash
```

## Target Repositories

### C/C++ (bomtrace3)

| Repo | Dependencies | Build System | Purpose |
|------|-------------|-------------|----------|
| [curl](https://github.com/curl/curl) | OpenSSL, zlib, nghttp2, libssh2, brotli, zstd, c-ares, libidn2 | autoconf/make | Medium-size, many dynamic deps |
| [redis](https://github.com/redis/redis) | 8 vendored static libs | make | Vendored library detection |
| [FFmpeg](https://github.com/FFmpeg/FFmpeg) | libx264, libx265, libvpx, libopus, OpenSSL, zlib, 20+ more | autoconf/make | Large-scale, 20+ third-party libs |
| [nmap](https://github.com/nmap/nmap) | 7 vendored + 14 dynamic | autoconf/make | Mixed vendored + system deps |

### Rust (bomtrace2)

| Repo | Direct crates (STATIC_LINK) | Transitive crates (DEPENDS_ON) | Dynamic libs | Purpose |
|------|-----------------------------|-------------------------------|--------------|----------|
| [oxipng](https://github.com/oxipng/oxipng) | 11 | 33 | 2 | First Rust target, PNG optimizer |
| [dura](https://github.com/tkellogg/dura) | 108 | 77 | 4 | Complex git2-rs binding layer depth |

Rust crates are classified as direct (from `Cargo.toml` → STATIC_LINK) or transitive (from `Cargo.lock` only → DEPENDS_ON). Each crate gets a `pkg:cargo` PURL with the version from `Cargo.lock`.

### Go (bomtrace2) — Experimental

Go build interception is functional but does not yet provide efficient build-time dependency details. Go support is TBD for production use.

| Repo | Direct deps | Indirect deps | Purpose |
|------|-------------|---------------|----------|
| [lazygit](https://github.com/jesseduffield/lazygit) | 33 | 29 | Rich Go dependency graph |
| [pocketbase](https://github.com/pocketbase/pocketbase) | ~20 | ~15 | Go backend framework |

For details on Go support, see [Go Language Support](docs/go-language-support.md).

To add a new target repository, see [CONTRIBUTING.md](docs/CONTRIBUTING.md#adding-a-new-target-repository).

## Output and Reports

### SPDX Output Files (per binary)

Each analysis run produces three SPDX files:

| File | Purpose |
|------|----------|
| `<binary>_adg.spdx.json` | **Primary output.** Full dependency graph from build interception (DEPENDS_ON, STATIC_LINK, DYNAMIC_LINK, BUILD_TOOL_OF). |
| `<binary>_omnibor.spdx.json` | OmniBOR artifact identity. Lists cryptographic hashes for provenance tracking. No dependency relationships (by design). |
| `<binary>_syft.spdx.json` | Syft manifest-based SBOM (package manager metadata). |

Each `.spdx.json` has a corresponding `.spdx.html` interactive D3.js visualization.

### Artifacts (not tracked in git)

| Path | Contents |
|------|----------|
| `output/omnibor/{lang}/{repo}/{ts}/` | OmniBOR ADG documents from bomsh |
| `output/spdx/{lang}/{repo}/{ts}/` | SPDX SBOM files + HTML visualizations |
| `output/binaries/{lang}/{repo}/{ts}/` | Collected output binaries |

### Reports (tracked in git)

| Path | Contents |
|------|----------|
| `docs/{lang}/{repo}/{ts}/build.md` | Build log, environment snapshot |
| `docs/runtime/{lang}/{repo}/{ts}/runtime.md` | Build time and performance metrics |
| `docs/summary/` | Cross-repo findings and methodology |

**Path convention:** `{lang}` is `c-cpp`, `rust`, or `go`. `{ts}` is `YYYY-MM-DD_HHMM`.

## Contributing

See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for guidelines on:
- Branch naming and PR workflow
- Adding new target repositories
- Code style and testing
- Commit message conventions

## License

TBD — License to be determined.

---

*Built with [OmniBOR/Bomsh](https://github.com/omnibor/bomsh) | [omnibor.io](https://omnibor.io)*
