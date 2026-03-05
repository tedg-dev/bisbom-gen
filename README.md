# OmniBOR Analysis

> SBOM accuracy and consistency comparison using [OmniBOR](https://omnibor.io/) build interception vs. proprietary binary scanning.

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

This project instruments C/C++ and Go open-source builds with [OmniBOR/Bomsh](https://github.com/omnibor/bomsh) to generate SPDX SBOMs via **build interception**, then compares those SBOMs against SBOMs produced by proprietary binary scanning tools (e.g., BDBA) to evaluate:

- **Accuracy** — Are the detected components correct?
- **Completeness** — Are all components found?
- **Consistency** — Do both methods agree on versions and identifiers?

## Background

### What is Build Interception?

Build interception hooks into the compiler and linker during a software build to observe exactly which source files are compiled into which output artifacts. [OmniBOR's Bomtrace](https://github.com/omnibor/bomsh) uses `strace` to intercept these calls and produce an **Artifact Dependency Graph (ADG)** — a cryptographically verifiable record of what was built from what. C/C++ builds use bomtrace3; Go builds use bomtrace2 with a Go-specific configuration (see [Go Language Support](docs/go-language-support.md)).

### Why Compare Against Binary Scanning?

Binary scanning tools analyze compiled binaries using signature databases to identify known open-source components. By comparing build interception SBOMs against binary scan SBOMs, we can understand the strengths and blind spots of each approach and determine the most effective strategy for comprehensive SBOM generation.

## Project Structure

```
omnibor-analysis/
├── docker/                 Docker environment (Linux + gcc + Go + bomtrace)
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── bomtrace_go.conf    Go-specific bomtrace2 configuration
│   ├── patches/            Upstream bomsh patches
│   └── README.md
├── repos/                  Cloned target repositories (not tracked in git)
├── output/                 Raw SBOM and ADG artifacts (not tracked in git)
│   ├── omnibor/            ADG documents from bomsh
│   ├── spdx/               SPDX SBOMs (OmniBOR + Syft)
│   └── binary-scan/        SBOMs from proprietary binary scanner
├── docs/                   Timestamped results and reports
│   ├── c-cpp/<repo>/<ts>/  C/C++ per-repo build logs
│   ├── go/<repo>/<ts>/     Go per-repo build logs
│   ├── runtime/            Build time and performance metrics
│   ├── go-language-support.md  Comprehensive Go support documentation
│   ├── upstream-changes.md     Tracking upstream bomsh fixes
│   └── summary/            Cross-repo findings and methodology
├── app/                    Orchestration scripts and configuration
│   ├── analyze.py          Clone, build, instrument, generate SBOMs
│   ├── compare.py          Diff OmniBOR SPDX vs binary-scan SPDX
│   ├── config.yaml         Repo definitions, build commands, paths
│   └── templates/          Report templates
├── .github/                GitHub templates and CI configuration
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── ISSUE_TEMPLATE/
├── CONTRIBUTING.md         Contribution guidelines
├── LICENSE                 License file
└── README.md               This file
```

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| **Docker Desktop** | Latest | Required — bomtrace3 runs on Linux only (uses strace) |
| **Python** | 3.11+ | For orchestration scripts |
| **Git** | 2.x+ | For cloning target repositories |
| **Binary scanner** | — | Optional — BDBA or equivalent for comparison SBOMs |

> **Note:** All C/C++ compilation and OmniBOR instrumentation happens inside the Docker container. You do **not** need gcc, clang, or any build tools installed on your host machine.

## Getting Started

### 1. Clone this repository

```bash
git clone https://github.com/tedg-cisco/omnibor-analysis.git
cd omnibor-analysis
```

### 2. Build the Docker environment

```bash
docker-compose -f docker/docker-compose.yml build
```

This builds an Ubuntu 22.04 container with:
- gcc, clang, make, cmake, autoconf
- Go SDK (latest)
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

### Compare SBOMs

After running analysis and placing a binary scanner SPDX file in `output/binary-scan/<repo>/`:

```bash
# Auto-detect latest files
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/compare.py --repo curl

# Or specify files explicitly
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/compare.py --repo curl \
    --omnibor-file /workspace/output/spdx/curl/curl_omnibor_2026-02-10_1430.spdx.json \
    --binary-file /workspace/output/binary-scan/curl/bdba_export.spdx.json
```

### Interactive container access

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env bash
```

## Target Repositories

### C/C++ (bomtrace3)

| Repo | Dependencies | Build System | Purpose |
|------|-------------|-------------|----------|
| [curl](https://github.com/curl/curl) | OpenSSL, zlib, nghttp2, libssh2, brotli, zstd, c-ares, libidn2 | autoconf/make | Controlled medium-size comparison |
| [redis](https://github.com/redis/redis) | 8 vendored static libs | make | Vendored library detection |
| [FFmpeg](https://github.com/FFmpeg/FFmpeg) | libx264, libx265, libvpx, libopus, OpenSSL, zlib, 20+ more | autoconf/make | Large-scale dependency-rich comparison |
| [nmap](https://github.com/nmap/nmap) | 7 vendored + 14 dynamic | autoconf/make | Mixed vendored + system deps |

### Go (bomtrace2)

| Repo | Direct deps | Indirect deps | Purpose |
|------|-------------|---------------|----------|
| [lazygit](https://github.com/jesseduffield/lazygit) | 33 | 29 | First Go target, rich dependency graph |

For details on Go support, see [Go Language Support](docs/go-language-support.md).

To add a new target repository, see [CONTRIBUTING.md](CONTRIBUTING.md#adding-a-new-target-repository).

## Output and Reports

### SPDX Output Files (per binary)

Each analysis run produces three SPDX files:

| File | Purpose |
|------|----------|
| `<binary>_adg.spdx.json` | **Primary output.** Full dependency graph from build interception (DEPENDS_ON, STATIC_LINK, DYNAMIC_LINK, BUILD_TOOL_OF). |
| `<binary>_omnibor.spdx.json` | OmniBOR artifact identity. Lists cryptographic hashes for provenance tracking. No dependency relationships (by design). |
| `<binary>_syft.spdx.json` | Syft baseline. Manifest-based SBOM for comparison. |

Each `.spdx.json` has a corresponding `.spdx.html` interactive D3.js visualization.

### Artifacts (not tracked in git)

| Path | Contents |
|------|----------|
| `output/omnibor/{lang}/{repo}/{ts}/` | OmniBOR ADG documents from bomsh |
| `output/spdx/{lang}/{repo}/{ts}/` | SPDX SBOM files + HTML visualizations |
| `output/binaries/{lang}/{repo}/{ts}/` | Collected output binaries |
| `output/binary-scan/{lang}/{repo}/` | SBOMs from proprietary binary scanner |

### Reports (tracked in git)

| Path | Contents |
|------|----------|
| `docs/{lang}/{repo}/{ts}/build.md` | Build log, environment snapshot |
| `docs/runtime/{lang}/{repo}/{ts}/runtime.md` | Build time and performance metrics |
| `docs/summary/` | Cross-repo findings and methodology |

**Path convention:** `{lang}` is `c-cpp` or `go`. `{ts}` is `YYYY-MM-DD_HHMM`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on:
- Branch naming and PR workflow
- Adding new target repositories
- Code style and testing
- Commit message conventions

## License

TBD — License to be determined.

---

*Built with [OmniBOR/Bomsh](https://github.com/omnibor/bomsh) | [omnibor.io](https://omnibor.io)*
