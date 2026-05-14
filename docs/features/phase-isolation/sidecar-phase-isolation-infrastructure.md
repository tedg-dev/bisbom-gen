# Sidecar & Phase Isolation — Shared Infrastructure

> **Status**: Design proposal — not yet implemented
> **Date**: 2026-06-12
> **Prerequisite docs**: `sidecar-refactoring-plan.md`, `sidecar-implementation-design.md`,
> `phase2-binary-artifact-dependencies.md`, `sidecar-async-spdx-architecture.md`

---

## Per-Language Design Documents

This document covers the **shared components** that all languages use:
manifest format, CLI flags, config schema, Corona integration, Docker
setup, and the testing framework. Each language has its own design doc
with strategy details, Phase 1/2 artifacts, and implementation tasks:

- **`sidecar-c-cpp-design.md`** — `CcWrapperStrategy`, upstream bomsh wrappers, version pre-computation
- **`sidecar-java-design.md`** — `MavenDepTreeStrategy`/`GradleDepTreeStrategy` (already implemented)
- **`sidecar-go-design.md`** — `GoToolexecStrategy`, `-a` flag interaction
- **`sidecar-rust-design.md`** — `RustcWrapperStrategy`, `RUSTC_WRAPPER` vs `RUSTC_WORKSPACE_WRAPPER`
- **`sidecar-python-design.md`** — metadata-only pipeline (future)

---

## 1. Executive Summary

The `omnibor-analysis` pipeline supports two execution modes:
**Standalone** and **Sidecar**. Both are permanent, first-class modes.

- **Sidecar** is the authoritative mode for all enterprise repository
  build-interception SBOM generation projects. It uses the customer's
  native toolchains and does not require `SYS_PTRACE`.
- **Standalone** is the baseline for `omnibor-analysis` golden file
  generation and the primary `omnibor-analysis` development/debug mode.
  It is also used by enterprise teams with isolated black-box build
  machines, where the Standalone container is customized to include their
  specific build toolsets, operating systems, and configurations.

**Standalone** always runs the full pipeline (Phase 1 + Phase 2) in a
single container. There is no phase split for Standalone.

**Sidecar** can run either way:
- **Sidecar full** — Phase 1 + Phase 2 in one container (primary customer mode)
- **Sidecar Phase 1 only** — Phase 1 produces artifacts and exits;
  Phase 2 runs in a separate process, host, or Corona daemon

This document describes the shared infrastructure:

1. **Two modes: Standalone and Sidecar** — Standalone uses ptrace-based
   interception (`bomtrace3`/`bomtrace2`) and requires `SYS_PTRACE`.
   Sidecar uses build-system-native interception mechanisms and does
   **not** require `SYS_PTRACE`. The specific mechanism varies by
   language — see per-language design docs for details.
2. **Phase isolation (Sidecar only)** — Phase 1 (build interception) and
   Phase 2 (SPDX generation) can run independently, connected only by a
   well-defined artifact contract (`phase1_manifest.json`).
3. **Multiple Phase 2 executors** — Phase 2 can run in the sidecar
   container, on a different host, or on a Corona daemon.
4. **CLI, config, and module changes** that apply to all languages.

Language-specific strategy wiring, artifacts, and testing are in the
per-language docs listed above.

---

## 2. Current State Analysis

### 2.1 What Exists Today

| Component | File | Status |
|-----------|------|--------|
| `InterceptionStrategy` ABC | `app/pipeline/interception.py` | ✅ Complete |
| `PtraceStrategy` (standalone) | `app/pipeline/interception.py` | ✅ Complete |
| `CcWrapperStrategy` (C/C++ sidecar) | `app/pipeline/interception.py` | ✅ Skeleton — not wired to CLI |
| `GoToolexecStrategy` (Go sidecar) | `app/pipeline/interception.py` | ✅ Skeleton — not wired to CLI |
| `RustcWrapperStrategy` (Rust sidecar) | `app/pipeline/interception.py` | ✅ Skeleton — not wired to CLI |
| `MavenDepTreeStrategy` (Java sidecar) | `app/pipeline/interception.py` | ✅ Fully wired and tested |
| `GradleDepTreeStrategy` (Java sidecar) | `app/pipeline/interception.py` | ✅ Fully wired and tested |
| Phase 1/2 timing tags | `app/pipeline/timing.py` | ✅ `StepMetrics.phase` ∈ {`phase1`, `phase2`} |
| Dual-mode config resolution | `app/config.py` | ✅ `resolve_omnibor_cfg()` handles nested format |
| `--mode` CLI flag | `app/pipeline/runners.py` | ✅ Parsed, but only passed to Java |
| `BomtraceBuilder.build()` `strategy=` param | `app/pipeline/builder.py` | ✅ Accepts strategy, delegates to it |

### 2.2 What's Missing

