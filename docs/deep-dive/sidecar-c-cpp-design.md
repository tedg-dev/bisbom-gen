# Sidecar & Phase Isolation — C/C++

> **Parent doc**: `sidecar-phase-isolation-infrastructure.md`
> **Status**: Design proposal — not yet implemented
> **Date**: 2026-06-12

---

> **Supported modes**: See `sidecar-phase-isolation-infrastructure.md` §1
> for the authoritative definition of Standalone and Sidecar modes.
> All modes apply to C/C++.

---

## 1. Current State

| Component | Status |
|-----------|--------|
| Standalone pipeline (`bomtrace3`) | ✅ Production — 6 repos (curl, ffmpeg, nmap, redis, openosc, node) |
| `PtraceStrategy` | ✅ Complete in `interception.py` |
| `CcWrapperStrategy` skeleton | ✅ Defined in `interception.py` — **not wired to CLI** |
| `run_c_cpp_pipeline()` | ✅ Runs Phase 1 + Phase 2 sequentially, standalone only |
| Phase 1/2 timing tags | ✅ `StepMetrics.phase` properly assigned |
| `--mode sidecar` for C/C++ | ❌ Not wired — only Java passes `mode` to its runner |

### 1.1 Current Code Path (Standalone)

```
runners.py main()
  → run_c_cpp_pipeline()
    → pipeline.validator.validate()         # apt dep check
    → pipeline.builder.build()              # Phase 1: bomtrace3 make
      ├── clean_cmd
      ├── prebuild steps (autoreconf, ./configure)
      ├── "bomtrace3 make -j$(nproc)"       # instrumented build
      └── bomsh_create_bom.py               # ADG generation
    → _run_post_build()                     # Phase 2
      ├── bomsh_sbom.py                     # OmniBOR SBOM
      ├── MetadataCollector.collect()
      ├── AdgSpdxStep.generate()            # per-binary SPDX
      ├── SpdxValidator.validate()
      └── BinaryCollector.collect()
```

### 1.2 Key Observation

`run_c_cpp_pipeline()` does **not** accept a `mode` parameter — it always
uses the legacy `bomtrace3` path (hardcoded in `builder.build()` when
`strategy=None`). The `CcWrapperStrategy` class exists but is never
instantiated by any runner.

---

## 2. Interception Strategies

### 2.1 Standalone: `PtraceStrategy` (existing)

- **Mechanism**: `bomtrace3 make -j$(nproc)` — ptrace-based syscall interception
- **Capability needed**: `SYS_PTRACE` in Docker
- **Output**: raw logfile at `/tmp/bomsh_hook_raw_logfile.sha1`
- **ADG**: `bomsh_create_bom.py -r <raw_logfile> -b <bom_dir>`

### 2.2 Sidecar: `CcWrapperStrategy` (to be wired)

- **Mechanism**: `CC=/opt/bomsh/bin/bomsh_cc_wrapper.sh`, `CXX=...`, `AR=...`, `LD=...`
- **Capability needed**: None (`SYS_PTRACE` not required)
- **Output**: same raw logfile format as `bomtrace3`
- **ADG**: same `bomsh_create_bom.py` command — wrappers produce compatible output

```python
# From interception.py — already implemented:
class CcWrapperStrategy(InterceptionStrategy):
    def instrument_command(self, build_cmd, repo_dir):
        d = self._wrapper_dir
        env = {
            "CC": f"{d}/bomsh_cc_wrapper.sh",
            "CXX": f"{d}/bomsh_cxx_wrapper.sh",
            "AR": f"{d}/bomsh_ar_wrapper.sh",
            "LD": f"{d}/bomsh_ld_wrapper.sh",
        }
        return build_cmd, env

    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        # Delegates to PtraceStrategy.generate_adg()
        # because wrapper output format is identical
        strategy = PtraceStrategy()
        return strategy.generate_adg(repo_dir, bom_dir, omnibor_cfg)
```

### 2.3 Wiring `CcWrapperStrategy` to the Pipeline

Add `_select_c_cpp_strategy()` in `lang_runners.py`:

```python
def _select_c_cpp_strategy(repo_name, repo_cfg, paths_cfg, mode):
    """Select interception strategy for C/C++ builds.

    In sidecar mode, uses CC/CXX/AR/LD wrappers that
    avoid ptrace entirely.

    In standalone mode, returns None (legacy bomtrace3 path).
    """
    if mode != "sidecar":
        return None
    from app.pipeline.interception import CcWrapperStrategy
    return CcWrapperStrategy()
```

Modify `run_c_cpp_pipeline()` to accept `mode=`:

```python
def run_c_cpp_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_cfg, run_ts,
    vcs_uri="NOASSERTION",
    mode="standalone",        # NEW
):
    strategy = _select_c_cpp_strategy(
        repo_name, repo_cfg, paths_cfg, mode,
    )
    ...
    # In Phase 1:
    if strategy:
        build_result = pipeline.builder.build(
            ..., strategy=strategy,
        )
    else:
        build_result = pipeline.builder.build(
            ...,  # legacy path, strategy=None
        )
```

---

## 3. Phase 1 Artifacts

| Artifact | Standalone | Sidecar | Location |
|----------|-----------|---------|----------|
| Raw logfile | ✅ `bomtrace3` writes | ✅ CC wrappers write same format | `/tmp/bomsh_hook_raw_logfile.sha1` |
| Treedb (`bomsh_omnibor_treedb`) | ✅ `bomsh_create_bom.py` | ✅ same script (wrapper output) | `bom_dir/metadata/bomsh/` |
| `bomsh_omnibor_doc_mapping` | ✅ | ✅ | `bom_dir/metadata/bomsh/` |
| `bomsh_hook_raw_logfile` (archived) | ✅ | ✅ | `bom_dir/metadata/bomsh/` |
| Output binaries (ELF) | ✅ in `repo_dir` | ✅ in `repo_dir` | Per `output_binaries` config |
| `phase1_manifest.json` | ✅ (when `--phase build`) | ✅ | `bom_dir/phase1_manifest.json` |

---

## 4. Phase 2 Requirements

| Operation | Module | Needs Binary? | Needs Source Tree? | Needs Treedb? |
|-----------|--------|---------------|-------------------|---------------|
| `bomsh_sbom.py` | `spdx_generator.py` | ✅ reads binary hashes | ❌ | ✅ |
| `ldd` (dynamic deps) | `adg_spdx.py` via `AdgSpdxGenerator` | ✅ | ❌ | ❌ |
| `readelf` (ELF metadata) | `adg_spdx.py` via `AdgSpdxGenerator` | ✅ | ❌ | ❌ |
| `AdgSpdxGenerator` (per-binary SPDX) | `adg_spdx.py` | ❌ | ✅ (version detection) | ✅ |
| `MetadataCollector` | `metadata_collector.py` | ❌ | ✅ (repo metadata) | ❌ |
| `BinaryCollector` | `binary_collector.py` | ✅ (copies binaries) | ❌ | ❌ |

### 4.1 Source Tree Dependency for Version Detection

The `AdgSpdxGenerator` calls `version_detector.py` which scans source
headers (`VERSION`, `configure.ac`, `CMakeLists.txt`, `#define` macros) to
detect vendored library versions. This is the **primary reason** Phase 2
needs the source tree for C/C++.

**Mitigation for cross-host Phase 2**: Pre-compute versions in Phase 1
and include them in the manifest:

```python
# Phase 1 post-step:
from app.spdx.version_detector import detect_version_from_source
versions = {}
for vdir in repo_cfg.get("vendored_dirs", []):
    ver = detect_version_from_source(repo_dir, vdir)
    if ver:
        versions[vdir] = ver
manifest["precomputed_versions"] = versions
```

Phase 2 reads `precomputed_versions` from the manifest, bypassing source
tree scanning.

### 4.2 Binary Dependency

`bomsh_sbom.py`, `ldd`, and `readelf` all require the actual ELF binaries.
For cross-host Phase 2, these must be transferred alongside the manifest.

Expected binary sizes for configured repos:

| Repo | Binary | Approximate Size |
|------|--------|-----------------|
| curl | `src/.libs/curl` + `lib/.libs/libcurl.so` | ~5 MB |
| ffmpeg | 9 binaries/libraries | ~200 MB |
| nmap | `nmap` + `ncat` + `nping` | ~15 MB |
| redis | `redis-server` + `redis-cli` | ~10 MB |
| openosc | `libopenosc.so` | ~1 MB |
| node | `out/Release/node` | ~80 MB |

**Recommendation**: Compress with `zstd` for cross-host transfer. ffmpeg and
node are the only repos where binary size is a concern.

---

## 5. Config Schema

### 5.1 Current (flat format — standalone only)

```yaml
omnibor:
  tracer: bomtrace3
  create_bom_script: bomsh_create_bom.py
  sbom_script: bomsh_sbom.py
  raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1
```

### 5.2 Target (nested mode format)

