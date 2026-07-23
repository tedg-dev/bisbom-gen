# Sidecar & Phase Isolation — Rust

> **Parent doc**: `../infrastructure.md`
> **Status**: Design proposal — not yet implemented
> **Date**: 2026-06-12

---

> **Supported mode — Sidecar only.** See `../infrastructure.md` §1.
> Sidecar is the sole supported mode; **standalone is deprecated** — the
> initial ptrace-based implementation, retained only for a rare ~1%
> embedded corner case — and must not be offered as an option.

---

## 1. Current State

| Component | Status |
|-----------|--------|
| Standalone pipeline (`bomtrace2`) | ✅ Production — 2 repos (oxipng, dura) |
| `PtraceStrategy` (standalone via `bomtrace2`) | ✅ Used implicitly via legacy path |
| `RustcWrapperStrategy` skeleton | ✅ Defined in `interception.py` — **not wired to CLI** |
| `run_rust_pipeline()` | ✅ Runs Phase 1 + Phase 2 sequentially, standalone only |
| Phase 1/2 timing tags | ✅ Properly assigned |
| `--mode sidecar` for Rust | ❌ Not wired — runner does not accept `mode` |

### 1.1 Current Code Path (Standalone)

```
runners.py main()
  → run_rust_pipeline()
    → pipeline.builder.build()              # Phase 1: bomtrace2 cargo build
      ├── clean_cmd (cargo clean)
      ├── "bomtrace2 cargo build --release"
      └── bomsh_create_bom.py               # ADG generation
    → _run_post_build()                     # Phase 2
      ├── bomsh_sbom.py                     # OmniBOR SBOM
      ├── MetadataCollector.collect()
      ├── AdgSpdxStep.generate()            # per-binary SPDX
      ├── SpdxValidator.validate()
      └── BinaryCollector.collect()
```

### 1.2 Key Rust-Specific Details

- **`cargo build --release`**: Required per release-build policy. Output goes
  to `target/release/`, not `target/debug/`.
- **`bomtrace2` without custom conf**: Unlike Go, Rust uses the default
  `bomtrace.conf`. `bomsh_hook2.py` has a dedicated rustc command parser
  (`get_all_subfiles_in_rustc_cmdline`) that extracts input `.rs` files and
  output `.rlib` / binary files.
- **Static linking**: Rust statically links crate dependencies. Only system
  libraries (`libc`, `libgcc_s`, `libpthread`) are dynamically linked.
- **`Cargo.lock`**: Contains exact resolved versions for all transitive
  dependencies. This is the primary source for dependency version data.

---

## 2. Interception Strategies

### 2.1 Standalone: `bomtrace2`

- **Mechanism**: `bomtrace2 cargo build --release`
- **Capability needed**: `SYS_PTRACE` in Docker
- **Output**: raw logfile at `/tmp/bomsh_hook_raw_logfile.sha1`
- **ADG**: `bomsh_create_bom.py -r <raw_logfile> -b <bom_dir>`

### 2.2 Standalone-without-ptrace: `RustcWrapperStrategy`

> **Not a sidecar mechanism.** `RUSTC_WRAPPER` modifies the build
> invocation, which the sidecar model forbids (see `../infrastructure.md`
> §2.1 footnote). This is a valid **standalone-without-ptrace** option.
> The truly-sidecar Rust mechanism is transparent kernel/linker
> interception (`LD_PRELOAD` / eBPF), same as C/C++ — see
> `../c-cpp/sidecar-design.md` §2.

- **Mechanism**: `RUSTC_WRAPPER=/opt/bomsh/bin/bomsh_hook.sh` environment variable
- **Capability needed**: None (`SYS_PTRACE` not required)
- **How it works**: Cargo calls `RUSTC_WRAPPER rustc <args>` for every crate
  compilation. The wrapper records input `.rs` files and output `.rlib`/binary
  mappings, then invokes the real `rustc`.
- **Output**: Same raw logfile format as `bomtrace2`
- **ADG**: Same `bomsh_create_bom.py` — wrapper output is format-compatible