| Gap | Impact |
|-----|--------|
| **No `--phase` CLI flag** | Cannot run Phase 1 or Phase 2 independently |
| **No `phase1_manifest.json` writer/reader** | Phase 2 cannot discover Phase 1 artifacts without re-reading config |
| **C/C++, Go, Rust sidecar strategies not wired** | `--mode sidecar` only works for Java |
| **Phase 2 requires the source tree** | `ldd`, `readelf`, `bomsh_sbom.py` read binaries from `repo_dir` |
| **No Corona integration** | Phase 2 can only run inside the same container |
| **`_run_post_build()` is monolithic** | All Phase 2 steps coupled into one function |

### 2.3 Architecture Diagram Reference

The following existing diagrams illustrate the target architecture:

- `../../deep-dive/sidecar-standalone-architecture.drawio` — current standalone flow
- `../../deep-dive/sidecar-target-architecture.drawio` — target dual-mode flow
- `sidecar-two-phase-corona.drawio` — Phase 1 → manifest → Phase 2/Corona
- `../../deep-dive/sidecar-strategy-pattern.drawio` — strategy pattern class hierarchy
- `../../deep-dive/sidecar-critical-path.drawio` — CI/CD critical path reduction
- `../../deep-dive/sidecar-dependency-graph.drawio` — module dependency graph

---

## 3. Design Principles

1. **Backward compatibility** — `python3 -m app.analyze --repo curl` continues to
   work identically (standalone, both phases, sequential).
2. **Artifact-based decoupling** — Phase 1 and Phase 2 communicate exclusively
   through `phase1_manifest.json` plus the artifacts it references.
3. **Strategy pattern** — interception mechanism is selected via config/CLI, not
   hardcoded per-language `if/else` branches.
4. **Config-driven** — no repo-specific logic in executable code; all behavior
   differences come from `config.yaml` fields.
5. **Fail-safe defaults** — if `--mode` is omitted, use standalone; if `--phase`
   is omitted, run both phases.
6. **Single Responsibility** — each new module has exactly one concern.

---

## 4. Artifact Contract: `phase1_manifest.json`

The `phase1_manifest.json` is a small pointer file (~1-2 KB) that records
the paths to the existing artifacts (treedb, raw logfile, binaries,
bom_dir, etc.) plus metadata (repo name, language, commit SHA, run
timestamp). The actual artifact files stay in their original format and
location — nothing is converted or bundled.

The purpose is purely for **Sidecar Phase 1 only** mode: when Phase 2
runs in a different process or on a different host, it needs to know
where all the Phase 1 artifacts are. Today that information is derived
from `config.yaml` + convention, which requires the entire config and
source tree to be available. The manifest decouples that.

The manifest is written after Phase 1 completes (after the build and
treedb generation), before Phase 2 starts. It is a single `json.dump()`
call — effectively zero build-time overhead.

In Standalone mode and Sidecar full mode, where Phase 1 and Phase 2 run
in the same process, the manifest is not needed — Phase 2 already has
everything in memory.

