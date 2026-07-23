# Sidecar & Phase Isolation — Go

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
| Standalone pipeline (`bomtrace2`) | ✅ Production — 6 repos (fzf, lazygit, croc, dive, gdu, pocketbase) |
| `PtraceStrategy` (standalone via `bomtrace2`) | ✅ Used implicitly via legacy path |
| `GoToolexecStrategy` skeleton | ✅ Defined in `interception.py` — **not wired to CLI** |
| `run_go_pipeline()` | ✅ Runs Phase 1 + Phase 2 sequentially, standalone only |
| Phase 1/2 timing tags | ✅ Properly assigned |
| `--mode sidecar` for Go | ❌ Not wired — runner does not accept `mode` |

### 1.1 Current Code Path (Standalone)

```
runners.py main()
  → run_go_pipeline()
    → pipeline.builder.build()              # Phase 1: bomtrace2 go build
      ├── clean_cmd (rm -f binary)
      ├── "bomtrace2 -c bomtrace_go.conf go build -a -trimpath ..."
      └── bomsh_create_bom.py               # ADG generation
    → _run_post_build()                     # Phase 2
      ├── bomsh_sbom.py                     # OmniBOR SBOM
      ├── MetadataCollector.collect()
      ├── AdgSpdxStep.generate()            # per-binary SPDX
      ├── SpdxValidator.validate()
      └── BinaryCollector.collect()
```

### 1.2 Key Go-Specific Details

- **`-a` flag**: Forces rebuild of all packages, bypassing Go build cache.
  Required for `bomtrace2` to capture all compilation steps. In sidecar mode
  with `-toolexec`, `-a` is still needed for the same reason.
- **`bomtrace_go.conf`**: Custom bomtrace config that watches Go compiler
  tools (`compile`, `link`) and traces `openat` syscall.
- **Static linking**: Go statically links all dependencies. `ldd` returns
  "not a dynamic executable" — dynamic library analysis is not applicable.
- **Release build flags**: `-trimpath -ldflags="-s -w"` strip paths and debug
  info per project release-build policy.

---

## 2. Interception Strategies

### 2.1 Standalone: `bomtrace2` with Go conf

- **Mechanism**: `bomtrace2 -c /opt/bomsh/bin/bomtrace_go.conf go build -a ...`
- **Capability needed**: `SYS_PTRACE` in Docker
- **Output**: raw logfile at `/tmp/bomsh_hook_raw_logfile.sha1`
- **ADG**: `bomsh_create_bom.py -r <raw_logfile> -b <bom_dir>`

### 2.2 Standalone-without-ptrace: `GoToolexecStrategy`

> **Not a sidecar mechanism.** `-toolexec` modifies the build
> invocation, which the sidecar model forbids (see `../infrastructure.md`
> §2.1 footnote). This is a valid **standalone-without-ptrace** option.
> The truly-sidecar Go mechanism is transparent kernel/linker
> interception (`LD_PRELOAD` / eBPF), same as C/C++ — see
> `../c-cpp/sidecar-design.md` §2.

- **Mechanism**: `-toolexec=/opt/bomsh/bin/bomsh_hook.sh` injected into `go build`
- **Capability needed**: None (`SYS_PTRACE` not required)
- **How it works**: Go's `-toolexec` flag runs each tool invocation
  (`compile`, `asm`, `link`) through the specified wrapper. The wrapper
  records input/output file mappings before/after the real tool executes.
- **Output**: Same raw logfile format as `bomtrace2`
- **ADG**: Same `bomsh_create_bom.py` — wrapper output is format-compatible

```python
# From interception.py — already implemented:
class GoToolexecStrategy(InterceptionStrategy):
    def instrument_command(self, build_cmd, repo_dir):
        cmd = build_cmd.replace(
            "go build",
            f"go build -toolexec={self._wrapper}",
            1,
        )
        return cmd, {}

    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        strategy = PtraceStrategy()
        return strategy.generate_adg(repo_dir, bom_dir, omnibor_cfg)
```

