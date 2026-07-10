# Sidecar & Phase Isolation — C/C++

|  |  |
|---|---|
| **Parent doc** | `../infrastructure.md` |
| **Reference guide** | `sidecar-interception-strategies.md` — strategy analysis, coverage matrices, and the enterprise OS/kernel landscape |
| **Status** | Design proposal — not yet implemented |
| **Date** | 2026-06-12 (updated 2026-07-01: consolidated the PR #94 revision; compiler wrappers re-labeled standalone-without-ptrace) |

---

> **Supported modes**: See `../infrastructure.md` §1
> for the authoritative definition of Standalone and Sidecar modes.
> All modes apply to C/C++.
>
> **Interception model**: The truly-sidecar C/C++ mechanism is transparent
> kernel/linker interception — `LD_PRELOAD` (primary) → eBPF (secondary) →
> per-repo `ptrace` (tertiary). Compiler-wrapper injection
> (`CC=`/`CXX=`/`AR=`/`LD=`, `CcWrapperStrategy`) **modifies the build
> invocation** and is therefore a **standalone-without-ptrace** option,
> *not* sidecar. See §2.

---

## Architecture Diagram

<a href="c-cpp-sidecar-mode.png"><img src="c-cpp-sidecar-mode.png" width="600" alt="C/C++ Sidecar Mode Architecture — click to enlarge"></a>

*Click image to enlarge. Source: [c-cpp-sidecar-mode.drawio](c-cpp-sidecar-mode.drawio)*

---

## 1. Current State

| Component | Status |
|-----------|--------|
| Standalone pipeline (`bomtrace3`) | ✅ Production — 6 repos (curl, ffmpeg, nmap, redis, openosc, node) |
| `PtraceStrategy` | ✅ Complete in `interception.py` |
| `CcWrapperStrategy` skeleton (standalone-without-ptrace) | ✅ Defined in `interception.py` — **not wired to CLI**; *not* a sidecar mechanism (see §2.6) |
| `LdPreloadStrategy` / `EbpfStrategy` (truly-sidecar) | ❌ Not implemented — see §2.3–2.4 |
| `run_c_cpp_pipeline()` | ✅ Runs Phase 1 + Phase 2 sequentially, standalone only |
| Phase 1/2 timing tags | ✅ `StepMetrics.phase` properly assigned |
| `--mode sidecar` for C/C++ | ❌ Not wired — only Java passes `mode` to its runner |

### 1.1 Current Code Path (Standalone)

`runners.py main()` calls `run_c_cpp_pipeline()`, which runs:

1. **Phase 1**
   - `pipeline.validator.validate()` — apt dependency check
   - `pipeline.builder.build()` — instrumented build:
     - `clean_cmd`
     - prebuild steps (`autoreconf`, `./configure`)
     - `bomtrace3 make -j$(nproc)` — instrumented build
     - `bomsh_create_bom.py` — ADG generation
2. **Phase 2** — `_run_post_build()`
   - `bomsh_sbom.py` — OmniBOR SBOM
   - `MetadataCollector.collect()`
   - `AdgSpdxStep.generate()` — per-binary SPDX
   - `SpdxValidator.validate()`
   - `BinaryCollector.collect()`

### 1.2 Key Observation

`run_c_cpp_pipeline()` does **not** accept a `mode` parameter — it always
uses the legacy `bomtrace3` path (hardcoded in `builder.build()` when
`strategy=None`). The `CcWrapperStrategy` class exists but is never
instantiated by any runner.

---

## 2. Interception Strategies

C/C++ is the hardest sidecar case and the most important — legacy
enterprise platforms are overwhelmingly C/C++. Getting the phase-isolation
model right here is the priority. Full strategy analysis, coverage
matrices, and the enterprise OS/kernel landscape live in the reference
guide `sidecar-interception-strategies.md`.

### 2.1 Strategy taxonomy

| Category | Strategies | Modifies build invocation? | Mode |
|---|---|---|---|
| **Standalone (ptrace)** | `PtraceStrategy` (`bomtrace3`/`bomtrace2`) | No (wraps the *runner*, needs `SYS_PTRACE`) | standalone |
| **Standalone (no ptrace)** | `CcWrapperStrategy` (`CC=`/`CXX=`/`AR=`/`LD=`) | **Yes** (sets build env vars) | standalone alt — **not sidecar** |
| **Sidecar (transparent)** | `LdPreloadStrategy`, `EbpfStrategy` | **No** (kernel/linker-level, injected by infra) | sidecar |

Key correction: env-var/wrapper injection is a useful **standalone**
option, but it is explicitly **not** a sidecar mechanism. The sidecar must
intercept at the kernel or dynamic-linker level, transparent to the build
system (industry precedent: Istio, Dynatrace, and Vault all inject via
mutating webhooks + `LD_PRELOAD`).

### 2.2 Three-tier sidecar model

| Tier | Mechanism | Coverage | In-band overhead | Static binaries? | Build modification |
|---|---|---|---|---|---|
| **Primary** | `LD_PRELOAD` shim injected by K8s mutating webhook (init container + shared `emptyDir`) | ~80% — all dynamically-linked builds, any build system | +1–3% | No | None |
| **Secondary** | Node-level **eBPF** DaemonSet on kernel tracepoints | All languages incl. statically-linked | Minimal kernel cost | Yes | None |
| **Tertiary** | Per-repo `interception: ptrace` override (`bomtrace3`) | Hermetic builds (Bazel, Nix, Yocto) | 20–60% (ptrace) | Yes | None (needs `SYS_PTRACE`) |

Resolution order: per-repo `interception` override > global `mode` >
default. Hermetic build systems opt into the tertiary tier per-project
without affecting others.

### 2.3 Primary tier — `LD_PRELOAD` shim

A small shared library (`libomnibor_intercept.so`) is injected via
`LD_PRELOAD`, set by infrastructure (a K8s `MutatingAdmissionWebhook` +
init container that copies the shim into a shared volume), never by the
build command. The shim interposes `execve`, `open`/`openat`, and `close`
to:

1. Record each compiler/linker `argv` to the raw-logfile format consumed
   by `bomsh_create_bom.py`.
2. Hash compilation inputs and outputs **inline** (gitoid), keeping the
   data on the build's critical path minimal.
3. `exec()` the real tool so the build environment is otherwise identical.

Failure isolation: the shim must never fail the customer build — on any
internal error it logs and lets the real tool proceed; the SBOM is
reported incomplete rather than the build broken.

### 2.4 Secondary tier — eBPF node DaemonSet

For statically-linked builds (where `LD_PRELOAD` cannot interpose) the
secondary tier runs a privileged DaemonSet loading eBPF programs on
`sched_process_exec`, `sched_process_exit`, and `sys_enter_openat`. It
observes compiler invocations system-wide with no pod modification. The
`sched_process_exit` tracepoint also provides reliable **build-completion
detection** for the post-build capture window. Requires `CAP_BPF` /
`CAP_SYS_ADMIN` on the DaemonSet.

### 2.5 Tertiary tier — per-repo `ptrace` override

For hermetic build systems that defeat both `LD_PRELOAD` and eBPF, a
per-repo `interception: ptrace` setting falls back to the existing
`PtraceStrategy` (`bomtrace3`), reusing the production standalone ADG path
unchanged. The `build_system` field is recorded in the SPDX `creationInfo`
comment for traceability.

### 2.6 `CcWrapperStrategy` — standalone-without-ptrace (not sidecar)

The implemented `CcWrapperStrategy` (`@app/pipeline/interception.py`) sets
`CC`/`CXX`/`AR`/`LD` to OmniBOR wrapper scripts. This works without
`SYS_PTRACE`, but it **changes the build command's environment**, which the
sidecar model forbids. It is retained as a valid
**standalone-without-ptrace** option for environments that cannot use
ptrace and can tolerate a build-env change. Its ADG step reuses
`PtraceStrategy.generate_adg()` because the raw-logfile format is identical.

Approaches ruled out by the zero-modification (sidecar) constraint:

| Approach | Why not sidecar |
|---|---|
| `CC=/opt/omnibor/gcc-wrapper make` | Sets a build env var (changes invocation) |
| `bear -- make`, `cov-build make` | Wraps/changes the build command |
| `RUSTC_WRAPPER=`, `go build -toolexec=` | Requires env/flag on the build command |
| Makefile / lifecycle hooks | Modifies the project's build config |

```python
# From interception.py — retained as a standalone-without-ptrace option:
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
        # Delegates to PtraceStrategy.generate_adg() — identical
        # raw-logfile format.
        strategy = PtraceStrategy()
        return strategy.generate_adg(repo_dir, bom_dir, omnibor_cfg)
```

### 2.7 Wiring the sidecar strategy to the pipeline

`_select_c_cpp_strategy()` in `lang_runners.py` selects the transparent
sidecar strategy (primary `LD_PRELOAD`), falling back to the legacy
standalone `bomtrace3` path when not in sidecar mode:

```python
def _select_c_cpp_strategy(repo_name, repo_cfg, paths_cfg, mode):
    """Select interception strategy for C/C++ builds.

    Sidecar mode uses transparent kernel/linker interception
    (LD_PRELOAD primary; eBPF or per-repo ptrace per tier).
    Standalone mode returns None (legacy bomtrace3 path).
    """
    if mode != "sidecar":
        return None
    # Per-repo `interception` override selects the tier; default primary.
    from app.pipeline.interception import LdPreloadStrategy
    return LdPreloadStrategy()  # pending implementation
```

`run_c_cpp_pipeline()` accepts a `mode=` parameter and passes the selected
strategy into Phase 1 (see §7 for the full phase-split signatures).

---

## 3. Phase 1 Artifacts

| Artifact | Standalone | Sidecar | Location |
|----------|-----------|---------|----------|
| Raw logfile | ✅ `bomtrace3` writes | ✅ `LD_PRELOAD` shim (or eBPF) writes same format | `/tmp/bomsh_hook_raw_logfile.sha1` |
| Treedb (`bomsh_omnibor_treedb`) | ✅ `bomsh_create_bom.py` | ✅ same script (from `LD_PRELOAD`/eBPF capture) | `bom_dir/metadata/bomsh/` |
| `bomsh_omnibor_doc_mapping` | ✅ | ✅ | `bom_dir/metadata/bomsh/` |
| `bomsh_hook_raw_logfile` (archived) | ✅ | ✅ | `bom_dir/metadata/bomsh/` |
| Output binaries (ELF) | ✅ in `repo_dir` | ✅ in `repo_dir` | Per `output_binaries` config |
| `phase1_manifest.json` | ✅ (when `--phase build`) | ✅ | `bom_dir/phase1_manifest.json` |

---

## 4. Phase 2 Requirements

| Operation | Module | Needs Binary? | Needs Source Tree? | Needs Treedb? |
|-----------|--------|---------------|-------------------|---------------|
| `bomsh_sbom.py` (re-hashes artifacts) | `spdx_generator.py` | ✅ re-hashes via `-F` | ❌ | ✅ |
| `collect_dynamic_libs.py` (`ldd`/`readelf`) | `metadata_collector.py` (`MetadataCollector`) | ✅ to **produce** `dynamic_libs.json` | ❌ | ❌ |
| `AdgSpdxGenerator` (per-binary SPDX) | `spdx/generator.py` | ❌ reads `dynamic_libs.json` | ✅ (version detection) | ✅ |
| OmniBOR `ExternalRef` injection | `spdx_generator._inject_omnibor_refs` | ❌ reads raw logfile + `doc_mapping` | ❌ | ✅ |
| `BinaryCollector` (archival copy) | `binary_collector.py` | ✅ copies binaries | ❌ | ❌ |

Only `bomsh_sbom.py` and the `ldd`/`readelf` capture actually read the
binary; the SPDX assembly and `ExternalRef` injection are already
metadata-driven. See §4.2 for why the binary-reading steps belong in
Phase 1.

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

### 4.2 Binary-derived facts belong in Phase 1 (not Phase 2)

The phase boundary is defined by **the binary**, not by "hashing vs
assembly": any step that reads the binary must run where the binary is
guaranteed present — the Phase-1 capture window in the ephemeral build
environment. `bomsh_sbom.py` re-hashing the artifact at Phase 2 is a
**standalone-mode assumption** that must not cross into the sidecar phase
split, because:

1. **Phase 1 already hashes the binary.** The raw logfile records
   `outfile: <sha1> path: <path>` (`_inject_omnibor_refs`), and
   `bomsh_omnibor_doc_mapping` maps `sha1 → OmniBOR doc id`. The full
   `binary → gitoid → ADG-doc-id` chain is already resolved in Phase-1
   artifacts; re-hashing at Phase 2 is redundant.
2. **No artifact-derived fact needs Phase 2.** bomsh's `SHA-1` treedb/gitoid
   (ADG topology lookup only), the raw `SHA-256` + `SHA-256` gitOID that the
   SBOM surfaces, size, ELF metadata (`readelf`), and dynamic deps
   (`ldd` → `dynamic_libs.json`) are all Phase-1-capturable. The `SHA-256`
   identity is computed by reading each artifact while it still exists at
   Phase 1 (bomsh's `SHA-1` values never surface in the SBOM). See the design
   of record: `.windsurf/rules/project/artifact-identity.md`.
3. **Binaries are often proprietary customer IP** — egressing them to S3 or
   an analysis host is a data-exfiltration surface (CWE-200). Capturing
   facts in Phase 1 keeps binaries on the build host.

**Resolution — two ways to draw the line:**

| | Binary-facts captured | SPDX document assembled | Upstream change | Binary egress |
|---|---|---|---|---|
| **Pilot** | Phase 1 | **Phase 1** (run `bomsh_sbom.py` in capture window) | None | None |
| **Future** | Phase 1 (structured map) | Phase 2 (assemble from treedb + map) | small Phase-2 assembler *or* upstream `bomsh` flag to accept precomputed gitoids | None |

Adopt the **pilot** first: `bomsh_sbom.py` runs in the Phase-1 capture
window (treedb `-b` and binaries `-F` are both local there), emits the
small per-artifact SPDX + metadata, and Phase 2 does only the
metadata-driven merge/patch/validate it already performs. This eliminates
the binary dependency with **zero upstream work and zero binary egress**.
This supersedes any notion that Phase 2 must transfer binaries.

For reference, the binary sizes that this avoids shipping:

| Repo | Binary | Approximate Size |
|------|--------|-----------------|
| curl | `src/.libs/curl` + `lib/.libs/libcurl.so` | ~5 MB |
| ffmpeg | 9 binaries/libraries | ~200 MB |
| nmap | `nmap` + `ncat` + `nping` | ~15 MB |
| redis | `redis-server` + `redis-cli` | ~10 MB |
| openosc | `libopenosc.so` | ~1 MB |
| node | `out/Release/node` | ~80 MB |

Under the Phase-1 capture resolution these binaries are **not** shipped at
all. If an interim build ever must ship a binary (before the pilot lands),
compress with `zstd`; only ffmpeg and node are a size concern.

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
    # Truly-sidecar: transparent LD_PRELOAD shim injected by infra.
    preload_lib: /opt/omnibor/lib/libomnibor_intercept.so
    interception: ld_preload   # ld_preload (default) | ebpf | ptrace
    create_bom_script: bomsh_create_bom.py
    sbom_script: bomsh_sbom.py
    raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1
    # wrapper_dir is used ONLY by the standalone-without-ptrace
    # CcWrapperStrategy option (§2.6), not by the sidecar tiers.
    wrapper_dir: /opt/bomsh/bin
```

`resolve_omnibor_cfg()` in `config.py` already handles both formats — the
nested format auto-selects based on `config["mode"]`. A per-repo
`interception` override (`ld_preload` | `ebpf` | `ptrace`) selects the
tier for hermetic or statically-linked builds.

---

## 6. Upstream `bomsh` Interception Requirements

### 6.1 Truly-sidecar — `LD_PRELOAD` shim (primary)

The transparent sidecar mechanism is an `LD_PRELOAD` shim
(`libomnibor_intercept.so`) injected by infrastructure, never by the build
command (see §2.3). Because it interposes at the exec/dynamic-linker level,
it captures compiler **and** linker invocations regardless of whether the
Makefile uses `$(CC)` or hardcodes `gcc` — avoiding the wrapper option's
biggest coverage gap. It writes the **same raw logfile format** as
`bomtrace3` so `bomsh_create_bom.py` works unchanged. The shim does not yet
exist in upstream bomsh and must be contributed or developed.

### 6.2 Standalone-without-ptrace — CC/CXX/AR/LD wrappers

The CC/CXX/AR/LD wrappers assumed by `CcWrapperStrategy` (§2.6) support the
standalone-without-ptrace option **only** (not sidecar). They also **do not
yet exist in upstream bomsh** and must be contributed or developed.

| Wrapper | Purpose | Intercepts | Output |
|---------|---------|-----------|--------|
| `bomsh_cc_wrapper.sh` | Wrap `gcc`/`clang` | `.c` → `.o` compilation | Appends to raw logfile |
| `bomsh_cxx_wrapper.sh` | Wrap `g++`/`clang++` | `.cpp` → `.o` compilation | Appends to raw logfile |
| `bomsh_ar_wrapper.sh` | Wrap `ar` | `.o` → `.a` archiving | Appends to raw logfile |
| `bomsh_ld_wrapper.sh` | Wrap `ld`/`gold`/`lld` | `.o` → binary linking | Appends to raw logfile |

#### 6.2.1 Wrapper implementation approach

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

#### 6.2.2 Wrapper build-system compatibility

| Build System | `CC=` Support | Notes |
|-------------|--------------|-------|
| autoconf/make | ✅ Native | `./configure CC=wrapper` or env var |
| CMake | ✅ via `-DCMAKE_C_COMPILER=` | Or env `CC=` before cmake |
| Meson | ✅ via `--native-file` or env | Cross-file or `CC=` |
| Plain Makefile | ✅ if Makefile uses `$(CC)` | Most do; some hardcode `gcc` |

**Risk (wrappers only)**: Some Makefiles hardcode `gcc`/`g++` instead of
using `$(CC)`/`$(CXX)`. For those repos, the **wrapper** option misses
compilation events. The truly-sidecar `LD_PRELOAD` tier (§6.1) is
**unaffected** — it interposes below the build system. Wrapper mitigation:
document per-repo compatibility in `config.yaml` with a
`sidecar_compatible: true/false` field.

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
| `test_select_c_cpp_strategy_sidecar` | Returns `LdPreloadStrategy` (sidecar primary tier) |
| `test_cc_wrapper_instrument_command` | Standalone-without-ptrace: correct `CC`/`CXX`/`AR`/`LD` env vars |
| `test_cc_wrapper_generate_adg` | Standalone-without-ptrace: delegates to `PtraceStrategy.generate_adg()` |
| `test_c_cpp_phase1_writes_manifest` | `--phase build` produces `phase1_manifest.json` |
| `test_c_cpp_phase2_reads_manifest` | `--phase spdx --manifest ...` runs Phase 2 |
| `test_c_cpp_pipeline_unchanged` | No `--phase` runs both phases identically |

### 8.2 Integration Tests (EC2)

| Test | Command | Validates |
|------|---------|-----------|
| Standalone full | `--repo curl` | Current behavior unchanged |
| Sidecar full | `--repo curl --mode sidecar` | `LD_PRELOAD` shim produces valid SPDX |
| Phase split | `--repo curl --phase build` then `--phase spdx` | Output matches standalone golden |
| Golden comparison | All modes | SPDX matches standalone golden files |

### 8.3 Build System Compatibility Matrix

The `$(CC)` column below matters **only** for the standalone-without-ptrace
wrapper option (§2.6). The truly-sidecar `LD_PRELOAD` tier interposes below
the build system, so all repos are expected compatible regardless of
`$(CC)` usage. Test sidecar mode against all 6 C/C++ repos:

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
| 5 | Develop `LD_PRELOAD` shim (`libomnibor_intercept.so`) + injection | 3d | External/infra dependency |
| 6 | Add version pre-computation for cross-host Phase 2 | 0.5d | Task 4 |
| 7 | Convert `config.yaml` `omnibor:` to nested format | 0.25d | — |
| 8 | Unit tests | 0.5d | Tasks 1-4 |
| 9 | Integration tests on EC2 (sidecar mode) | 1d | Task 5 |
| 10 | Golden file comparison for sidecar output | 0.5d | Task 9 |
| 11 | (Deferred) eBPF DaemonSet for statically-linked builds | 3d | Task 5 |

**Critical path blocker**: Task 5 (the `LD_PRELOAD` shim). Without the
shim, the sidecar primary tier cannot be tested end-to-end. The wiring
(tasks 1-4, 6-8) can proceed in parallel. The eBPF secondary tier (task
11) is deferrable and only needed for statically-linked builds.

---

## 10. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `LD_PRELOAD` shim not yet built | **High** | Blocks sidecar E2E testing | Prototype shim locally; ship Java sidecar first; tertiary `ptrace` tier works today |
| Statically-linked builds defeat `LD_PRELOAD` | Medium | Missed events for static builds | eBPF secondary tier (task 11); or per-repo `ptrace` override |
| Makefile hardcodes `gcc` | **Low** (sidecar) | Only affects the wrapper option; `LD_PRELOAD` is unaffected | Use `LD_PRELOAD`; wrappers need `sidecar_compatible` flag |
| Binary transfer size (ffmpeg, node) | **Low** (resolved) | Would slow cross-host Phase 2 | Run `bomsh_sbom.py` + `ldd`/`readelf` in the Phase-1 capture window; ship metadata only, no binary egress (§4.2) |
| Source tree needed for version detection | Medium | Blocks cross-host Phase 2 | Version pre-computation in Phase 1 manifest |
| `libtool` relinking changes binary hash | Low | `bomsh_sbom.py` `ExternalRef` injection fails | Already mitigated by `_inject_omnibor_refs()` in `spdx_generator.py` |

---

## 11. Effort and ROI (AI-days)

| Work Item | Effort |
|---|---|
| Design (this consolidation) | ~2 |
| `LD_PRELOAD` shim + plumbing (primary) | ~3 |
| eBPF DaemonSet (secondary, deferrable) | ~3 |
| ptrace override (tertiary, mostly exists) | ~0.5 |

Recommendation: **primary `LD_PRELOAD` first** (covers ~80% with ~3%
overhead and zero build modification); the eBPF secondary tier is
deferrable and only needed for statically-linked builds.

---

## 12. Open Questions

1. **Webhook ownership** — is the K8s mutating-webhook + init-container
   injection in scope for this repo, or owned by a platform team (we just
   ship the shim + manifest)?
2. **Upstream bomsh** — should the `LD_PRELOAD` shim live in `omnibor/bomsh`
   (like the wrappers) or in this repo?
3. **Rust/Go** — `GoToolexecStrategy` (`-toolexec`) and `RustcWrapperStrategy`
   (`RUSTC_WRAPPER`) share the same wrapper-vs-sidecar concern. Apply the
   same tier model to them, or keep this revision scoped to C/C++ for now?
4. **Binaries vs metadata to S3 (resolved principle)** — no artifact-derived
   fact needs Phase 2: hashes, ELF/`ldd` metadata, and ADG resolution are
   all Phase-1-capturable, and Phase 1 already records artifact hashes in
   the raw logfile. The only open choice is *where the SPDX document is
   assembled*: run `bomsh_sbom.py` in the Phase-1 capture window (pilot,
   zero upstream change) vs. capture a structured artifact→facts map and
   assemble in Phase 2 (lets Corona re-generate without re-capture). Either
   way, binaries never leave the build host. See §4.2.