### 4.1 Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": [
    "version", "repo_name", "language", "mode", "tracer",
    "run_ts", "commit_sha", "vcs_uri",
    "artifacts", "paths"
  ],
  "properties": {
    "version": {
      "type": "string",
      "const": "1.0",
      "description": "Manifest schema version"
    },
    "repo_name": { "type": "string" },
    "language": {
      "type": "string",
      "enum": ["c-cpp", "go", "rust", "java", "python"]
    },
    "mode": {
      "type": "string",
      "enum": ["standalone", "sidecar"]
    },
    "tracer": {
      "type": "string",
      "description": "Interception method used (bomtrace3, cc-wrapper, maven-dep-tree, etc.)"
    },
    "run_ts": {
      "type": "string",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}_\\d{4}$"
    },
    "commit_sha": { "type": ["string", "null"] },
    "vcs_uri": { "type": "string" },
    "artifacts": {
      "type": "object",
      "properties": {
        "bom_dir": {
          "type": "string",
          "description": "Absolute path to OmniBOR ADG output directory"
        },
        "treedb": {
          "type": ["string", "null"],
          "description": "Absolute path to bomsh_omnibor_treedb"
        },
        "raw_logfile": {
          "type": ["string", "null"],
          "description": "Absolute path to bomsh_hook_raw_logfile"
        },
        "strace_log": {
          "type": ["string", "null"],
          "description": "Absolute path to strace log (Java standalone only)"
        },
        "dep_tree_json": {
          "type": ["string", "null"],
          "description": "Absolute path to maven_deps.json or gradle_deps.json (Java sidecar)"
        },
        "binaries": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Absolute paths to output binaries/JARs"
        }
      },
      "required": ["bom_dir", "binaries"]
    },
    "paths": {
      "type": "object",
      "properties": {
        "repos_dir": { "type": "string" },
        "output_dir": { "type": "string" },
        "spdx_dir": { "type": "string" }
      },
      "required": ["repos_dir", "output_dir", "spdx_dir"]
    },
    "repo_cfg": {
      "type": "object",
      "description": "Subset of repo config needed by Phase 2 (output_binaries, vendored_dirs, language, description)"
    },
    "omnibor_cfg": {
      "type": "object",
      "description": "Resolved omnibor config section for this language/mode"
    },
    "gitoids": {
      "type": "object",
      "description": "Map of artifact path → SHA-256 gitoid for provenance verification",
      "additionalProperties": { "type": "string" }
    }
  }
}
```

### 4.2 Manifest Location

```
output/omnibor/{lang}/{repo}/{run_ts}/phase1_manifest.json
```

This is inside `bom_dir`, co-located with the OmniBOR ADG artifacts.

### 4.3 When the Manifest Is Written

The manifest is written **after** Phase 1 completes — after the build,
treedb generation, and ADG creation have all finished. It does not run
during the build and has zero impact on build time.

| Mode | Manifest written? | Manifest read? |
|------|------------------|----------------|
| **Standalone** | No | No — Phase 2 has everything in memory |
| **Sidecar full** | No | No — Phase 2 has everything in memory |
| **Sidecar Phase 1 only** | Yes — `json.dump()` after build | No — Phase 2 runs in a separate invocation |
| **Phase 2 from manifest** | No — Phase 1 already ran | Yes — reads manifest to locate artifacts |

### 4.4 Why Not Reuse `config.yaml`?

Today, Phase 2 derives artifact locations from `config.yaml` paths plus
naming conventions (e.g., `output/omnibor/{lang}/{repo}/{run_ts}/`). This
works when both phases run in the same process because the config, source
tree, and build environment are all available.

In Sidecar Phase 1 only mode, Phase 2 runs in a different process or on
a different host. It may not have access to:
- `config.yaml` (the sidecar container may be destroyed after Phase 1)
- The source tree (not transferred to the analysis host)
- The build environment (compiler paths, environment variables)

The manifest captures exactly what Phase 2 needs — artifact paths,
repo metadata, and resolved config — in a single self-contained file
that can be transferred alongside the artifacts.

### 4.5 Provenance Integrity

Each artifact path in the manifest includes a SHA-256 gitoid computed at
Phase 1 completion time. Phase 2 can optionally verify these gitoids
before processing to detect tampering or corruption during transfer.

---

## 5. Phase Isolation Architecture

### 5.1 CLI Interface Changes

```bash
# Standalone (always full pipeline — Phase 1 + Phase 2)
python3 -m app.analyze --repo curl
python3 -m app.analyze --repo curl --mode standalone  # explicit, same effect

# Sidecar full (Phase 1 + Phase 2, no SYS_PTRACE)
python3 -m app.analyze --repo curl --mode sidecar

# Sidecar Phase 1 only — Phase 2 runs elsewhere
python3 -m app.analyze --repo curl --mode sidecar --phase build

# Phase 2 from manifest (consumes artifacts from any Sidecar Phase 1 run)
python3 -m app.analyze --repo curl --phase spdx --manifest /path/to/phase1_manifest.json
```

New CLI arguments in `app/pipeline/runners.py`:

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--phase` | `{build, spdx}` | None (both) | Run only Phase 1 or Phase 2 |
| `--manifest` | path | None | Path to `phase1_manifest.json` (required when `--phase spdx`) |

### 5.2 Execution Patterns

#### Pattern A: Standalone (full pipeline, single container)

```
┌─────────────────────────────────────────────┐
│  Container (standalone, SYS_PTRACE)         │
│                                             │
│  Phase 1: clone → build → treedb → ADG     │
│     ↓ (in-memory, no manifest needed)       │
│  Phase 2: SBOM → metadata → SPDX → validate│
└─────────────────────────────────────────────┘
```

This is the only Standalone pattern. Phase split is not supported in
Standalone mode.

#### Pattern B: Sidecar Full (Phase 1 + Phase 2, single container)

```
┌─────────────────────────────────────────────┐
│  Container (sidecar, NO SYS_PTRACE)         │
│                                             │
│  Phase 1: clone → build → treedb → ADG     │
│     ↓ (in-memory, no manifest needed)       │
│  Phase 2: SBOM → metadata → SPDX → validate│
└─────────────────────────────────────────────┘
```

Same flow as Standalone but using wrapper-based interception. This is
the **primary customer deployment mode**.

#### Pattern C: Sidecar Phase 1 + Separate Phase 2 (two-stage CI)

```
┌──── CI Stage 1 (sidecar) ─────────┐
│  --mode sidecar --phase build      │
│  Phase 1: clone → build → treedb   │
│  → writes phase1_manifest.json     │
└────────────┬───────────────────────┘
             │ manifest + bom_dir artifacts
┌────────────▼───────────────────────┐
│  CI Stage 2 (--phase spdx)         │
│  Phase 2: reads manifest            │
│  → SBOM → metadata → SPDX          │
└────────────────────────────────────┘
```

