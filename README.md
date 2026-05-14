# OmniBOR Analysis

> SPDX SBOM generation via [OmniBOR](https://omnibor.io/) build interception for C/C++, Rust, Go, and Java projects.

[![License](https://img.shields.io/badge/license-TBD-lightgrey.svg)](#license)

## Table of Contents

- [Overview](#overview)
- [Documentation](#documentation)
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

This project instruments C/C++, Rust, Go, and Java open-source builds with [OmniBOR/Bomsh](https://github.com/omnibor/bomsh) to generate **SPDX 2.3 SBOMs** via build interception. For each compiled binary, it produces a full dependency graph capturing:

- **Static dependencies** (STATIC_LINK) — vendored libraries compiled into the binary
- **Dynamic dependencies** (DYNAMIC_LINK) — system shared libraries resolved via ldd/readelf
- **Transitive dependencies** (DEPENDS_ON) — indirect dependencies from lock files
- **Build tools** (BUILD_TOOL_OF) — compiler/linker version tracking
- **Interactive HTML visualizations** — D3.js force-directed dependency graphs

## Documentation

For detailed documentation, see the [`docs/`](docs/) directory:

| Directory | Contents |
|-----------|----------|
| **[`docs/guides/`](docs/guides/)** | **Start here.** Onboarding, contributing, AWS setup |
| [`docs/architecture/`](docs/architecture/) | System diagrams, build interception flow, technical overview |
| [`docs/features/`](docs/features/) | Feature documentation (Go support, stable tag pinning, etc.) |
| [`docs/issues/`](docs/issues/) | Upstream bomsh/bomtrace bug reports and workarounds |
| [`docs/deep-dive/`](docs/deep-dive/) | Research, performance analysis, optimization proposals |

## Background

### What is Build Interception?

Build interception hooks into the compiler and linker during a software build to observe exactly which source files are compiled into which output artifacts. [OmniBOR's Bomtrace](https://github.com/omnibor/bomsh) uses `strace` to intercept these calls and produce an **Artifact Dependency Graph (ADG)** — a cryptographically verifiable record of what was built from what. C/C++ builds use bomtrace3; Rust and Go builds use bomtrace2. Java uses strace-based post-build analysis. See [Go Language Support](docs/features/go-language-support.md), [Analyzed vs Build SBOMs](docs/features/analyzed-vs-build-sboms.md), and [Stable Tag Pinning](docs/features/stable-tag-pinning.md) for details.

## Project Structure

```
omnibor-analysis/
├── app/                    Orchestration scripts and modular packages
│   ├── pipeline/           Analysis pipeline (clone, build, instrument, generate SBOMs)
│   ├── spdx/              Per-binary SPDX 2.3 generation from ADG data
│   ├── viz/               D3.js visualization package (extract, styles, JS templates)
│   ├── version_detection/ Root + vendored package version detection (14 strategies)
│   ├── repo_discovery/    Auto-discover and configure repos from GitHub
│   └── templates/         Report templates
├── docker/                Docker environment (Linux + gcc + Rust + Go + Maven + bomtrace)
├── docs/                  Documentation (hand-written only, no generated files)
│   ├── guides/            Onboarding, contributing, AWS setup
│   ├── architecture/      System design, diagrams, pipeline overview
│   ├── features/          Feature documentation
│   ├── issues/            Upstream bug tracking and workarounds
│   └── deep-dive/         Research, performance, enterprise docs
├── terraform/             AWS EC2 infrastructure as code
├── tests/                 Unit tests (1310 tests, 98% coverage)
├── repos/                 Cloned target repositories (gitignored)
├── output/                Generated artifacts: SBOMs, ADGs, binaries (gitignored)
├── .windsurf/             Cascade AI rules and workflows
└── .github/               GitHub templates and CI configuration
```

> See [`app/README.md`](app/README.md) for detailed module documentation.

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
- [Syft](https://github.com/anchore/syft) (used internally by bomsh_sbom.py for baseline SPDX scaffolding)
- All build dependencies for target repositories

First build takes **10-20 minutes** (compiles bomtrace from patched strace source). Subsequent builds use Docker layer cache.

### 3. Verify the environment

```bash
# Check bomtrace3
docker-compose -f docker/docker-compose.yml run --rm omnibor-env bomtrace3 --version

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
| [Node.js](https://github.com/nodejs/node) | V8, libuv, OpenSSL, zlib, nghttp2, 20 vendored | ./configure + make | Massive vendored tree (~4M LoC) |
| [OpenOSC](https://github.com/cisco/OpenOSC) | Minimal (libc only) | autoconf/make | Small C library, minimal deps |

### Rust (bomtrace2)

| Repo | Crates (STATIC_LINK) | Dynamic libs | Purpose |
|------|---------------------|--------------|----------|
| [oxipng](https://github.com/oxipng/oxipng) | 44 | 2 | First Rust target, PNG optimizer |
| [dura](https://github.com/tkellogg/dura) | 92 | 4 | Complex git2-rs binding layer depth |

All Rust crates use STATIC_LINK (compiled into the binary). Each crate gets a `pkg:cargo` PURL with the version from `Cargo.lock`.

### Go (bomtrace2)

| Repo | Direct deps | Indirect deps | Purpose |
|------|-------------|---------------|----------|
| [fzf](https://github.com/junegunn/fzf) | 7 | 4 | Small Go project, fuzzy finder |
| [lazygit](https://github.com/jesseduffield/lazygit) | 33 | 29 | Rich Go dependency graph |
| [pocketbase](https://github.com/pocketbase/pocketbase) | ~50 | ~100 | Backend with SQLite, REST API, auth |
| [croc](https://github.com/schollz/croc) | ~10-15 | ~15 | Secure file transfer |
| [dive](https://github.com/wagoodman/dive) | ~15-20 | ~25 | Docker image explorer |
| [gdu](https://github.com/dundee/gdu) | ~10-15 | ~15-20 | Disk usage analyzer |

Go modules are classified as direct or indirect from `go.mod`. Each gets a `pkg:golang` PURL. For details, see [Go Language Support](docs/features/go-language-support.md).

### Java (strace + post-build analysis)

| Repo | Direct deps | Transitive deps | Purpose |
|------|-------------|-----------------|----------|
| [checkstyle](https://github.com/checkstyle/checkstyle) | 10 | 21 | Static analysis, deep Maven tree |
| [jsoup](https://github.com/jhy/jsoup) | 0 | 0 | HTML parser, zero runtime deps |
| [crawler4j](https://github.com/yasserg/crawler4j) | 6 | 16 | Web crawler, Apache HttpComponents |
| [dependency-check](https://github.com/jeremylong/DependencyCheck) | ~20 | ~80 | OWASP vulnerability scanner, Maven multi-module |
| [logging-log4j2](https://github.com/apache/logging-log4j2) | ~10 | ~20 | Apache Log4j2 logging framework, Maven multi-module |
| [spring-boot](https://github.com/spring-projects/spring-boot) | ~50 | ~70 | Spring Boot framework, Gradle multi-module |
| [bc-java](https://github.com/bcgit/bc-java) | ~10 | ~5 | Bouncy Castle crypto library, Gradle multi-module |

Java uses strace-based post-build analysis instead of bomtrace. Maven dependencies are classified as direct (depth 1) or transitive (depth 2+) via BFS.

To add a new target repository, see [CONTRIBUTING.md](docs/guides/CONTRIBUTING.md#adding-a-new-target-repository).

## Output and Reports

### SPDX Output Files (per binary)

Each analysis run produces SPDX files per output binary:

| File | CISA Type | Purpose |
|------|-----------|----------|
| `<binary>_analyzed.spdx.json` | Analyzed | Components compiled into the binary (STATIC_LINK only). For vulnerability scanning and license compliance. |
| `<binary>_build.spdx.json` | Build | Full dependency graph: static + dynamic + build tools + transitive deps. For build reproducibility and supply chain audit. |
| `<binary>_omnibor.spdx.json` | — | OmniBOR artifact identity. Cryptographic hashes for provenance tracking. No dependency relationships (by design). |

Each `.spdx.json` has a corresponding `.spdx.html` interactive D3.js visualization. See [Analyzed vs Build SBOMs](docs/features/analyzed-vs-build-sboms.md) for the rationale behind the two-file approach.

### Artifacts (not tracked in git)

| Path | Contents |
|------|----------|
| `output/omnibor/{lang}/{repo}/{ts}/` | OmniBOR ADG documents from bomsh |
| `output/spdx/{lang}/{repo}/{ts}/` | SPDX SBOM files + HTML visualizations |
| `output/binaries/{lang}/{repo}/{ts}/` | Collected output binaries |

### Reports (gitignored, regenerated per run)

| Path | Contents |
|------|----------|
| `output/build-logs/{lang}/{repo}/{ts}/build.md` | Build log, environment snapshot |

**Path convention:** `{lang}` is `c-cpp`, `rust`, `go`, or `java`. `{ts}` is `YYYY-MM-DD_HHMM`.

## Runtime Performance

Wall-clock times on EC2 `c6i.xlarge` (4 vCPU, 8 GB). **Capture** is the instrumented build (bomtrace + compilation). **SPDX** is post-build analysis (OmniBOR ADG, SPDX generation, validation, binary collection).

### C/C++ (bomtrace3 + strace)

| Repo | Capture | SPDX | Total |
|------|--------:|-----:|------:|
| curl | 72s | 12s | 84s |
| redis | 31s | 12s | 43s |
| nmap | 51s | 19s | 69s |
| FFmpeg | 741s | 123s | 864s |

### Rust (bomtrace2)

| Repo | Capture | SPDX | Total |
|------|--------:|-----:|------:|
| oxipng | 40s | 6s | 45s |
| dura | 177s | 15s | 192s |

### Go (bomtrace2)

| Repo | Capture | SPDX | Total |
|------|--------:|-----:|------:|
| fzf | 47s | 21s | 69s |
| lazygit | 120s | 42s | 161s |

### Java (strace)

| Repo | Capture | SPDX | Total |
|------|--------:|-----:|------:|
| jsoup | 34s | 7s | 42s |
| checkstyle | 73s | 19s | 92s |

> SPDX generation is typically 10–20% of total wall time. The majority is spent in the instrumented build itself.

## Contributing

See [CONTRIBUTING.md](docs/guides/CONTRIBUTING.md) for guidelines on:
- Branch naming and PR workflow
- Adding new target repositories
- Code style and testing
- Commit message conventions

## License

TBD — License to be determined.

---

*Built with [OmniBOR/Bomsh](https://github.com/omnibor/bomsh) | [omnibor.io](https://omnibor.io)*