### 2.3 Wiring `GoToolexecStrategy` to the Pipeline

Add `_select_go_strategy()` in `lang_runners.py`:

```python
def _select_go_strategy(repo_name, repo_cfg, paths_cfg, mode):
    """Select interception strategy for Go builds.

    In standalone-without-ptrace mode, uses -toolexec wrapper
    that avoids ptrace entirely.

    In standalone mode, returns None (legacy bomtrace2 path).
    """
    if mode != "sidecar":
        return None
    from app.pipeline.interception import GoToolexecStrategy
    return GoToolexecStrategy()
```

Modify `run_go_pipeline()` to accept `mode=`:

```python
def run_go_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_go_cfg, run_ts,
    vcs_uri="NOASSERTION",
    mode="standalone",        # NEW
):
    strategy = _select_go_strategy(
        repo_name, repo_cfg, paths_cfg, mode,
    )
    ...
    build_result = pipeline.builder.build(
        ..., strategy=strategy,  # None for standalone, GoToolexecStrategy for sidecar
    )
```

### 2.4 `-toolexec` and `-a` Flag Interaction

The `-a` flag is critical for both modes:
- **Standalone**: Without `-a`, Go's build cache serves cached artifacts and
  `bomtrace2` never sees the compilation
- **Sidecar**: Without `-a`, `-toolexec` is only invoked for uncached packages

The `instrument_command()` inserts `-toolexec` but does **not** add `-a` —
it expects `-a` to already be in the build command from `config.yaml`. All
6 Go repos already include `-a` in their `build_steps`.

**Future optimization**: In a warm-cache CI environment, `-a` forces a full
rebuild every time. A future enhancement could use Go's `-toolexec` without
`-a` and rely on Go's own cache invalidation for incremental builds. This
is a performance optimization tracked separately in
`sidecar-refactoring-plan.md §2.3`.

---

## 3. Phase 1 Artifacts

| Artifact | Standalone | Sidecar | Location |
|----------|-----------|---------|----------|
| Raw logfile | ✅ `bomtrace2` writes | ✅ `-toolexec` wrapper writes same format | `/tmp/bomsh_hook_raw_logfile.sha1` |
| Treedb (`bomsh_omnibor_treedb`) | ✅ `bomsh_create_bom.py` | ✅ same script | `bom_dir/metadata/bomsh/` |
| `bomsh_omnibor_doc_mapping` | ✅ | ✅ | `bom_dir/metadata/bomsh/` |
| Output binary (ELF, static) | ✅ in `repo_dir` | ✅ in `repo_dir` | Per `output_binaries` config |
| `go.sum` | ✅ (in source tree) | ✅ | `repo_dir/go.sum` |
| `go.mod` | ✅ (in source tree) | ✅ | `repo_dir/go.mod` |
| `phase1_manifest.json` | ✅ (when `--phase build`) | ✅ | `bom_dir/phase1_manifest.json` |

---

## 4. Phase 2 Requirements

| Operation | Module | Needs Binary? | Needs Source Tree? | Needs Treedb? |
|-----------|--------|---------------|-------------------|---------------|
| `bomsh_sbom.py` | `spdx_generator.py` | ✅ reads binary hashes | ❌ | ✅ |
| `ldd` (dynamic deps) | `adg_spdx.py` | ❌ Go is static | ❌ | ❌ |
| `AdgSpdxGenerator` (per-binary SPDX) | `adg_spdx.py` | ❌ | ✅ (`go.sum`/`go.mod` for versions) | ✅ |
| `MetadataCollector` | `metadata_collector.py` | ❌ | ✅ (repo metadata) | ❌ |
| `BinaryCollector` | `binary_collector.py` | ✅ (copies binary) | ❌ | ❌ |

### 4.1 Source Tree Dependency