Phase 2 runs in a downstream CI stage, reducing the critical path.

#### Pattern D: Sidecar Phase 1 + Remote Phase 2 (cross-host)

```
┌──── Customer CI (sidecar) ─────┐     ┌──── Analysis Host ──────────┐
│  --mode sidecar --phase build  │     │  --phase spdx               │
│  Phase 1: build + treedb       │────▶│  --manifest ./manifest.json │
│  → manifest + artifacts        │     │  Phase 2: SPDX generation   │
└────────────────────────────────┘     └─────────────────────────────┘
```

Artifacts are transferred via `rsync`, S3, or CI artifact upload.

#### Pattern E: Corona Daemon (future extension of Pattern C/D)

```
┌──── Customer CI (sidecar) ─────┐     ┌──── Corona Service ─────────┐
│  --mode sidecar --phase build  │     │  HTTP API: POST /analyze    │
│  Phase 1: build + treedb       │────▶│  Reads manifest             │
│  → uploads manifest + artifacts│     │  Runs Phase 2 asynchronously│
│    to Corona Artifactory       │     │  Stores SPDX in SBOM DB     │
└────────────────────────────────┘     └─────────────────────────────┘
```

---

## 6. Module Design

### 6.1 New Module: `app/pipeline/manifest.py`

```python
"""
Phase 1 manifest writer and reader.

The manifest is the sole interface between Phase 1
(build interception) and Phase 2 (SPDX generation).
"""

MANIFEST_VERSION = "1.0"
MANIFEST_FILENAME = "phase1_manifest.json"


class ManifestWriter:
    """Writes phase1_manifest.json after Phase 1."""

    def write(self, bom_dir, repo_name, repo_cfg,
              paths_cfg, omnibor_cfg, run_ts,
              tracer, mode, commit_sha, vcs_uri,
              binaries):
        """Write manifest to bom_dir."""
        ...


class ManifestReader:
    """Reads phase1_manifest.json for Phase 2."""

    def read(self, manifest_path):
        """Load and validate manifest. Returns dict."""
        ...

    def verify_gitoids(self, manifest):
        """Verify artifact integrity via gitoids."""
        ...
```

**Responsibilities**:
- `ManifestWriter.write()` is called at the end of Phase 1 (after `builder.build()` succeeds).
- `ManifestReader.read()` is called at the start of Phase 2 when `--phase spdx` is specified.
- Gitoid verification is optional but recommended for cross-host transfers.

### 6.2 Modified Module: `app/pipeline/lang_runners.py`

Each language runner is refactored from one function into three:

```python
# Before (current):
def run_java_pipeline(pipeline, ..., mode="standalone"):
    # Phase 1
    build_result = pipeline.builder.build(...)
    # Phase 2
    _run_post_build(pipeline, ...)


# After (proposed):
def run_java_phase1(pipeline, ..., mode="standalone"):
    """Phase 1 only: build + treedb + manifest."""
    strategy = _select_java_strategy(...)
    build_result = pipeline.builder.build(...)
    ManifestWriter().write(...)
    return timing

def run_java_phase2(pipeline, ..., manifest=None):
    """Phase 2 only: SPDX from manifest or in-memory."""
    if manifest:
        ctx = ManifestReader().read(manifest)
    _run_post_build(pipeline, ..., ctx=ctx)
    return timing

def run_java_pipeline(pipeline, ..., mode="standalone"):
    """Both phases (backward compatible)."""
    timing1 = run_java_phase1(...)
    timing2 = run_java_phase2(...)
    return merge_timing(timing1, timing2)
```

The same pattern applies to `run_c_cpp_pipeline`, `run_go_pipeline`,
`run_rust_pipeline`. The shared `_run_post_build()` gains an optional `ctx`
parameter that provides paths from the manifest instead of constructing them
from config.

### 6.3 Modified Module: `app/pipeline/runners.py` (CLI)

```python
# New argument handling in main():

parser.add_argument(
    "--phase",
    choices=("build", "spdx"),
    default=None,
    help="Run only Phase 1 (build) or Phase 2 (spdx)",
)
parser.add_argument(
    "--manifest",
    type=str, default=None,
    help="Path to phase1_manifest.json (required with --phase spdx)",
)

# Dispatch logic:
if args.phase == "build":
    timing = run_{lang}_phase1(...)
    # Write manifest, skip Phase 2
elif args.phase == "spdx":
    if not args.manifest:
        sys.exit("--manifest required with --phase spdx")
    timing = run_{lang}_phase2(..., manifest=args.manifest)
else:
    timing = run_{lang}_pipeline(...)  # both phases
```

### 6.4 Modified Module: `app/pipeline/builder.py`

**No structural changes needed.** The builder already accepts `strategy=` and
delegates to it. The only addition is that `build()` returns the resolved
`bom_dir` path in `BuildResult` so the manifest writer can reference it.

