# App Architecture and Call Graph

This document maps every file under `app/`, shows how they call each
other, and traces the execution flow from entry points to leaf modules.
Use this as a guide to understand how the OmniBOR analysis pipeline
works end to end.

> **Visual overview:** Open [`omnibor-analysis-workflow.drawio`](omnibor-analysis-workflow.drawio)
> in [draw.io](https://app.diagrams.net/) for a high-level pipeline diagram.

---

## Table of Contents

1. [Entry Points](#1-entry-points)
2. [Pipeline Workflow (analyze.py)](#2-pipeline-workflow-analyzepy)
3. [SPDX Generation (spdx_from_adg.py)](#3-spdx-generation-spdx_from_adgpy)
4. [Visualization (spdx_visualize.py)](#4-visualization-spdx_visualizepy)
5. [SBOM Comparison (compare.py)](#5-sbom-comparison-comparepy)
6. [Repo Discovery (add_repo.py)](#6-repo-discovery-add_repopy)
7. [Shared Utilities](#7-shared-utilities)
8. [Full Dependency Map](#8-full-dependency-map)
9. [Package Summaries](#9-package-summaries)

---

## 1. Entry Points

There are five independent CLI entry points. Each can be run as
`python3 -m app.<module>` or directly inside the Docker container.

| Entry Point | Purpose | Where it runs |
|-------------|---------|---------------|
| `app/analyze.py` | Full pipeline: clone → build → instrument → SPDX → validate → collect | Docker container (EC2) |
| `app/spdx_from_adg.py` | Standalone ADG-to-SPDX generation (per-binary) | Docker container |
| `app/spdx_visualize.py` | Generate HTML visualization from SPDX JSON | Local or container |
| `app/compare.py` | Compare OmniBOR SBOM vs. proprietary scan SBOM | Local |
| `app/add_repo.py` | Auto-discover and add a new repo to config.yaml | Local |

## 2. Pipeline Workflow (analyze.py)

`analyze.py` is the main orchestrator. It reads `config.yaml`, creates
an `AnalysisPipeline` facade, and dispatches to a language-specific
runner. Here is the call sequence for a typical `--repo curl` run:

```
analyze.py
 └─ main()                              # CLI argument parsing
     ├─ config.load_config()            # Load app/config.yaml
     ├─ AnalysisPipeline()              # Create facade (composes all steps)
     │   ├─ CommandRunner()             # Shell command executor
     │   ├─ DependencyValidator()       # Check apt deps are installed
     │   ├─ RepoCloner()               # git clone --branch <tag>
     │   ├─ BomtraceBuilder()          # Instrumented build (bomtrace2/3)
     │   ├─ SpdxGenerator()            # bomsh_sbom.py → OmniBOR SPDX
     │   ├─ SpdxValidator()            # JSON schema + semantic checks
     │   ├─ SyftGenerator()            # Syft manifest-based SBOM
     │   ├─ MetadataCollector()        # collect_metadata + collect_dynamic_libs
     │   ├─ AdgSpdxStep()             # Per-binary analyzed + build SBOMs
     │   ├─ BinaryCollector()          # Copy output binaries to output/
     │   └─ DocWriter()                # Write build.md + runtime.md
     │
     └─ _run_{language}_pipeline()      # Language-specific step sequence
```

### Language-specific pipelines

Pipeline execution is split between `runners.py` (CLI + mode routing)
and `lang_runners.py` (per-language step sequences). Each language
follows the same pattern:

```
Step 1: Clone           RepoCloner.clone()
Step 2: Syft SBOM       SyftGenerator.generate()                [if enabled]
Step 3: Validate deps   DependencyValidator.validate()          [C/C++ only]
Step 4: Build           BomtraceBuilder.build()                 [or sidecar strategy]
Step 5a: OmniBOR SPDX   SpdxGenerator.generate()                [or generate_java()]
Step 5b: Metadata        MetadataCollector.collect()
Step 5c: ADG SPDX        AdgSpdxStep.generate()                 [or JavaSpdxGenerator]
Step 6: Validate         SpdxValidator.validate()
Step 7: Collect          BinaryCollector.collect()
Step 8: Docs             DocWriter.write_build_doc() + write_runtime_doc()
```

| Language | Tracer | ADG SPDX Generator | Notes |
|----------|--------|-------------------|-------|
| C/C++ | bomtrace3 | `AdgSpdxStep` → `AdgSpdxGenerator` | apt deps validated first |
| Rust | bomtrace2 | `AdgSpdxStep` → `AdgSpdxGenerator` | Same as C/C++ but bomtrace2 |
| Go | bomtrace2 + `bomtrace_go.conf` | `AdgSpdxStep` → `AdgSpdxGenerator` | Needs `-a` flag, openat tracing |
| Java | strace + `bomsh_create_bom_java.py` | `JavaSpdxGenerator` | Maven + Gradle dep:tree support |

### Pipeline file dependencies

```
app/pipeline/runners.py          # CLI main() + mode routing (standalone/sidecar/phase)
 ├─ app/config.py                # load_config(), timestamp(), lang_subdir()
 ├─ app/pipeline/lang_runners.py # Per-language pipeline orchestration
 │   └─ app/pipeline/timing.py   # StepTimer, TimingResult, StepMetrics
 ├─ app/pipeline/manifest.py     # Phase 1/2 manifest (write, read, verify gitoids)
 └─ app/pipeline/facade.py       # AnalysisPipeline (composes all steps below)
     ├─ app/runner.py             # CommandRunner (subprocess wrapper)
     ├─ app/pipeline/validator.py        # DependencyValidator
     │   └─ app/runner.py
     ├─ app/pipeline/cloner.py           # RepoCloner
     │   └─ app/runner.py
     ├─ app/pipeline/builder.py          # BomtraceBuilder + interception strategy
     │   ├─ app/config.py
     │   ├─ app/runner.py
     │   └─ app/pipeline/interception.py  # InterceptionStrategy ABC + PtraceStrategy
     ├─ app/pipeline/spdx_generator.py   # SpdxGenerator (bomsh_sbom.py wrapper)
     │   ├─ app/config.py
     │   └─ app/runner.py
     ├─ app/pipeline/spdx_validator.py   # SpdxValidator
     ├─ app/pipeline/syft.py             # SyftGenerator
     │   ├─ app/config.py
     │   └─ app/runner.py
     ├─ app/pipeline/metadata_collector.py  # MetadataCollector
     │   ├─ app/config.py
     │   └─ app/runner.py
     ├─ app/pipeline/adg_spdx.py         # AdgSpdxStep
     │   ├─ app/config.py
     │   └─ app/spdx_from_adg.py  [lazy import inside generate()]
     ├─ app/pipeline/binary_collector.py  # BinaryCollector
     │   └─ app/config.py
     └─ app/pipeline/doc_writer.py       # DocWriter
         └─ app/config.py

# Java-specific pipeline modules
app/pipeline/maven_dep_tree_parser.py   # Parse mvn dependency:tree DOT format
app/pipeline/gradle_dep_tree_parser.py  # Parse gradle dependencies tree format
app/pipeline/maven_plugin_detector.py   # Detect shade/assembly plugin in pom.xml
app/pipeline/language_validator.py      # Validate language is supported
app/pipeline/version_checker.py         # Check bomsh upstream for updates
```

## 3. SPDX Generation (`spdx_from_adg.py`)

`spdx_from_adg.py` is a backward-compatibility **shim** that re-exports
everything from the refactored `app/spdx/` package. New code should
import directly from `app.spdx.*`.

### Call graph: ADG → SPDX JSON → HTML

```
spdx_from_adg.py (shim)
 └─ re-exports from app/spdx/

app/spdx/cli.py                  # Standalone CLI entry point
 └─ AdgSpdxGenerator.generate()

app/spdx/generator.py            # AdgSpdxGenerator (facade)
 ├─ app/spdx/parser.py           # AdgParser — reads bomsh treedb, classifies artifacts
 ├─ app/spdx/resolver.py         # ComponentResolver — maps artifacts to packages
 ├─ app/spdx/emitter.py          # SpdxEmitter — produces SPDX 2.3 JSON
 │   └─ app/version_detection/   # VendoredVersionDetector (12 strategies)
 │       ├─ detector.py           # Orchestrates strategies in priority order
 │       ├─ strategies.py         # 12 version detection strategies
 │       └─ patterns.py           # Regex patterns and file name constants
 └─ app/spdx_visualize.py        # generate_html() [called at end of generate()]
     └─ app/viz/                  # Visualization sub-package (see §4)
```

### Java-specific path

Java does not use `AdgSpdxGenerator`. It has its own generator:

```
app/pipeline/runners.py
 └─ _generate_java_adg_spdx()
     └─ app/spdx/java_generator.py    # JavaSpdxGenerator
         ├─ app/spdx/parser.py         # AdgParser (shared with native langs)
         ├─ mvn dependency:tree         # Maven CLI for transitive deps
         ├─ pom.xml parsing             # XML for project metadata
         └─ Sibling module filtering    # BFS to exclude sibling transitive deps
```

**Sibling module filtering:** For multi-module Java projects (e.g., dependency-check
with cli, core, utils modules), each module's SPDX should only contain its own
dependencies. Transitive deps of sibling modules are excluded via BFS traversal
and appear in the sibling's own SPDX file instead.

### The spdx/ package at a glance

| File | Class | Responsibility |
|------|-------|----------------|
| `parser.py` | `AdgParser` | Read bomsh treedb, classify artifacts (system_lib, project_source, go_stdlib, etc.) |
| `resolver.py` | `ComponentResolver` | Load `component_metadata.json` and `dynamic_libs.json`, map files to dpkg packages |
| `emitter.py` | `SpdxEmitter` | Build SPDX 2.3 JSON: packages, files, relationships, PURLs, ExternalRefs |
| `generator.py` | `AdgSpdxGenerator` | Facade: compose parser → resolver → emitter → write JSON → generate HTML |
| `java_generator.py` | `JavaSpdxGenerator` | Java-specific: treedb + Maven/Gradle deps + sibling filtering |
| `cli.py` | `main()` | Standalone CLI for `python3 -m app.spdx_from_adg` |
| `relationships.py` | — | SPDX 2.3 relationship type constants and scope-to-type mapping |
| `vendored.py` | — | Vendored dependency detection and sub-component splitting |
| `lang_parsers.py` | — | Go module, Rust crate, and C/C++ artifact path parsers |
| `maven_parser.py` | `MavenParser` | Parse Maven `dependency:tree` output for SPDX emission |
| `gradle_parser.py` | `GradleParser` | Parse Gradle `dependencies` output for SPDX emission |
| `package_resolver.py` | `PackageResolver` | Multi-distro abstraction: dpkg, rpm, apk resolver factory |
| `dpkg_resolver.py` | `DpkgResolver` | Debian/Ubuntu `dpkg-query -S` package resolution |
| `rpm_resolver.py` | `RpmResolver` | RHEL/CentOS `rpm -qf` package resolution |
| `apk_resolver.py` | `ApkResolver` | Alpine `apk info --who-owns` package resolution |
| `structural_comparator.py` | `SpdxStructuralComparator` | Compare SPDX docs for structural equivalence (golden file testing) |
| `version_detector.py` | — | Backward-compat shim → `app.version_detection` |

## 4. Visualization (`spdx_visualize.py`)

`spdx_visualize.py` is the **orchestrator** that reads an SPDX JSON
document and assembles a standalone HTML file from modular parts in
`app/viz/`.

### Call graph

```
app/spdx_visualize.py             # Orchestrator + CLI
 ├─ generate_html(doc, path)       # Main function
 │   ├─ app/viz/extract.py         # extract_graph() — parse SPDX JSON into nodes/edges
 │   ├─ app/viz/styles.py          # get_css() — all CSS as a Python string
 │   ├─ app/viz/html_parts.py      # get_header_html(), get_legend_html(), get_ui_html()
 │   ├─ app/viz/js_simulation.py   # get_js_simulation() — D3 force layout, BFS tree, fanout
 │   └─ app/viz/js_interaction.py  # get_js_interaction() — rendering, tooltips, drag, search
 └─ main()                         # CLI: argparse → load JSON → generate_html()
```

### How the HTML is assembled

```python
parts = [
    "<!DOCTYPE html>",
    "<head>",
    "  <style>",        get_css(),           "</style>",
    "</head>",
    "<body>",
    get_header_html(),                       # Title bar
    get_legend_html(),                       # Relationship/type counts
    get_ui_html(),                           # Tooltip + search box
    "<script src='d3.v7.min.js'></script>",
    "<script>",
    "  const data = {graph_data};",          # Inline JSON
    get_js_simulation(),                     # Force simulation setup
    get_js_interaction(),                    # Node/link rendering + events
    "</script>",
    "</body></html>",
]
```

### The viz/ package at a glance

| File | Function | Lines | Responsibility |
|------|----------|-------|----------------|
| `extract.py` | `extract_graph(doc)` | 234 | Parse SPDX relationships → nodes/edges with groups, types, colors |
| `styles.py` | `get_css()` | 140 | Complete CSS for the visualization page |
| `html_parts.py` | `get_header_html()`, `get_legend_html()`, `get_ui_html()` | 126 | HTML fragments for header, legend, tooltip, search |
| `js_simulation.py` | `get_js_simulation()` | 336 | D3 force simulation: layout, BFS tree, xPositions, yPositions, fanout |
| `js_interaction.py` | `get_js_interaction()` | 272 | D3 rendering: nodes, links, tooltips, drag, click highlight, search |
| `__init__.py` | — | 3 | Re-exports `extract_graph` |

### Who calls the visualizer?

The visualizer is called in two places:

1. **`app/spdx/generator.py`** line 180 — automatically after generating
   each SPDX JSON (`from spdx_visualize import generate_html`)
2. **`scripts/regen_html.sh`** — batch regeneration of all HTML files
   from existing SPDX JSON files

## 5. SBOM Comparison (compare.py)

`compare.py` is a standalone tool that compares an OmniBOR-generated
SPDX against a proprietary binary scan SPDX. It is self-contained
(does not import from `app/spdx/` or `app/pipeline/`).

```
app/compare.py
 ├─ SpdxLoader          # Load SPDX JSON files
 ├─ PackageExtractor    # Normalize package names/versions
 ├─ SbomComparator      # Set intersection/difference
 ├─ ReportGenerator     # Markdown comparison report
 └─ ComparisonPipeline  # Facade orchestrating the above
```

## 6. Repo Discovery (`add_repo.py`)

`add_repo.py` auto-discovers build system, dependencies, and output
binaries for a GitHub repository and generates a `config.yaml` entry.

```
app/add_repo.py (shim)
 └─ re-exports from app/repo_discovery/

app/repo_discovery/cli.py              # CLI entry point
 └─ app/repo_discovery/facade.py       # RepoDiscovery (facade)
     ├─ app/data_loader.py             # Repology API + cached JSON data
     ├─ app/repo_discovery/github_client.py        # GitHub API via gh CLI
     ├─ app/repo_discovery/build_system_detector.py # Detect Makefile/CMake/etc.
     ├─ app/repo_discovery/dependency_analyzer.py   # Parse configure flags
     │   └─ github_client.py
     ├─ app/repo_discovery/binary_detector.py       # Find output binary paths
     │   └─ github_client.py
     ├─ app/repo_discovery/build_step_generator.py  # Generate build commands
     └─ app/repo_discovery/config_generator.py      # Write config.yaml entry
```

## 7. Shared Utilities

These files are imported by multiple parts of the codebase:

| File | What it provides | Used by |
|------|-----------------|---------|
| `app/config.py` | `load_config()`, `timestamp()`, `lang_subdir()` | pipeline/*, runners.py |
| `app/runner.py` | `CommandRunner` (subprocess wrapper with logging) | pipeline/facade.py and 6 pipeline steps |
| `app/config.yaml` | All repo definitions, paths, omnibor settings | config.py, runners.py |
| `app/data_loader.py` | `DataLoader` (Repology API, JSON cache) | repo_discovery/facade.py |

### Container-only utilities

These run inside the Docker container during pipeline execution:

| File | Purpose | Called by |
|------|---------|----------|
| `app/collect_metadata.py` | dpkg metadata for system files → `component_metadata.json`; root version from config tag | `MetadataCollector` |
| `app/collect_dynamic_libs.py` | ldd/readelf → `dynamic_libs.json` per binary | `MetadataCollector` |
| `app/apply_qemu_fallback.py` | Patch bomsh for QEMU/Apple Silicon compatibility | Dockerfile |

## 8. Full Dependency Map

Every `app/*.py` file and what it imports from within the project:

```
analyze.py
 ├── app.config (load_config, timestamp, lang_subdir)
 ├── app.runner (CommandRunner)
 └── app.pipeline.* (all 10 pipeline steps + facade + runners)

spdx_from_adg.py [shim]
 ├── app.spdx.parser (AdgParser)
 ├── app.spdx.resolver (ComponentResolver)
 ├── app.spdx.emitter (SpdxEmitter)
 ├── app.spdx.generator (AdgSpdxGenerator)
 ├── app.spdx.cli (main)
 └── app.version_detection (VendoredVersionDetector)

spdx_visualize.py
 ├── app.viz.extract (extract_graph)
 ├── app.viz.styles (get_css)
 ├── app.viz.html_parts (get_header_html, get_legend_html, get_ui_html)
 ├── app.viz.js_simulation (get_js_simulation)
 └── app.viz.js_interaction (get_js_interaction)

compare.py
 └── (self-contained — no app.* imports)

add_repo.py [shim]
 ├── data_loader (DataLoader)
 └── app.repo_discovery.* (all 6 discovery modules + facade + cli)

app/spdx/emitter.py
 ├── app.version_detection (VendoredVersionDetector)
 ├── app.spdx.relationships (relationship type constants)
 ├── app.spdx.lang_parsers (Go/Rust/C++ path parsers)
 └── app.spdx.vendored (vendored detection + sub-component split)

app/spdx/generator.py
 ├── app.spdx.parser
 ├── app.spdx.resolver
 ├── app.spdx.emitter
 └── spdx_visualize (generate_html) [lazy import at end]

app/spdx/java_generator.py
 ├── app.spdx.parser (AdgParser)
 ├── app.spdx.maven_parser (MavenParser)
 └── app.spdx.gradle_parser (GradleParser)

app/spdx/package_resolver.py
 ├── app.spdx.dpkg_resolver (DpkgResolver)
 ├── app.spdx.rpm_resolver (RpmResolver)
 └── app.spdx.apk_resolver (ApkResolver)

app/pipeline/adg_spdx.py
 ├── app.config
 └── spdx_from_adg (AdgSpdxGenerator) [lazy import]

app/pipeline/facade.py
 ├── app.runner
 └── app.pipeline.{validator,cloner,builder,spdx_generator,
     spdx_validator,syft,metadata_collector,adg_spdx,
     binary_collector,doc_writer}

app/pipeline/runners.py
 ├── app.config
 ├── app.pipeline.facade
 ├── app.pipeline.lang_runners (run_c_cpp/rust/go/java_pipeline)
 ├── app.pipeline.manifest (write_manifest, read_manifest, verify_gitoids)
 └── app.spdx.java_generator [lazy import in _generate_java_adg_spdx]

app/pipeline/lang_runners.py
 ├── app.config (lang_subdir)
 └── app.pipeline.timing (StepTimer, TimingResult)

app/pipeline/interception.py
 └── (ABC + PtraceStrategy, CcWrapperStrategy, GoToolexecStrategy, RustcWrapperStrategy, etc.)

app/pipeline/timing.py
 └── (StepTimer, StepMetrics, TimingResult dataclasses)

app/pipeline/manifest.py
 └── (write_manifest, read_manifest, verify_gitoids)

app/pipeline/maven_dep_tree_parser.py
 └── (parse Maven dependency:tree DOT format)

app/pipeline/gradle_dep_tree_parser.py
 └── app.spdx.gradle_parser

app/pipeline/maven_plugin_detector.py
 └── (scan pom.xml for shade/assembly plugins)

app/collect_metadata.py
 └── app.version_detection (VendoredVersionDetector) [lazy import]
```

## 9. Package Summaries

### `app/pipeline/` — Build orchestration (10 step classes + facade + runners + 8 support modules)

Manages the full lifecycle: clone, build with bomtrace instrumentation,
generate SPDX, validate, collect artifacts, write docs. Each step is a
small class (30-80 lines) that depends only on `app.config` and
`app.runner`. Support modules handle interception strategies, timing,
phase 1/2 manifest, Maven/Gradle dep tree parsing, plugin detection,
language validation, and version checking.

### `app/spdx/` — SPDX generation (parser → resolver → emitter + 11 support modules)

Three-stage pipeline: parse bomsh treedb → resolve artifacts to named
packages → emit SPDX 2.3 JSON. The `AdgSpdxGenerator` facade composes
all three. `JavaSpdxGenerator` handles Java-specific Maven/Gradle
dependency resolution. Multi-distro package resolvers (dpkg, rpm, apk)
support Ubuntu, RHEL, and Alpine. Language-specific parsers handle
Go modules, Rust crates, and vendored C/C++ libraries.

### `app/viz/` — D3.js visualization (6 modules)

Modular HTML generation for interactive dependency graphs. The
orchestrator (`spdx_visualize.py`) assembles CSS, HTML fragments, and
JS code from dedicated modules. Each module is under 340 lines.

### `app/version_detection/` — Root + vendored version detection (3 modules)

12 ordered strategies for detecting versions from source trees
(VERSION files, CMakeLists.txt, configure.ac, package.json, Cargo.toml,
pom.xml, Makefile variables, etc.). Used by `SpdxEmitter` to set
`versionInfo` on vendored packages, and by `collect_metadata.py` to
detect the root package version from config tags with file-based
fallback.

### `app/repo_discovery/` — Auto-discover repos (6 modules)

GitHub API client, build system detection, dependency analysis, binary
path detection, build step generation, and config.yaml writing. Used by
`add_repo.py` to onboard new target repositories.

---

*Last updated: June 10, 2026*