Go's `AdgSpdxGenerator` needs:
- `go.sum` — dependency versions and checksums
- `go.mod` — direct vs indirect dependency classification

These are small text files that can be copied to `bom_dir` during Phase 1
for cross-host Phase 2.

### 4.2 Binary Size

Go binaries are statically linked and stripped (`-ldflags="-s -w"`).
Typical sizes:

| Repo | Binary | Approximate Size |
|------|--------|-----------------|
| fzf | `fzf` | ~3 MB |
| lazygit | `lazygit` | ~15 MB |
| croc | `croc` | ~8 MB |
| dive | `dive_bin` | ~10 MB |
| gdu | `gdu` | ~5 MB |
| pocketbase | `pocketbase` | ~30 MB |

Manageable for cross-host transfer without compression.

---

## 5. Config Schema

### 5.1 Current (flat format)

```yaml
omnibor_go:
  tracer: bomtrace2 -c /opt/bomsh/bin/bomtrace_go.conf
  create_bom_script: bomsh_create_bom.py
  sbom_script: bomsh_sbom.py
  raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1
```

### 5.2 Target (nested mode format)

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
```

---

## 6. Upstream `bomsh` Wrapper Requirements

Go's `-toolexec` calls the wrapper with the tool path as the first argument
followed by the tool's original arguments:

```
/opt/bomsh/bin/bomsh_hook.sh /usr/local/go/pkg/tool/linux_amd64/compile -o output.o input.go
```

`bomsh_hook2.py` already has Go-specific command parsers:
- `get_all_subfiles_in_go_compile_cmdline()` — extracts `.go` → `.o` mappings
- `get_all_subfiles_in_go_link_cmdline()` — extracts `.o` → binary mappings

The wrapper script (`bomsh_hook.sh`) needs to:
1. Record the command + file hashes in the raw logfile
2. Execute the real tool
3. Record output file hash

**Status**: `bomsh_hook.sh` exists in upstream bomsh but may need testing
with Go's `-toolexec` calling convention. The wrapper receives the real
tool path as `$1`, which differs from CC wrapper mode where the wrapper
*replaces* the compiler.

---

## 7. Phase Split Design

### 7.1 `run_go_phase1()`

```python
def run_go_phase1(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_go_cfg, run_ts,
    mode="standalone",
    vcs_uri="NOASSERTION",
    commit_sha=None,
):
    """Go Phase 1: build + treedb + manifest.

    Returns TimingResult with Phase 1 steps only.
    """
    strategy = _select_go_strategy(
        repo_name, repo_cfg, paths_cfg, mode,
    )
    tracer = strategy.name if strategy else omnibor_go_cfg.get("tracer", "bomtrace2")
    timing = TimingResult(tracer=tracer)

    build_result = pipeline.builder.build(
        repo_name, repo_cfg, paths_cfg, omnibor_go_cfg,
        run_ts=run_ts, strategy=strategy,
    )
    timing.steps.extend(build_result.steps)
    timing.success = build_result.success

    if build_result.success:
        # Copy go.mod and go.sum to bom_dir for cross-host Phase 2
        _copy_go_metadata(build_result.repo_dir, build_result.bom_dir)

        ManifestWriter().write(
            bom_dir=build_result.bom_dir,
            repo_name=repo_name,
            repo_cfg=repo_cfg,
            paths_cfg=paths_cfg,
            omnibor_cfg=omnibor_go_cfg,
            run_ts=run_ts,
            tracer=tracer,
            mode=mode,
            commit_sha=commit_sha,
            vcs_uri=vcs_uri,
            binaries=build_result.binaries,
        )

    return timing


def _copy_go_metadata(repo_dir, bom_dir):
    """Copy go.mod and go.sum to bom_dir for cross-host Phase 2."""
    import shutil
    from pathlib import Path
    for fname in ("go.mod", "go.sum"):
        src = Path(repo_dir) / fname
        if src.exists():
            dst = Path(bom_dir) / fname
            shutil.copy2(str(src), str(dst))