```python
@dataclass
class BuildResult:
    success: bool = False
    steps: List[StepMetrics] = field(default_factory=list)
    bom_dir: str = ""       # NEW: for manifest writer
    repo_dir: str = ""      # NEW: for manifest writer
    binaries: List[str] = field(default_factory=list)  # NEW: resolved paths
```

### 6.5 Strategy Wiring for Non-Java Languages

Currently, only Java passes `mode` to its runner. Each language needs a
`_select_{lang}_strategy()` function:

```python
def _select_c_cpp_strategy(repo_name, repo_cfg, paths_cfg, mode):
    if mode != "sidecar":
        return None  # legacy bomtrace3 path
    return CcWrapperStrategy()

def _select_go_strategy(repo_name, repo_cfg, paths_cfg, mode):
    if mode != "sidecar":
        return None  # legacy bomtrace2 path
    return GoToolexecStrategy()

def _select_rust_strategy(repo_name, repo_cfg, paths_cfg, mode):
    if mode != "sidecar":
        return None  # legacy bomtrace2 path
    return RustcWrapperStrategy()
```

The `run_{lang}_pipeline()` functions must accept `mode=` and pass it
through, mirroring what Java already does.

---

## 7. Per-Language Phase Isolation Details

### 7.1 C/C++

#### Phase 1 Artifacts
| Artifact | Standalone | Sidecar |
|----------|-----------|---------|
| Treedb (`bomsh_omnibor_treedb`) | ✅ via `bomsh_create_bom.py` | ✅ via `bomsh_create_bom.py` (wrapper output) |
| Raw logfile | ✅ bomtrace3 writes | ✅ CC wrappers write same format |
| `bomsh_omnibor_doc_mapping` | ✅ | ✅ |
| Output binaries | ✅ in `repo_dir` | ✅ in `repo_dir` |

#### Phase 2 Requirements
| Operation | Needs Binary? | Needs Source Tree? | Needs Treedb? |
|-----------|---------------|-------------------|---------------|
| `bomsh_sbom.py` | ✅ reads binary hashes | ❌ | ✅ |
| `ldd` (dynamic deps) | ✅ | ❌ | ❌ |
| `readelf` (ELF metadata) | ✅ | ❌ | ❌ |
| `AdgSpdxGenerator` | ❌ (uses treedb) | ✅ (version detection reads source headers) | ✅ |

**Key constraint**: Phase 2 for C/C++ requires both the **binaries** and
**source tree** to remain available. For cross-host Phase 2 (Pattern C/D),
binaries must be transferred; source tree access can be replaced by pre-computing
version metadata in Phase 1 and storing it in the manifest.

#### Mitigation for Cross-Host Phase 2

Add a Phase 1 post-step: **version pre-computation**.

```python
# In Phase 1, after build succeeds:
versions = version_detector.detect_all(repo_dir, vendored_dirs)
manifest["precomputed_versions"] = versions
```

Phase 2 reads `precomputed_versions` from the manifest instead of scanning
source headers. This eliminates the source tree dependency for `AdgSpdxGenerator`.

### 7.2 Java

#### Phase 1 Artifacts
| Artifact | Standalone | Sidecar |
|----------|-----------|---------|
| Treedb (`bomsh_omnibor_treedb`) | ✅ `bomsh_create_bom_java.py` | ✅ same script |
| Strace log | ✅ strace `openat` | ❌ not needed |
| `maven_deps.json` / `gradle_deps.json` | ❌ (deps from strace) | ✅ `mvn dep:tree` / `gradlew dependencies` |
| Output JARs | ✅ in `repo_dir` | ✅ in `repo_dir` |

#### Phase 2 Requirements
| Operation | Needs JAR? | Needs Source Tree? | Needs Treedb? |
|-----------|-----------|-------------------|---------------|
| `JavaSpdxGenerator` | ❌ (only JAR path) | ❌ | ✅ |
| Maven/Gradle dep resolution | ❌ | ❌ (reads `maven_deps.json`) | ❌ |

**Java is the easiest language for cross-host Phase 2** — it does not need
binaries or source trees. The treedb + dep tree JSON are sufficient.

### 7.3 Go

#### Phase 1 Artifacts
| Artifact | Standalone | Sidecar |
|----------|-----------|---------|
| Treedb | ✅ `bomtrace2` + `bomsh_create_bom.py` | ✅ `-toolexec` wrapper + `bomsh_create_bom.py` |
| Raw logfile | ✅ | ✅ |
| Output binary | ✅ in `repo_dir` | ✅ in `repo_dir` |
| `go.sum` | ✅ (in source tree) | ✅ |

#### Phase 2 Requirements
Same as C/C++: `bomsh_sbom.py` needs binaries, `AdgSpdxGenerator` needs
treedb + source tree (for version detection).

**Go-specific note**: Go statically links all dependencies, so `ldd` returns
nothing useful. Version detection uses `go.sum` + `go.mod`, which could be
copied to the manifest as pre-computed metadata.

### 7.4 Rust

