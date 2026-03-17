# app/ — Application Code

This directory contains the OmniBOR Analysis application: orchestration scripts,
SPDX generation, repo discovery, and supporting utilities.

## Entry Points

These are the three main scripts. Each is a **thin shim** that re-exports from
its corresponding package for backward compatibility. Run them directly or import
from the packages.

| Entry Point | Package | Purpose |
|-------------|---------|---------|
| `analyze.py` | `app.pipeline` | Clone, build, instrument, generate SBOMs |
| `spdx_from_adg.py` | `app.spdx` | Per-binary SPDX 2.3 from ADG data |
| `add_repo.py` | `app.repo_discovery` | Auto-discover repos from GitHub |

```bash
# Run analysis (inside Docker container)
python3 /workspace/app/analyze.py --repo curl

# Generate SPDX from ADG (inside Docker container)
python3 /workspace/app/spdx_from_adg.py /path/to/adg_dir --binary curl

# Add a repo (local, uses GitHub API)
python3 app/add_repo.py openssl --write
```

## Packages

### `pipeline/` — Analysis Pipeline (from `analyze.py`)

Full build interception and SBOM generation pipeline.

| Module | Class/Function | Purpose |
|--------|---------------|---------|
| `facade.py` | `AnalysisPipeline` | Top-level orchestrator |
| `runners.py` | `main()`, `_run_c_cpp_pipeline()`, `_run_rust_pipeline()`, `_run_go_pipeline()` | CLI and per-language runners |
| `cloner.py` | `RepoCloner` | Git clone with depth/branch control |
| `builder.py` | `BomtraceBuilder` | bomtrace2/3 instrumented builds |
| `spdx_generator.py` | `SpdxGenerator` | bomsh_sbom.py SPDX generation |
| `spdx_validator.py` | `SpdxValidator` | JSON Schema + semantic validation |
| `syft.py` | `SyftGenerator` | Syft manifest-based SPDX baseline |
| `metadata_collector.py` | `MetadataCollector` | dpkg package resolution + ldd |
| `adg_spdx.py` | `AdgSpdxStep` | Per-binary ADG→SPDX + visualization |
| `binary_collector.py` | `BinaryCollector` | Copy output binaries to output dir |
| `doc_writer.py` | `DocWriter` | Generate build.md and runtime.md |
| `validator.py` | `DependencyValidator` | Verify apt deps are installed |

### `spdx/` — SPDX Generation (from `spdx_from_adg.py`)

Converts OmniBOR ADG data into SPDX 2.3 JSON with vendored detection,
version extraction, and relationship classification.

| Module | Class | Purpose |
|--------|-------|---------|
| `generator.py` | `AdgSpdxGenerator` | Top-level orchestrator |
| `parser.py` | `AdgParser` | Parse bomsh ADG tree database |
| `resolver.py` | `ComponentResolver` | Group source files into components |
| `version_detector.py` | `VendoredVersionDetector` | Backward-compat shim → `app.version_detection` |
| `emitter.py` | `SpdxEmitter` | Assemble SPDX 2.3 JSON document |
| `cli.py` | `main()` | CLI entry point |

### `repo_discovery/` — Repo Discovery (from `add_repo.py`)

Searches GitHub, detects build systems, and generates `config.yaml` entries.

| Module | Class | Purpose |
|--------|-------|---------|
| `facade.py` | `RepoDiscovery` | Top-level orchestrator |
| `github_client.py` | `GitHubClient` | GitHub API via `gh` CLI |
| `build_system_detector.py` | `BuildSystemDetector` | Detect autoconf/cmake/meson/make |
| `dependency_analyzer.py` | `DependencyAnalyzer` | Parse configure.ac/CMakeLists for deps |
| `binary_detector.py` | `BinaryDetector` | Parse Makefile.am for output binaries |
| `build_step_generator.py` | `BuildStepGenerator` | Generate build_steps for config.yaml |
| `config_generator.py` | `ConfigGenerator` | Write config.yaml entries |
| `cli.py` | `main()` | CLI entry point |

### `version_detection/` — Version Detection

Detects versions of vendored libraries and project root packages from source
code. Supports 12 ordered strategies across C/C++, JavaScript, Python, and
key-value ecosystems.

| Module | Class/Function | Purpose |
|--------|---------------|----------|
| `detector.py` | `VendoredVersionDetector` | Orchestrates 12 strategies in priority order |
| `strategies.py` | `parse_*()` functions | Individual strategy implementations (testable) |
| `patterns.py` | `VER_RE`, `PATCH_SUFFIXES`, `name_prefixes()` | Regex patterns, suffix aliases, prefix generation |

## Shared Utilities

| File | Purpose |
|------|---------|
| `config.py` | `load_config()`, `timestamp()`, `lang_subdir()` — used by all packages |
| `runner.py` | `CommandRunner` — subprocess wrapper with logging |
| `data_loader.py` | Shared data loading (ADG, metadata, component data) |
| `config.yaml` | Single source of truth: repo URLs, build steps, language, paths |

## Other Scripts

| File | Purpose |
|------|---------|
| `spdx_visualize.py` | D3.js interactive HTML dependency graph generator |
| `collect_metadata.py` | Resolve system files to dpkg packages |
| `collect_dynamic_libs.py` | Per-binary ldd/readelf dynamic library analysis |
| `compare.py` | Compare OmniBOR SBOM vs proprietary binary scanner SBOM |

## Import Patterns

```python
# New style (preferred) — import from packages directly
from app.pipeline.facade import AnalysisPipeline
from app.spdx.generator import AdgSpdxGenerator
from app.repo_discovery.github_client import GitHubClient
from app.config import load_config, timestamp

# Legacy style (still works via thin shims)
from analyze import AnalysisPipeline, CommandRunner
from spdx_from_adg import AdgSpdxGenerator
from add_repo import GitHubClient, RepoDiscovery
```