```python
# From interception.py — already implemented:
class RustcWrapperStrategy(InterceptionStrategy):
    def instrument_command(self, build_cmd, repo_dir):
        return build_cmd, {
            "RUSTC_WRAPPER": self._wrapper,
        }

    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        strategy = PtraceStrategy()
        return strategy.generate_adg(repo_dir, bom_dir, omnibor_cfg)
```

### 2.3 Wiring `RustcWrapperStrategy` to the Pipeline

Add `_select_rust_strategy()` in `lang_runners.py`:

```python
def _select_rust_strategy(repo_name, repo_cfg, paths_cfg, mode):
    """Select interception strategy for Rust builds.

    In standalone-without-ptrace mode, uses RUSTC_WRAPPER
    that avoids ptrace entirely.

    In standalone mode, returns None (legacy bomtrace2 path).
    """
    if mode != "sidecar":
        return None
    from app.pipeline.interception import RustcWrapperStrategy
    return RustcWrapperStrategy()
```

Modify `run_rust_pipeline()` to accept `mode=`:

```python
def run_rust_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_rust_cfg, run_ts,
    vcs_uri="NOASSERTION",
    mode="standalone",        # NEW
):
    strategy = _select_rust_strategy(
        repo_name, repo_cfg, paths_cfg, mode,
    )
    ...
    build_result = pipeline.builder.build(
        ..., strategy=strategy,
    )
```

### 2.4 `RUSTC_WRAPPER` vs `RUSTC_WORKSPACE_WRAPPER`

Cargo supports two wrapper environment variables:
- **`RUSTC_WRAPPER`**: Wraps every `rustc` invocation (including build scripts,
  proc macros, and all transitive dependencies)
- **`RUSTC_WORKSPACE_WRAPPER`**: Only wraps workspace crates (skips
  dependencies compiled by Cargo itself)

For OmniBOR, we want `RUSTC_WRAPPER` because we need to trace **all**
compilation steps including transitive dependencies. Using
`RUSTC_WORKSPACE_WRAPPER` would miss most of the dependency graph.

**Future optimization**: For large workspaces with many proc-macro crates,
`RUSTC_WORKSPACE_WRAPPER` could be used as a fast mode that only traces
first-party code. Track as a future enhancement.

---

## 3. Phase 1 Artifacts

| Artifact | Standalone | Sidecar | Location |
|----------|-----------|---------|----------|
| Raw logfile | ✅ `bomtrace2` writes | ✅ `RUSTC_WRAPPER` wrapper writes same format | `/tmp/bomsh_hook_raw_logfile.sha1` |
| Treedb (`bomsh_omnibor_treedb`) | ✅ `bomsh_create_bom.py` | ✅ same script | `bom_dir/metadata/bomsh/` |
| `bomsh_omnibor_doc_mapping` | ✅ | ✅ | `bom_dir/metadata/bomsh/` |
| Output binary (ELF) | ✅ `target/release/` | ✅ `target/release/` | Per `output_binaries` config |
| `Cargo.lock` | ✅ (in source tree) | ✅ | `repo_dir/Cargo.lock` |
| `Cargo.toml` | ✅ (in source tree) | ✅ | `repo_dir/Cargo.toml` |
| `phase1_manifest.json` | ✅ (when `--phase build`) | ✅ | `bom_dir/phase1_manifest.json` |

---

## 4. Phase 2 Requirements

| Operation | Module | Needs Binary? | Needs Source Tree? | Needs Treedb? |
|-----------|--------|---------------|-------------------|---------------|
| `bomsh_sbom.py` | `spdx_generator.py` | ✅ reads binary hashes | ❌ | ✅ |
| `ldd` (dynamic deps) | `adg_spdx.py` | ✅ (only system libs) | ❌ | ❌ |
| `AdgSpdxGenerator` (per-binary SPDX) | `adg_spdx.py` | ❌ | ✅ (`Cargo.lock`/`Cargo.toml`) | ✅ |
| `MetadataCollector` | `metadata_collector.py` | ❌ | ✅ (repo metadata) | ❌ |
| `BinaryCollector` | `binary_collector.py` | ✅ (copies binary) | ❌ | ❌ |