#### Phase 1 Artifacts
| Artifact | Standalone | Sidecar |
|----------|-----------|---------|
| Treedb | ✅ `bomtrace2` + `bomsh_create_bom.py` | ✅ `RUSTC_WRAPPER` + `bomsh_create_bom.py` |
| Raw logfile | ✅ | ✅ |
| Output binary | ✅ `target/release/` | ✅ `target/release/` |
| `Cargo.lock` | ✅ (in source tree) | ✅ |

#### Phase 2 Requirements
Same pattern as Go. `Cargo.lock` + `Cargo.toml` provide version/dependency
data; these can be pre-parsed in Phase 1.

### 7.5 Python (Future)

Python is metadata-only (no build tracing for pure Python). Phase 1 is
effectively `pip install` + metadata collection. Phase 2 reads `pip show`
output. This naturally separates because there is no binary artifact.

---

## 8. Corona Integration

Corona integration is a future capability where Sidecar Phase 1 uploads
artifacts to a Corona service, which runs Phase 2 asynchronously. The
phase-split architecture (manifest + artifact contract) in this document
is a prerequisite for Corona integration.

**Design details are deferred to a dedicated Corona integration design
document.** This document does not specify Corona APIs, upload protocols,
or daemon architecture.

---

## 9. Config Schema Changes

### 9.1 Nested Mode Config (already supported)

```yaml
mode: sidecar  # or standalone (default)

omnibor:
  standalone:
    tracer: bomtrace3
    create_bom_script: bomsh_create_bom.py
    sbom_script: bomsh_sbom.py
    raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1
  sidecar:
    wrapper_dir: /opt/bomsh/bin
    create_bom_script: bomsh_create_bom.py
    sbom_script: bomsh_sbom.py
```

### 9.2 New Config Fields (Phase Isolation)

```yaml
phase_isolation:
  # Whether to write phase1_manifest.json after Phase 1
  write_manifest: true  # default: true when --phase build

  # Corona integration (future — see dedicated Corona design doc)
  # corona:
  #   url: https://corona.internal/api/v1
  #   api_key_env: CORONA_API_KEY
  #   upload_timeout_sec: 300
```

### 9.3 Per-Language Sidecar Config

```yaml
omnibor_go:
  standalone:
    tracer: bomtrace2 -c /opt/bomsh/bin/bomtrace_go.conf
    create_bom_script: bomsh_create_bom.py
    sbom_script: bomsh_sbom.py
    raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1
  sidecar:
    wrapper: /opt/bomsh/bin/bomsh_hook.sh
    create_bom_script: bomsh_create_bom.py
    sbom_script: bomsh_sbom.py

omnibor_rust:
  standalone:
    tracer: bomtrace2
    create_bom_script: bomsh_create_bom.py
    sbom_script: bomsh_sbom.py
    raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1
  sidecar:
    wrapper: /opt/bomsh/bin/bomsh_hook.sh
    create_bom_script: bomsh_create_bom.py
    sbom_script: bomsh_sbom.py
```

---

## 10. Upstream `bomsh` Wrapper Requirements

The CC/CXX/AR/LD wrappers assumed by `CcWrapperStrategy` do not yet exist
in upstream bomsh. These must be contributed or developed:

| Wrapper | Purpose | Input | Output |
|---------|---------|-------|--------|
| `bomsh_cc_wrapper.sh` | Intercept `gcc`/`clang` calls | `.c` → `.o` mapping | Appends to raw logfile |
| `bomsh_cxx_wrapper.sh` | Intercept `g++`/`clang++` calls | `.cpp` → `.o` mapping | Appends to raw logfile |
| `bomsh_ar_wrapper.sh` | Intercept `ar` calls | `.o` → `.a` mapping | Appends to raw logfile |
| `bomsh_ld_wrapper.sh` | Intercept `ld` calls | `.o` → binary mapping | Appends to raw logfile |

**All wrappers must produce the same raw logfile format** as `bomtrace3` so
that `bomsh_create_bom.py` works without modification.

**Alternative**: If upstream bomsh does not provide these, `bomsh_hook2.py`
already supports a wrapper mode (`BOMSH_HOOK_PROGRAM_EMBEDDED`). The CC
wrapper scripts may simply delegate to `bomsh_hook2.py` with the right
environment variables.

For Go (`-toolexec`) and Rust (`RUSTC_WRAPPER`), `bomsh_hook2.py` already
has command-line parsers for `go tool compile/link` and `rustc`. The
wrapper scripts call `bomsh_hook2.py` before/after the real tool.

---

## 11. Docker Image Changes

### 11.1 Sidecar Image Variant

The sidecar Docker image (`Dockerfile.sidecar`) should include:

```dockerfile
# Interception tools only — NO build toolchains
COPY --from=bomsh /opt/bomsh/bin/bomsh_hook2.py /opt/bomsh/bin/
COPY --from=bomsh /opt/bomsh/bin/bomsh_create_bom.py /opt/bomsh/bin/
COPY --from=bomsh /opt/bomsh/bin/bomsh_create_bom_java.py /opt/bomsh/bin/
COPY --from=bomsh /opt/bomsh/bin/bomsh_sbom.py /opt/bomsh/bin/

# CC wrappers (once available)
COPY --from=bomsh /opt/bomsh/bin/bomsh_cc_wrapper.sh /opt/bomsh/bin/
COPY --from=bomsh /opt/bomsh/bin/bomsh_cxx_wrapper.sh /opt/bomsh/bin/
COPY --from=bomsh /opt/bomsh/bin/bomsh_ar_wrapper.sh /opt/bomsh/bin/
COPY --from=bomsh /opt/bomsh/bin/bomsh_ld_wrapper.sh /opt/bomsh/bin/

# Analysis pipeline
COPY app/ /workspace/app/
COPY scripts/ /workspace/scripts/

# NO SYS_PTRACE capability needed
```

### 11.2 Dual-Mode Container

A single image can serve both modes by detecting whether `bomtrace3` is
available at runtime:

```python
import shutil
can_ptrace = shutil.which("bomtrace3") is not None
default_mode = "standalone" if can_ptrace else "sidecar"
```

---

## 12. Testing Strategy

### 12.1 Unit Tests

| Test | Module | What it validates |
|------|--------|-------------------|
| `test_manifest_write_read` | `manifest.py` | Round-trip: write → read → identical dict |
| `test_manifest_version_check` | `manifest.py` | Rejects unsupported manifest versions |
| `test_manifest_gitoid_verify` | `manifest.py` | Detects tampered artifacts |
| `test_select_strategy_*` | `lang_runners.py` | Correct strategy for each mode × language |
| `test_phase1_writes_manifest` | `lang_runners.py` | `--phase build` produces `phase1_manifest.json` |
| `test_phase2_reads_manifest` | `lang_runners.py` | `--phase spdx` loads manifest and runs Phase 2 |
| `test_full_pipeline_unchanged` | `lang_runners.py` | No `--phase` runs both phases (backward compat) |

### 12.2 Integration Tests

| Test | Environment | What it validates |
|------|-------------|-------------------|
| `test_java_sidecar_e2e` | Docker sidecar image | Java `--mode sidecar` produces valid SPDX |
| `test_c_cpp_sidecar_e2e` | Docker sidecar image | C/C++ `--mode sidecar` produces valid SPDX |
| `test_phase_split_e2e` | Docker standalone | `--phase build` → `--phase spdx` produces same SPDX as full run |
| `test_cross_host_phase2` | Two containers | Phase 1 on host A, `rsync` artifacts, Phase 2 on host B |

### 12.3 Golden File Comparison

Every sidecar run must produce SPDX that matches the standalone golden files
(per project golden file policy). The phase-split run (`--phase build` +
`--phase spdx`) must produce **byte-identical** output to a full sequential
run (excluding timestamps in `creationInfo`).

### 12.4 Regression Tests

Add a regression test that verifies:
1. `--phase build` without `--phase spdx` does NOT produce SPDX files
2. `--phase spdx` without `--manifest` exits with error
3. `--phase spdx` with invalid manifest exits with descriptive error
4. `--phase build --baseline` is rejected (baseline is a full-build concept)

---

## 13. Implementation Plan

### Phase I: Manifest + CLI (2-3 days)

| # | Task | Files Modified | Effort |
|---|------|---------------|--------|
| 1 | Create `app/pipeline/manifest.py` (writer + reader) | New file | 0.5d |
| 2 | Add `--phase` and `--manifest` to CLI | `runners.py` | 0.5d |
| 3 | Refactor `lang_runners.py` — split Java into `phase1`/`phase2`/`pipeline` | `lang_runners.py` | 0.5d |
| 4 | Add `bom_dir` to `BuildResult` | `builder.py` | 0.25d |
| 5 | Write unit tests for manifest + phase isolation | `tests/` | 0.5d |
| 6 | Integration test: Java `--phase build` + `--phase spdx` | `tests/` | 0.5d |

**Deliverable**: Java works with `--phase build` → `--phase spdx` in the
same container. All existing tests pass unchanged.

### Phase II: Wire Sidecar Strategies (2-3 days)

| # | Task | Files Modified | Effort |
|---|------|---------------|--------|
| 7 | Wire `CcWrapperStrategy` into `run_c_cpp_pipeline` | `lang_runners.py` | 0.5d |
| 8 | Wire `GoToolexecStrategy` into `run_go_pipeline` | `lang_runners.py` | 0.5d |
| 9 | Wire `RustcWrapperStrategy` into `run_rust_pipeline` | `lang_runners.py` | 0.5d |
| 10 | Pass `mode=` through all language runners | `runners.py`, `lang_runners.py` | 0.25d |
| 11 | Convert `config.yaml` to nested mode format | `config.yaml` | 0.25d |
| 12 | Integration tests: sidecar mode per language | `tests/` | 1d |