```

### 7.2 `run_go_phase2()`

```python
def run_go_phase2(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_go_cfg, run_ts,
    vcs_uri="NOASSERTION",
    manifest=None,
):
    """Go Phase 2: SBOM → metadata → SPDX → validate → collect.

    Returns TimingResult with Phase 2 steps only.
    """
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

### 7.3 `run_go_pipeline()` (backward compatible)

```python
def run_go_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_go_cfg, run_ts,
    vcs_uri="NOASSERTION",
    mode="standalone",
):
    timing = run_go_phase1(...)
    if not timing.success:
        return timing
    timing2 = run_go_phase2(...)
    timing.steps.extend(timing2.steps)
    return timing
```

---

## 8. Testing

### 8.1 Unit Tests

| Test | What it validates |
|------|-------------------|
| `test_select_go_strategy_standalone` | Returns `None` (legacy path) |
| `test_select_go_strategy_sidecar` | Returns `GoToolexecStrategy` |
| `test_go_toolexec_instrument_command` | Inserts `-toolexec=` after `go build` |
| `test_go_toolexec_preserves_flags` | `-a -trimpath -ldflags` remain intact |
| `test_go_phase1_writes_manifest` | Manifest includes `go.mod`/`go.sum` copies |
| `test_go_phase2_reads_manifest` | Phase 2 runs from manifest |
| `test_go_pipeline_unchanged` | Full pipeline backward compatible |

### 8.2 Integration Tests (EC2)

| Test | Command | Validates |
|------|---------|-----------|
| Standalone full | `--repo fzf` | Current behavior unchanged |
| Sidecar full | `--repo fzf --mode sidecar` | `-toolexec` produces valid SPDX |
| Phase split | `--repo fzf --phase build` then `--phase spdx` | Matches golden |
| Large repo | `--repo pocketbase --mode sidecar` | Complex dep graph handled |

### 8.3 `-toolexec` Compatibility

All 6 Go repos use standard `go build` commands. `-toolexec` is a Go-native
mechanism — no build system compatibility concerns (unlike C/C++ `CC=` wrappers).

---

## 9. Implementation Tasks

| # | Task | Effort | Depends On |
|---|------|--------|------------|
| 1 | Add `mode=` param to `run_go_pipeline()` | 0.25d | — |
| 2 | Implement `_select_go_strategy()` | 0.25d | — |
| 3 | Pass `mode` from `runners.py` → `run_go_pipeline()` | 0.25d | Task 1 |
| 4 | Split into `run_go_phase1()` / `run_go_phase2()` | 0.5d | Infra manifest module |
| 5 | Implement `_copy_go_metadata()` for cross-host Phase 2 | 0.25d | Task 4 |
| 6 | Verify `bomsh_hook.sh` with `-toolexec` calling convention | 1d | External dependency |
| 7 | Convert `config.yaml` `omnibor_go:` to nested format | 0.25d | — |
| 8 | Unit tests | 0.5d | Tasks 1-5 |
| 9 | Integration tests on EC2 (sidecar mode) | 1d | Task 6 |

**Blocker**: Task 6 — verifying `bomsh_hook.sh` works with Go's `-toolexec`.
Lower risk than C/C++ wrappers because `-toolexec` is a well-defined
Go-native mechanism and `bomsh_hook2.py` already has Go command parsers.

---

## 10. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `bomsh_hook.sh` incompatible with `-toolexec` | Medium | Blocks sidecar E2E | Test wrapper in isolation first; prototype if needed |
| `-a` flag forces full rebuild every time | Known | Slower CI | Future: explore incremental `-toolexec` without `-a` |
| Go module download during build | Low | Build may fail in air-gapped environments | `go mod download` as a pre-build step |
| CGO-enabled projects | Low | C compilation within Go build needs CC wrappers too | Add CGO detection; fall back to `bomtrace2` if CGO |