### 4.1 Source Tree Dependency

Rust's `AdgSpdxGenerator` needs:
- `Cargo.lock` — exact dependency versions and checksums
- `Cargo.toml` — direct vs transitive dependency classification,
  `[features]` enabled

These are small text files. Copy to `bom_dir` during Phase 1 for
cross-host Phase 2.

### 4.2 Binary Size

Rust binaries are statically linked (crate deps) with some dynamic system
libraries. Release builds with default optimization:

| Repo | Binary | Approximate Size |
|------|--------|-----------------|
| oxipng | `target/release/oxipng` | ~4 MB |
| dura | `target/release/dura` | ~8 MB |

Small enough for direct cross-host transfer.

---

## 5. Config Schema

### 5.1 Current (flat format)

```yaml
omnibor_rust:
  tracer: bomtrace2
  create_bom_script: bomsh_create_bom.py
  sbom_script: bomsh_sbom.py
  raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1
```

### 5.2 Target (nested mode format)

```yaml
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

## 6. Upstream `bomsh` Wrapper Requirements

Rust's `RUSTC_WRAPPER` calls the wrapper as:

```
/opt/bomsh/bin/bomsh_hook.sh rustc <crate_args...>
```

The wrapper receives `rustc` as `$1` followed by all original rustc arguments.

`bomsh_hook2.py` already has:
- `get_all_subfiles_in_rustc_cmdline()` — parses `rustc` arguments to extract
  input `.rs` files, `--extern` crate references, and output `.rlib`/binary paths

**Status**: `bomsh_hook.sh` needs verification that it correctly handles:
1. The `RUSTC_WRAPPER` calling convention (tool as first arg)
2. `rustc` command-line parsing via `bomsh_hook2.py`
3. Proc-macro compilation (separate compilation unit)
4. Build script execution (`build.rs`)

**Key difference from Go**: Go's `-toolexec` passes the tool path directly.
Rust's `RUSTC_WRAPPER` always passes `rustc` as `$1` — the wrapper doesn't
need to discover the real compiler path.

---

## 7. Phase Split Design

### 7.1 `run_rust_phase1()`

```python
def run_rust_phase1(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_rust_cfg, run_ts,
    mode="standalone",
    vcs_uri="NOASSERTION",
    commit_sha=None,
):
    """Rust Phase 1: build + treedb + manifest."""
    strategy = _select_rust_strategy(
        repo_name, repo_cfg, paths_cfg, mode,
    )
    tracer = strategy.name if strategy else omnibor_rust_cfg.get("tracer", "bomtrace2")
    timing = TimingResult(tracer=tracer)

    build_result = pipeline.builder.build(
        repo_name, repo_cfg, paths_cfg, omnibor_rust_cfg,
        run_ts=run_ts, strategy=strategy,
    )
    timing.steps.extend(build_result.steps)
    timing.success = build_result.success

    if build_result.success:
        _copy_cargo_metadata(build_result.repo_dir, build_result.bom_dir)
        ManifestWriter().write(...)

    return timing


def _copy_cargo_metadata(repo_dir, bom_dir):
    """Copy Cargo.lock and Cargo.toml to bom_dir for cross-host Phase 2."""
    import shutil
    from pathlib import Path
    for fname in ("Cargo.lock", "Cargo.toml"):
        src = Path(repo_dir) / fname
        if src.exists():
            dst = Path(bom_dir) / fname
            shutil.copy2(str(src), str(dst))
```

### 7.2 `run_rust_phase2()`

```python
def run_rust_phase2(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_rust_cfg, run_ts,
    vcs_uri="NOASSERTION",
    manifest=None,
):
    """Rust Phase 2: SBOM → metadata → SPDX → validate → collect."""
    if manifest:
        ctx = ManifestReader().read(manifest)

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

### 7.3 `run_rust_pipeline()` (backward compatible)