**Deliverable**: `--mode sidecar` works for all languages (requires bomsh
wrappers for C/C++/Go/Rust — may be blocked on upstream).

### Phase III: Phase Split for All Languages (2-3 days)

| # | Task | Files Modified | Effort |
|---|------|---------------|--------|
| 13 | Split C/C++ runner into `phase1`/`phase2` | `lang_runners.py` | 0.5d |
| 14 | Split Go runner into `phase1`/`phase2` | `lang_runners.py` | 0.5d |
| 15 | Split Rust runner into `phase1`/`phase2` | `lang_runners.py` | 0.5d |
| 16 | Version pre-computation for cross-host Phase 2 | `manifest.py`, `version_detector.py` | 0.5d |
| 17 | Integration tests: phase split per language | `tests/` | 1d |

**Deliverable**: All languages support `--phase build` + `--phase spdx`.

### Phase IV: Cross-Host Phase 2 (1-2 days)

| # | Task | Files Modified | Effort |
|---|------|---------------|--------|
| 18 | Artifact packaging script (tar.gz `bom_dir` + binaries) | `scripts/` | 0.5d |
| 19 | Manifest gitoid verification on Phase 2 side | `manifest.py` | 0.5d |
| 20 | Documentation: cross-host usage guide | `docs/` | 0.5d |

**Deliverable**: Phase 2 can run on a different host from Phase 1.

### Phase V: Corona Integration (future — see dedicated design doc)

Deferred to a separate Corona integration design document. The
phase-split architecture from Phases I–IV is a prerequisite.

---

## 14. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Upstream bomsh wrappers delayed | High | Blocks sidecar for C/C++/Go/Rust | Java sidecar ships first; wrappers can be prototyped locally |
| Binary transfer size for cross-host | Medium | Large binaries (ffmpeg ~200MB) slow transfer | Compress with `zstd`; only transfer binaries needed by Phase 2 |
| Treedb path assumptions | Medium | Treedb contains absolute paths that differ across hosts | Manifest includes `repos_dir` so Phase 2 can rebase paths |
| Source tree needed for version detection | Medium | Blocks cross-host Phase 2 for C/C++ | Version pre-computation in Phase 1 (task #16) |
| Golden file divergence between modes | Low | Different SPDX from sidecar vs standalone | Same golden files for all modes (per policy); investigate any diff |
| `phase1_manifest.json` schema evolution | Low | Breaking changes between versions | Version field + backward-compatible reader |

---

## 15. Success Criteria

All three execution modes must pass independently:

### Sidecar Full (authoritative enterprise mode)
1. `--mode sidecar --repo jsoup` runs **both Phase 1 and Phase 2** without
   `SYS_PTRACE` and produces complete SPDX output.
2. Sidecar full SPDX matches standalone golden files (per golden file policy).
3. `--mode sidecar` selects the correct `InterceptionStrategy` for each
   language.

### Sidecar Phase 1 Only + Separate Phase 2
4. `--mode sidecar --phase build` produces `phase1_manifest.json` and all
   referenced artifacts, then exits without producing SPDX.
5. `--phase spdx --manifest <path>` consumes the manifest and produces
   SPDX matching the golden files — without access to `config.yaml`,
   the source tree, or the original build environment.
6. The Phase 2 executor produces **identical SPDX** whether it runs in
   the same container or on a different host.

### Standalone Full (golden file baseline + black-box builds)
7. `python3 -m app.analyze --repo curl` (no new flags) produces identical
   output to current behavior — **zero regression**.
8. Standalone remains the baseline for `omnibor-analysis` golden file
   generation and development/debug mode.

### Cross-Cutting
9. **Tests**: ≥97% overall coverage, ≥95% per file.
10. **Performance**: Phase 1 (build-only) completes within 5% of baseline
    build time (excluding Phase 2 overhead).
11. **Documentation**: Updated architecture docs, usage guide, config
    reference, and per-language design docs.

---

## 16. Appendix: File Change Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `app/pipeline/manifest.py` | **New** | Manifest writer + reader |
| `app/pipeline/runners.py` | Modify | Add `--phase`, `--manifest` args |
| `app/pipeline/lang_runners.py` | Modify | Split runners into `phase1`/`phase2`/`pipeline` |
| `app/pipeline/builder.py` | Modify | Add `bom_dir`/`repo_dir`/`binaries` to `BuildResult` |
| `app/pipeline/interception.py` | No change | Already complete |
| `app/config.py` | Modify | Add `phase_isolation` config schema |
| `app/config.yaml` | Modify | Add nested mode configs, `phase_isolation` section |
| `docker/Dockerfile.sidecar` | Modify | Add wrapper scripts |
| `tests/test_manifest.py` | **New** | Manifest unit tests |
| `tests/test_phase_isolation.py` | **New** | Phase split integration tests |
