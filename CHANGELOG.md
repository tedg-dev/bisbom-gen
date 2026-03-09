# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Rust language support** — full OmniBOR analysis pipeline for Rust projects using bomtrace2:
  - Rust toolchain (rustup + stable) installed in Docker image
  - `_run_rust_pipeline()` in analyze.py with Rust-specific build doc notes
  - Cargo registry path classification (`.cargo/registry/src/`) as project_source
  - `_rust_crate_from_registry_path()` regex for crate name/version extraction
  - `_parse_cargo_lock()` for deterministic crate version resolution
  - Rust crate SPDX packages with STATIC_LINK relationships and `pkg:cargo` PURLs
  - `.rs` source files included in SPDX file entries
- **oxipng** as first Rust analysis target (94 packages, 85 files, 179 relationships, 44 crates)
- **dura** as second Rust analysis target (Git background auto-commit, ~42 direct + 35 transitive deps)
- Anti-hang rules in `command-execution.md` (no inline multiline Python, no interactive gh/git)

### Fixed

- `_parse_cargo_lock` now checks `repos_dir/repo_name/` directly for Cargo.lock,
  fixing version/PURL resolution when file paths are relative
- Add `requirements.txt` and `requirements-dev.txt` as single source of truth for Python dependencies
- Dockerfile now `COPY`s and installs from `requirements.txt` instead of ad-hoc `pip install` commands
- Docker build context changed to project root so Dockerfile can access `requirements.txt`
- Fixes `ModuleNotFoundError: No module named 'yaml'` when running app scripts inside the container
- Pin strace to v6.11 for stable bomtrace2/bomtrace3 patch application
- Force `linux/amd64` platform in docker-compose (bomtrace3 requires x86 `sys/reg.h`)
- Use `make -j1` for bomtrace3 to avoid `printers.h` parallel build race condition
- Suppress GCC `stringop-overflow` warning in bomsh_hook.c (upstream bomsh bug)
- Use `--enable-mpers=check` to match bomsh project's own build configuration

### Added

- **ADG-based SPDX generator** (`app/spdx_from_adg.py`) — generates complete SPDX 2.3 JSON
  directly from OmniBOR ADG data, replacing the incomplete bomsh_sbom.py output:
  - `AdgParser`: reads bomsh treedb and classifies all build artifacts
  - `ComponentResolver`: maps system files to dpkg packages with name, version, supplier,
    homepage, PURL (`pkg:deb/ubuntu/...`), and CPE 2.3 identifiers
  - `SpdxEmitter`: produces SPDX with packages, source files, relationships
    (DEPENDS_ON, BUILD_TOOL_OF, CONTAINS), and OmniBOR ExternalRefs
  - For curl: 13 packages, 441 source files, 454 relationships (vs 2 packages from bomsh_sbom.py)
- **Metadata collection script** (`app/collect_metadata.py`) — runs inside the build container
  to resolve system files to dpkg packages via `dpkg -S` and extract rich metadata
- `SpdxValidator` class in `analyze.py` — two-phase SPDX v2.3 validation:
  1. JSON Schema validation against the official SPDX 2.3 schema (via `jsonschema`)
  2. Semantic validation via `spdx-tools` (`parse_file` + `validate_full_spdx_document`)
  Either phase degrades gracefully if its library is unavailable
- SPDX validation step (Step 6) added to the analysis pipeline, runs after SPDX generation
- `BinaryCollector` class in `analyze.py` — copies `output_binaries` from the build tree into `output/binaries/<repo>/` for download to local Mac
- `jsonschema==4.23.0` and `spdx-tools==0.8.2` added to `requirements.txt`
- DigitalOcean droplet (`omnibor-build`) for native x86_64 bomtrace3 builds — replaces local Docker
- Droplet shutdown reminder rule (`.windsurf/rules/droplet-shutdown.md`)
- bomtrace3 QEMU/Rosetta debug findings documented (`docs/bomtrace3-qemu-debug.md`)
- GitHub Issue draft for omnibor/bomsh QEMU bugs (`docs/github-issue-bomsh-qemu.md`)

### Fixed

- `bomsh_sbom.py` CLI invocation — removed incorrect `-r` flag (means `--remove_intermediate_files`, not raw logfile)

### Changed