```yaml
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

`resolve_omnibor_cfg()` in `config.py` already handles both formats — the
nested format auto-selects based on `config["mode"]`.

---

## 6. Upstream `bomsh` Wrapper Requirements

The CC/CXX/AR/LD wrappers assumed by `CcWrapperStrategy` **do not yet exist
in upstream bomsh**. These must be contributed or developed.

| Wrapper | Purpose | Intercepts | Output |
|---------|---------|-----------|--------|
| `bomsh_cc_wrapper.sh` | Wrap `gcc`/`clang` | `.c` → `.o` compilation | Appends to raw logfile |
| `bomsh_cxx_wrapper.sh` | Wrap `g++`/`clang++` | `.cpp` → `.o` compilation | Appends to raw logfile |
| `bomsh_ar_wrapper.sh` | Wrap `ar` | `.o` → `.a` archiving | Appends to raw logfile |
| `bomsh_ld_wrapper.sh` | Wrap `ld`/`gold`/`lld` | `.o` → binary linking | Appends to raw logfile |

### 6.1 Implementation Approach

**Option A**: Shell scripts that call `bomsh_hook2.py` in embedded mode:

```bash
#!/bin/bash
# bomsh_cc_wrapper.sh
REAL_CC=$(which gcc)  # or detect from PATH minus wrapper dir
bomsh_hook2.py --hook-program "$REAL_CC" "$@"
```

`bomsh_hook2.py` already has logic to parse GCC command lines
(`get_all_subfiles_in_gcc_cmdline`) and record input/output file mappings.
The wrapper just needs to invoke it with the correct arguments.

**Option B**: `bomsh_hook2.py` natively supports `BOMSH_HOOK_PROGRAM_EMBEDDED`
environment variable. Set it to the real compiler path, then invoke
`bomsh_hook2.py` as if it were the compiler:

```bash
#!/bin/bash
export BOMSH_HOOK_PROGRAM_EMBEDDED=$(which gcc)
exec bomsh_hook2.py "$@"
```

**All wrappers must produce the same raw logfile format** as `bomtrace3` so
that `bomsh_create_bom.py` works without modification.

### 6.2 Build System Compatibility

| Build System | `CC=` Support | Notes |
|-------------|--------------|-------|
| autoconf/make | ✅ Native | `./configure CC=wrapper` or env var |
| CMake | ✅ via `-DCMAKE_C_COMPILER=` | Or env `CC=` before cmake |
| Meson | ✅ via `--native-file` or env | Cross-file or `CC=` |
| Plain Makefile | ✅ if Makefile uses `$(CC)` | Most do; some hardcode `gcc` |

**Risk**: Some Makefiles hardcode `gcc`/`g++` instead of using `$(CC)`/`$(CXX)`.
For those repos, sidecar mode will miss compilation events. Mitigation: document
per-repo compatibility in `config.yaml` with a `sidecar_compatible: true/false`
field.

---

## 7. Phase Split Design

### 7.1 `run_c_cpp_phase1()`

```python
def run_c_cpp_phase1(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_cfg, run_ts,
    mode="standalone",
    vcs_uri="NOASSERTION",
    commit_sha=None,
):
    """C/C++ Phase 1: validate → build → treedb → manifest.

    Returns TimingResult with Phase 1 steps only.
    """
    strategy = _select_c_cpp_strategy(
        repo_name, repo_cfg, paths_cfg, mode,
    )
    tracer = strategy.name if strategy else "bomtrace3"
    timing = TimingResult(tracer=tracer)

    # Validate apt dependencies
    deps_ok, missing = pipeline.validator.validate(repo_cfg)
    if not deps_ok:
        ...

    # Build (Phase 1)
    build_result = pipeline.builder.build(
        repo_name, repo_cfg, paths_cfg, omnibor_cfg,
        run_ts=run_ts, strategy=strategy,
    )
    timing.steps.extend(build_result.steps)
    timing.success = build_result.success

    if build_result.success:
        # Write manifest for Phase 2
        ManifestWriter().write(
            bom_dir=build_result.bom_dir,
            repo_name=repo_name,
            repo_cfg=repo_cfg,
            paths_cfg=paths_cfg,
            omnibor_cfg=omnibor_cfg,
            run_ts=run_ts,
            tracer=tracer,
            mode=mode,
            commit_sha=commit_sha,
            vcs_uri=vcs_uri,
            binaries=build_result.binaries,
        )

    return timing
```

### 7.2 `run_c_cpp_phase2()`

```python
def run_c_cpp_phase2(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_cfg, run_ts,
    vcs_uri="NOASSERTION",
    manifest=None,
):
    """C/C++ Phase 2: SBOM → metadata → SPDX → validate → collect.

    When manifest is provided, reads paths from it.
    Otherwise uses the same in-memory paths as today.

    Returns TimingResult with Phase 2 steps only.
    """
    if manifest:
        ctx = ManifestReader().read(manifest)
        # Override paths from manifest
        ...

    timing = TimingResult(tracer="phase2-only")
    timing.steps.extend(
        _run_post_build(
            pipeline, repo_name, repo_cfg,
            paths_cfg, run_ts,
            sbom_fn=lambda: pipeline.spdx_gen.generate(...),
            spdx_gen_fn=lambda: pipeline.adg_spdx.generate(...),
        )
    )
    timing.success = True
    return timing
