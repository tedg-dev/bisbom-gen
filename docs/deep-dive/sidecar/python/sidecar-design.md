# Sidecar & Phase Isolation — Python

> **Parent doc**: `../../../features/phase-isolation/sidecar-phase-isolation-infrastructure.md`
> **Status**: Future — no pipeline exists yet
> **Date**: 2026-06-12
> **Prerequisite**: `docs/architecture/python-omnibor-support-analysis.md`

---

> **Supported modes**: See `../../../features/phase-isolation/sidecar-phase-isolation-infrastructure.md` §1
> for the authoritative definition of Standalone and Sidecar modes.
> All modes apply to Python.

---

## 1. Current State

| Component | Status |
|-----------|--------|
| Python pipeline | ❌ Not implemented |
| Python interception strategy | ❌ Not defined |
| Python repos in `config.yaml` | ❌ None configured |
| `bomsh_pylib.py` (upstream) | ⚠️ Exists but has gaps (see analysis doc) |

Python is **fundamentally different** from the other four languages:
- Pure Python packages have no compiled binaries to trace
- Dependencies are declared in `pyproject.toml`/`setup.py`/`requirements.txt`
  and resolved by `pip`
- C extension modules (via `setuptools`, `maturin`, `scikit-build`) are the
  only compilation events worth tracing

The Python pipeline is **metadata-only for pure Python** and
**strace/wrapper-based for C extensions**.

---

## 2. Interception Strategies

### 2.1 Metadata-Only (Pure Python)

- **Mechanism**: `pip install` + `pip show` / `importlib.metadata`
- **Capability needed**: None
- **Output**: Package metadata (name, version, license, dependencies)
- **No build tracing**: Pure Python has no compilation step

This is inherently a sidecar-compatible approach — no `SYS_PTRACE` needed.

### 2.2 Strace (C Extensions — Standalone)

- **Mechanism**: `strace -f pip install` to capture C compilation via
  `setuptools`/`distutils`
- **Capability needed**: `SYS_PTRACE` in Docker
- **Output**: strace log showing `gcc`/`g++` invocations for `.c` → `.so`
- **ADG**: `bomsh_create_bom.py` on strace output (same as Java standalone)

### 2.3 CC Wrapper (C Extensions — Sidecar)

- **Mechanism**: Same `CC=`/`CXX=` wrappers as C/C++ sidecar, but applied
  during `pip install` of packages with C extensions
- **Capability needed**: None
- **Output**: Same raw logfile format
- **Dependency**: Requires the C/C++ CC wrappers (shared with `CcWrapperStrategy`)

### 2.4 Proposed Strategy Class

```python
class PythonMetadataStrategy(InterceptionStrategy):
    """Python: metadata-only, no build tracing.

    For pure Python packages, dependencies are fully
    described by pip metadata. No compilation to trace.
    """

    @property
    def name(self):
        return "python-metadata"

    def instrument_command(self, build_cmd, repo_dir):
        # pip install runs unmodified
        return build_cmd, {}

    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        # Parse pip metadata instead of treedb
        from app.pipeline.pip_metadata_parser import (
            collect_pip_metadata,
        )
        metadata = collect_pip_metadata(repo_dir)
        # Write to bom_dir as JSON
        ...
        return True
```

---

## 3. Phase 1 Artifacts

| Artifact | Pure Python | C Extension (standalone) | C Extension (sidecar) |
|----------|------------|------------------------|----------------------|
| `pip_metadata.json` | ✅ | ✅ | ✅ |
| Strace log | ❌ | ✅ | ❌ |
| Raw logfile (CC wrappers) | ❌ | ❌ | ✅ |
| Treedb | ❌ | ✅ (C compilation) | ✅ (C compilation) |
| `.so` extension modules | ❌ | ✅ | ✅ |
| `requirements.txt` / `pyproject.toml` | ✅ | ✅ | ✅ |
| `phase1_manifest.json` | ✅ | ✅ | ✅ |

---

## 4. Phase 2 Requirements

| Operation | Needs Binary? | Needs Source Tree? | Needs Treedb? |
|-----------|---------------|-------------------|---------------|
| SPDX from pip metadata | ❌ | ❌ | ❌ |
| SPDX for C extensions | ✅ (`.so` files) | ❌ | ✅ |
| `ldd` on `.so` extensions | ✅ | ❌ | ❌ |

**Python is the easiest language for cross-host Phase 2** for pure packages.
`pip_metadata.json` is the only required artifact.

---

## 5. SPDX Relationship Mapping

| Python Concept | SPDX Relationship |
|---------------|-------------------|
| Direct `install_requires` dependency | `DEPENDS_ON` |
| Transitive dependency | `DEPENDS_ON` (via pip resolver) |
| C extension `.so` | `CONTAINED_BY` (part of the package) |
| Build tool (`setuptools`, `wheel`) | `BUILD_TOOL_OF` |
| `extras_require` optional dep | `OPTIONAL_DEPENDENCY_OF` |

---

## 6. Implementation Plan

Python is Phase V (future) in the overall implementation plan. Prerequisites:

1. **Phase I-III complete** — manifest infrastructure, CLI changes, and
   phase split for existing languages must be stable
2. **`bomsh_pylib.py` gaps addressed** — upstream script needs fixes for
   import side effects and missing metadata fields (see analysis doc)
3. **Test Python project identified** — need a representative open-source
   Python project with C extensions for integration testing

### 6.1 Proposed Implementation Phases

| Phase | Scope | Effort | Dependency |
|-------|-------|--------|------------|
| MVP | Metadata-only SPDX for pure Python (`pip show` → SPDX) | 2 weeks | None |
| Phase 2 | strace integration for C extension tracing | 1 week | Standalone Docker |
| Phase 3 | `bomsh_pylib.py` improvements (no import side effects) | 1 week | Upstream bomsh |
| Phase 4 | Advanced: maturin/Rust extensions, Fortran, editable installs | TBD | Per-case |

### 6.2 MVP Scope

The MVP produces SPDX for pure Python packages without any build tracing:

```python
def run_python_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_python_cfg, run_ts,
    vcs_uri="NOASSERTION",
    mode="standalone",  # mode is irrelevant for pure Python
):
    # Phase 1: pip install + metadata collection
    timing = run_python_phase1(...)
    if not timing.success:
        return timing
    # Phase 2: SPDX generation from metadata
    timing2 = run_python_phase2(...)
    timing.steps.extend(timing2.steps)
    return timing
```

---

## 7. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `pip show` metadata incomplete | Medium | Missing dependencies in SPDX | Cross-validate with `pip freeze` and `importlib.metadata` |
| C extension detection unreliable | Medium | Miss compiled `.so` files | Scan `site-packages` for `.so` files post-install |
| Virtual environment isolation | Low | Wrong packages detected | Always use dedicated venv for analysis |
| `bomsh_pylib.py` import side effects | Known | Scripts execute on import | Fix upstream or bypass with metadata-only approach |
| Editable installs (`pip install -e`) | Low | Different file layout | Detect and handle separately |

---

## 8. Testing

Integration testing for Python will use a representative project:
- **Pure Python**: A project with only Python dependencies (e.g., `requests`,
  `click`-based CLI tool)
- **C Extension**: A project with compiled extensions (e.g., `lxml`, `numpy`)

Unit tests will mock `pip show` output and verify SPDX generation from
metadata JSON.