- Setup-environment workflow now checks SSH to DigitalOcean droplet instead of local Docker
- Docker rules updated: builds run on remote droplet, local Docker no longer required
- Per-repo `apt_deps` field in `config.yaml` — explicitly lists required `-dev` packages for each target repo's build
- `DependencyValidator` class in `analyze.py` — checks all `apt_deps` are installed (via `dpkg-query`) before starting an instrumented build; prints actionable install hints on failure
- `ConfigGenerator.generate_entry()` now includes discovered `apt_deps` in generated config entries
- Explicit `apt_deps` for `curl` (10 packages) and `ffmpeg` (13 packages) in `config.yaml`
- `app/add_repo.py` — smart repo discovery script that auto-generates `config.yaml` entries from just a repo name using GitHub API (`gh` CLI)
  - Detects build systems: autoconf, cmake, meson, perl-configure (OpenSSL), auto-configure (nginx), configure-only (FFmpeg), make-only
  - Analyzes `configure.ac` / `CMakeLists.txt` / `configure` for dependency flags
  - Cross-checks required apt packages against the Dockerfile
  - Supports dry-run (default) and `--write` mode
- `app/data_loader.py` — external data loader with fetch/cache/fallback pattern
  - Build system indicators loaded from `app/data/build_systems.json` (sourced from GitHub Linguist)
  - Dependency metadata loaded from `app/data/dependencies.json` (sourced from Repology API)
  - On-demand Repology lookups for unknown dependencies with automatic cache persistence
  - Respects Repology rate limits (1 req/sec) and never fails on network errors
- `docs/summary/workflow-guide.md` — consolidated user guide for all workflows
- Mandatory rules-review step (Step 0) in `/setup-environment` workflow
- Comprehensive Docker build documentation in `docker/README.md` (troubleshooting table, architecture notes, version pin rationale)
- Detailed inline build notes in `docker/Dockerfile`
- `.windsurf/rules/build-documentation.md` — rule to update docs after build changes
- `.windsurf/rules/pre-commit.md` — pre-commit quality gates (tests, coverage, single-step git)
- `.windsurf/workflows/merge-pr.md` — streamlined PR merge workflow

### Changed

- `/add-repo` workflow now uses `app/add_repo.py` for automated config generation instead of manual editing
- `BUILD_SYSTEM_INDICATORS` and `KNOWN_DEPENDENCIES` replaced with external JSON data files loaded via `data_loader.py` (no more hardcoded static lists)
- Refactored `app/add_repo.py` from procedural to class-based architecture using design patterns:

  - `GitHubClient` — encapsulates all gh CLI / GitHub API interactions
  - `BuildSystemDetector` — detects build system from file list (Strategy pattern via indicator list)
  - `DependencyAnalyzer` — inspects config files for dependency flags
  - `BinaryDetector` — detects output binaries from Makefiles
  - `BuildStepGenerator` — generates build commands per build system (Strategy pattern via recipe dispatch)
  - `ConfigGenerator` — generates and writes config.yaml entries
  - `RepoDiscovery` — facade orchestrating the full pipeline (Facade pattern)

- Refactored `app/data_loader.py` from procedural to class-based architecture:

  - `HttpClient` — minimal HTTP transport with user-agent
  - `JsonCache` — atomic JSON read/write with age tracking
  - `RepologyResolver` — resolves library names to Debian -dev packages (Strategy pattern)
  - `DataLoader` — main facade composing the above
  - Module-level convenience functions preserved for backward compatibility

- Refactored `app/analyze.py` from procedural to class-based architecture:

  - `CommandRunner` — wraps subprocess execution with logging
  - `RepoCloner` — handles git clone logic
  - `BomtraceBuilder` — instrumented build with bomtrace3 and ADG generation
  - `SpdxGenerator` — generates SPDX SBOM from OmniBOR data
  - `SyftGenerator` — generates baseline manifest SBOM via Syft
  - `DocWriter` — writes build logs and runtime metrics
  - `AnalysisPipeline` — facade orchestrating the full workflow (Facade pattern)

- Refactored `app/compare.py` from procedural to class-based architecture:

  - `SpdxLoader` — loads and parses SPDX JSON files
  - `PackageExtractor` — extracts and normalizes package data
  - `SbomComparator` — compares two SPDX package sets
  - `ReportGenerator` — generates markdown comparison reports
  - `ComparisonPipeline` — facade orchestrating the full workflow (Facade pattern)

- Rewrote all tests to use class-based API (207 tests, 99% coverage)

## [0.1.0] - 2026-02-10

### Added

- Initial project structure
- Docker-based OmniBOR build interception environment (bomtrace3, syft)
- `app/analyze.py` — build interception and SPDX SBOM generation
- `app/compare.py` — SBOM comparison between OmniBOR and binary scan results
- Windsurf rules and workflows for project governance
- GitHub issue and PR templates
- Project documentation (README, CONTRIBUTING, LICENSE)