```python
def run_rust_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_rust_cfg, run_ts,
    vcs_uri="NOASSERTION",
    mode="standalone",
):
    timing = run_rust_phase1(...)
    if not timing.success:
        return timing
    timing2 = run_rust_phase2(...)
    timing.steps.extend(timing2.steps)
    return timing
```

---

## 8. Testing

### 8.1 Unit Tests

| Test | What it validates |
|------|-------------------|
| `test_select_rust_strategy_standalone` | Returns `None` (legacy path) |
| `test_select_rust_strategy_sidecar` | Returns `RustcWrapperStrategy` |
| `test_rustc_wrapper_instrument_command` | Sets `RUSTC_WRAPPER` env var, command unchanged |
| `test_rustc_wrapper_generate_adg` | Delegates to `PtraceStrategy.generate_adg()` |
| `test_rust_phase1_writes_manifest` | Manifest includes `Cargo.lock`/`Cargo.toml` copies |
| `test_rust_phase2_reads_manifest` | Phase 2 runs from manifest |
| `test_rust_pipeline_unchanged` | Full pipeline backward compatible |

### 8.2 Integration Tests (EC2)

| Test | Command | Validates |
|------|---------|-----------|
| Standalone full | `--repo oxipng` | Current behavior unchanged |
| Sidecar full | `--repo oxipng --mode sidecar` | `RUSTC_WRAPPER` produces valid SPDX |
| Phase split | `--repo oxipng --phase build` then `--phase spdx` | Matches golden |
| Complex deps | `--repo dura --mode sidecar` | 42 direct + 35 transitive crates |

### 8.3 `RUSTC_WRAPPER` Compatibility

Both repos use standard `cargo build --release`. `RUSTC_WRAPPER` is a
Cargo-native mechanism — no build system compatibility concerns.

**Potential issue**: If a project uses `RUSTC_WRAPPER` for another tool
(e.g., `sccache`), our wrapper conflicts. Mitigation: chain wrappers or
detect existing `RUSTC_WRAPPER` and warn.

---

## 9. Implementation Tasks

| # | Task | Effort | Depends On |
|---|------|--------|------------|
| 1 | Add `mode=` param to `run_rust_pipeline()` | 0.25d | — |
| 2 | Implement `_select_rust_strategy()` | 0.25d | — |
| 3 | Pass `mode` from `runners.py` → `run_rust_pipeline()` | 0.25d | Task 1 |
| 4 | Split into `run_rust_phase1()` / `run_rust_phase2()` | 0.5d | Infra manifest module |
| 5 | Implement `_copy_cargo_metadata()` for cross-host Phase 2 | 0.25d | Task 4 |
| 6 | Verify `bomsh_hook.sh` with `RUSTC_WRAPPER` convention | 1d | External dependency |
| 7 | Convert `config.yaml` `omnibor_rust:` to nested format | 0.25d | — |
| 8 | Unit tests | 0.5d | Tasks 1-5 |
| 9 | Integration tests on EC2 (sidecar mode) | 0.5d | Task 6 |

**Blocker**: Task 6 — verifying `bomsh_hook.sh` works as `RUSTC_WRAPPER`.
Same risk level as Go (`-toolexec`). `bomsh_hook2.py` already has the rustc
parser, so the risk is in the wrapper shell script, not the Python analysis.

---

## 10. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `bomsh_hook.sh` incompatible with `RUSTC_WRAPPER` | Medium | Blocks sidecar E2E | Test in isolation first |
| Existing `RUSTC_WRAPPER` conflict (e.g., `sccache`) | Low | User's wrapper overwritten | Detect + warn; support wrapper chaining |
| Proc-macro compilation not traced | Low | Missing dependencies in SPDX | Verify `bomsh_hook2.py` handles proc-macro crates |
| Build script (`build.rs`) side effects | Low | Extra files in treedb | `bomsh_hook2.py` should filter build script artifacts |
| Workspace projects with multiple binaries | Low | Need per-binary SPDX | Already handled by `AdgSpdxStep.generate()` |
