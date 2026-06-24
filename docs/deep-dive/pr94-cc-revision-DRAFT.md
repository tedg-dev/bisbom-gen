# DRAFT for Review — PR #94 C/C++ Sidecar Revision (SI-1)

| | |
|---|---|
| **Purpose** | Proposed replacement content for PR #94 `sidecar-implementation-design.md` §5 (C/C++) and a re-label of the §3.3 strategy taxonomy |
| **Author** | Cascade (for Ted G. review) |
| **Drafted** | 2026-06-23 |
| **Status** | DRAFT — review before applying to branch `feat/q4fy26-sidecar-design-docs` |
| **Basis** | `phase-isolation-gap-analysis.md` (June 16) which supersedes the May 1 wrapper approach |
| **Scope** | **C/C++ sidecar only.** Rust (PR #94 §6) and Go (§7) raise analogous wrapper-vs-sidecar concerns but are out of scope here — see Open Question 3. |

> Nothing has been committed to the PR #94 branch. This file is the
> proposed text for your approval. On approval I will apply §5 and the
> §3.3 relabel to the feature branch.

---

## Summary of the change

PR #94 §5 currently designs C/C++ sidecar mode entirely around compiler
**wrapper injection** (`CC=/opt/omnibor/gcc-wrapper make`,
`CcWrapperStrategy`). The June 16 gap-analysis proves this is **not truly
sidecar**: setting `CC=`/`CXX=`/`AR=`/`LD=` modifies the build invocation,
violating the zero-build-modification constraint. This revision:

1. Re-labels the wrapper/env-var strategies as **standalone-without-ptrace**
   (a valid mode, just not sidecar).
2. Replaces §5 with a **three-tier truly-sidecar model**: primary
   `LD_PRELOAD`, secondary eBPF, tertiary per-repo `ptrace` override.
3. Documents **least-build-time-impact** by moving all non-inline capture
   (`ldd`/`readelf`, binary copy) to the post-build capture window.

---

## Proposed §3.3 relabel (strategy taxonomy)

Replace the "WrapperStrategy = sidecar" framing with three categories:

| Category | Strategies | Modifies build invocation? | Mode |
|---|---|---|---|
| **Standalone (ptrace)** | `PtraceStrategy` (`bomtrace3`/`bomtrace2`) | No (wraps the *runner*, needs `SYS_PTRACE`) | standalone |
| **Standalone (no ptrace)** | `CcWrapperStrategy`, `GoToolexecStrategy`, `RustcWrapperStrategy` | **Yes** (`CC=`, `-toolexec`, `RUSTC_WRAPPER`) | standalone alt — **not sidecar** |
| **Sidecar (transparent)** | `LdPreloadStrategy`, `EbpfStrategy` | **No** (kernel/linker-level, injected by infra) | sidecar |

Key correction: env-var/wrapper injection is retained as a useful
**standalone** option, but it is explicitly **not** a sidecar mechanism.

---

## Proposed replacement for §5

### 5. Per-Language Implementation: C/C++ (Truly-Sidecar)

#### 5.1 Current state and why wrappers are not sidecar

The implemented `CcWrapperStrategy`
(`@app/pipeline/interception.py`) sets `CC`/`CXX`/`AR`/`LD` to OmniBOR
wrapper scripts. This works without `SYS_PTRACE`, but it **changes the
build command's environment**, which the sidecar model forbids.

Approaches ruled out by the zero-modification constraint:

| Approach | Why invalid |
|---|---|
| `CC=/opt/omnibor/gcc-wrapper make` | Sets a build env var (changes invocation) |
| `bear -- make`, `cov-build make` | Wraps/changes the build command |
| `RUSTC_WRAPPER=`, `go build -toolexec=` | Requires env/flag on the build command |
| Makefile / lifecycle hooks | Modifies the project's build config |

The sidecar must intercept at the **kernel or dynamic-linker level**,
transparent to the build system (industry precedent: Istio, Dynatrace,
Vault all inject via mutating webhooks + `LD_PRELOAD`).

#### 5.2 Three-tier interception model

| Tier | Mechanism | Coverage | In-band overhead | Static binaries? | Build modification |
|---|---|---|---|---|---|
| **Primary** | `LD_PRELOAD` shim injected by K8s mutating webhook (init container + shared `emptyDir`) | ~80% — all dynamically-linked builds, any build system | +1–3% | No | None |
| **Secondary** | Node-level **eBPF** DaemonSet on kernel tracepoints | All languages incl. statically-linked | Minimal kernel cost | Yes | None |
| **Tertiary** | Per-repo `interception: ptrace` override (`bomtrace3`) | Hermetic builds (Bazel, Nix, Yocto) | 20–60% (ptrace) | Yes | None (needs `SYS_PTRACE`) |

Resolution order: per-repo `interception` override > global `mode` >
default. Hermetic build systems opt into the tertiary tier per-project
without affecting others.

#### 5.3 Primary tier — `LD_PRELOAD` shim

A small shared library is injected via `LD_PRELOAD`, set by infrastructure
(a K8s `MutatingAdmissionWebhook` + init container that copies
`libomnibor_intercept.so` into a shared volume), never by the build
command.

The shim interposes `execve`, `open`/`openat`, and `close` to:

1. Record each compiler/linker `argv` to the raw-logfile format consumed by
   `bomsh_create_bom.py`.
2. Hash compilation inputs and outputs **inline** (gitoid), keeping the
   data on the build's critical path minimal.
3. `exec()` the real tool so the build environment is otherwise identical.

Failure isolation (retain PR #94 P7): the shim must never fail the
customer build — on any internal error it logs and lets the real tool
proceed; the SBOM is reported incomplete rather than the build broken.

#### 5.4 Secondary tier — eBPF node DaemonSet

For statically-linked builds (where `LD_PRELOAD` cannot interpose) the
secondary tier runs a privileged DaemonSet loading eBPF programs on
`sched_process_exec`, `sched_process_exit`, and `sys_enter_openat`. It
observes compiler invocations system-wide with no pod modification. The
`sched_process_exit` tracepoint also provides reliable **build-completion
detection** for the post-build capture window. Requires `CAP_BPF` /
`CAP_SYS_ADMIN` on the DaemonSet.

#### 5.5 Tertiary tier — per-repo `ptrace` override

For hermetic build systems that defeat both `LD_PRELOAD` and eBPF, a
per-repo `interception: ptrace` setting falls back to the existing
`PtraceStrategy` (`bomtrace3`). The `build_system` field is recorded in the
SPDX `creationInfo` comment for traceability.

#### 5.6 Least-build-time-impact

Only inline hashing runs on the build's critical path (+1–3%). Everything
else moves to the **post-build capture window** on the shared volume:

| Operation | When | Cost |
|---|---|---|
| Tool invocation + I/O hashing | Inline (during build) | +1–3% |
| `ldd` + `readelf` per binary | Post-build (sidecar) | 5–30 s |
| Version detection from source | Post-build (sidecar) | <5 s |
| Copy binaries to `bom_dir` | Post-build (sidecar) | <10 s |

Total: ~1–3% in-band + <1 min post-build ≈ **~3%**. C/C++ is the cleanest
case; the default 30 s K8s `terminationGracePeriodSeconds` is sufficient.

#### 5.7 omnibor-analysis changes

| File | Change |
|---|---|
| `interception.py` | Add `LdPreloadStrategy`, `EbpfStrategy`; re-label `CcWrapperStrategy` docstring as standalone-without-ptrace |
| `config.yaml` | `mode: sidecar` selects `LD_PRELOAD`; per-repo `interception` override for tiers |
| `metadata_collector.py` | `ldd`/`readelf` run in the post-build capture window on `bom_dir`, not Phase 2 on `repo_dir` |
| `builder.py` | Capture window hook after build completion (PID/eBPF signal) |

#### 5.8 Effort and ROI (revised, AI-days)

| Work Item | Effort |
|---|---|
| Design (this revision) | ~2 |
| `LD_PRELOAD` shim + plumbing (primary) | ~3 |
| eBPF DaemonSet (secondary) | ~3 |
| ptrace override (tertiary, mostly exists) | ~0.5 |

Recommendation: **primary `LD_PRELOAD` first** (covers ~80% with ~3%
overhead and zero build modification); eBPF secondary tier is deferrable
and only needed for statically-linked builds.

---

## Open questions for your review

1. **Webhook ownership** — is the K8s mutating-webhook + init-container
   injection in scope for our repo, or owned by a platform team (we just
   ship the shim + manifest)?
2. **Upstream bomsh** — should the `LD_PRELOAD` shim live in `omnibor/bomsh`
   (like the wrappers) or in this repo?
3. **Rust/Go** — apply the same tier model to §6/§7, or keep this revision
   scoped to C/C++ for now?