```

### 7.3 `run_c_cpp_pipeline()` (backward compatible)

```python
def run_c_cpp_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_cfg, run_ts,
    vcs_uri="NOASSERTION",
    mode="standalone",
):
    """C/C++ full pipeline: Phase 1 + Phase 2.

    Backward compatible — identical behavior to current code.
    """
    # Phase 1
    timing = run_c_cpp_phase1(
        pipeline, repo_name, repo_cfg,
        paths_cfg, omnibor_cfg, run_ts,
        mode=mode, vcs_uri=vcs_uri,
    )
    if not timing.success:
        return timing

    # Phase 2
    timing2 = run_c_cpp_phase2(
        pipeline, repo_name, repo_cfg,
        paths_cfg, omnibor_cfg, run_ts,
        vcs_uri=vcs_uri,
    )
    timing.steps.extend(timing2.steps)
    return timing
```

---

## 8. Testing

### 8.1 Unit Tests

| Test | What it validates |
|------|-------------------|
| `test_select_c_cpp_strategy_standalone` | Returns `None` (legacy path) |
| `test_select_c_cpp_strategy_sidecar` | Returns `CcWrapperStrategy` |
| `test_cc_wrapper_instrument_command` | Correct `CC`/`CXX`/`AR`/`LD` env vars |
| `test_cc_wrapper_generate_adg` | Delegates to `PtraceStrategy.generate_adg()` |
| `test_c_cpp_phase1_writes_manifest` | `--phase build` produces `phase1_manifest.json` |
| `test_c_cpp_phase2_reads_manifest` | `--phase spdx --manifest ...` runs Phase 2 |
| `test_c_cpp_pipeline_unchanged` | No `--phase` runs both phases identically |

### 8.2 Integration Tests (EC2)

| Test | Command | Validates |
|------|---------|-----------|
| Standalone full | `--repo curl` | Current behavior unchanged |
| Sidecar full | `--repo curl --mode sidecar` | CC wrappers produce valid SPDX |
| Phase split | `--repo curl --phase build` then `--phase spdx` | Output matches standalone golden |
| Golden comparison | All modes | SPDX matches standalone golden files |

### 8.3 Build System Compatibility Matrix

Test sidecar mode against all 6 C/C++ repos:

| Repo | Build System | `$(CC)` Used? | Sidecar Compatible? |
|------|-------------|--------------|---------------------|
| curl | autoconf/make | ✅ | ✅ Expected |
| ffmpeg | custom configure/make | ✅ | ✅ Expected |
| nmap | autoconf/make | ✅ | ✅ Expected |
| redis | plain Makefile | ✅ (uses `$(CC)`) | ✅ Expected |
| openosc | autoconf/make | ✅ | ✅ Expected |
| node | GYP/make + custom | ⚠️ Verify | ⚠️ May need testing |

---

## 9. Implementation Tasks

| # | Task | Effort | Depends On |
|---|------|--------|------------|
| 1 | Add `mode=` param to `run_c_cpp_pipeline()` | 0.25d | — |
| 2 | Implement `_select_c_cpp_strategy()` | 0.25d | — |
| 3 | Pass `mode` from `runners.py` → `run_c_cpp_pipeline()` | 0.25d | Task 1 |
| 4 | Split into `run_c_cpp_phase1()` / `run_c_cpp_phase2()` | 0.5d | Infra manifest module |
| 5 | Verify/develop upstream bomsh CC wrappers | 2-3d | External dependency |
| 6 | Add version pre-computation for cross-host Phase 2 | 0.5d | Task 4 |
| 7 | Convert `config.yaml` `omnibor:` to nested format | 0.25d | — |
| 8 | Unit tests | 0.5d | Tasks 1-4 |
| 9 | Integration tests on EC2 (sidecar mode) | 1d | Task 5 |
| 10 | Golden file comparison for sidecar output | 0.5d | Task 9 |

**Critical path blocker**: Task 5 (upstream bomsh wrappers). Without the
wrappers, `CcWrapperStrategy` cannot be tested end-to-end. The wiring
(tasks 1-4, 6-8) can proceed in parallel.

---

## 10. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Upstream bomsh wrappers delayed | **High** | Blocks sidecar E2E testing | Prototype wrappers locally; ship Java sidecar first |
| Makefile hardcodes `gcc` | Medium | Some repos miss compilation events | Document per-repo; add `sidecar_compatible` config field |
| Binary transfer size (ffmpeg, node) | Medium | Slow cross-host Phase 2 | `zstd` compression; only transfer what Phase 2 needs |
| Source tree needed for version detection | Medium | Blocks cross-host Phase 2 | Version pre-computation in Phase 1 manifest |
| `libtool` relinking changes binary hash | Low | `bomsh_sbom.py` `ExternalRef` injection fails | Already mitigated by `_inject_omnibor_refs()` in `spdx_generator.py` |
