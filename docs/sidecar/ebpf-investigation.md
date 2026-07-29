# eBPF Deep Investigation Report

> **Date**: June 10, 2026
> **Status**: Investigation complete — recommendation provided
> **Prerequisite reading**: `ebpf-and-bpf.md` (same directory)

---

## Executive Summary

eBPF for build interception may be **necessary for enterprise C/C++
deployment**. As a sidecar solution, eBPF feasibility depends entirely
on the **customer's build machines** — their kernel version, security
policies, and container runtime capabilities — not our EC2 dev/test
infrastructure.

Language-native wrappers (`CC=`, `CXX=`) work for well-structured
open-source projects that use `$(CC)` variables (our 6 test repos).
However, **the majority of enterprise C/C++ build environments will not
work with wrappers**. Enterprise codebases frequently have:

- **Hardcoded compiler paths** in Makefiles and scripts (10+ years old)
- **Proprietary or custom build systems** that ignore `CC=` env vars
- **Multi-layer build orchestrations** (wrappers around wrappers)
- **Generated Makefiles** from non-standard tools that embed absolute paths
- **Legacy autoconf scripts** that cache the compiler path at `configure` time

For these environments, only **kernel-level interception** (ptrace or
eBPF) can observe compiler invocations without requiring build
modification. ptrace works today (standalone mode) but has 20-60%
overhead and requires `SYS_PTRACE`. eBPF would provide the same
transparent interception with near-zero overhead and potentially
without `SYS_PTRACE`.

**Recommendation**: eBPF is a **serious candidate** for enterprise C/C++
sidecar mode, not merely a future extensibility point. Evaluate ebomf
when access is available; if blocked, prototype an in-house eBPF
interceptor. `CcWrapperStrategy` remains valid for the subset of
projects with compliant build systems, but should not be assumed as
the general enterprise solution.

---

## 1. Current BPF/eBPF Usage in bisbom-gen

| Technology | Where Used | Purpose |
|-----------|-----------|---------|
| **seccomp-BPF** (classic BPF) | Java standalone (`strace --seccomp-bpf`) | Filter `openat` syscalls only — reduces ptrace stops by ~99% |
| **eBPF** | Nowhere | Not used in any production code |

seccomp-BPF is classic BPF (cBPF) — a simple syscall filter. It is
**not** full eBPF. The distinction matters: cBPF can only accept/reject
syscalls; eBPF can run arbitrary programs attached to kernel tracepoints
with ring buffers, maps, and complex logic.

---

## 2. Interception Strategy Landscape

Six interception strategies exist in the performance optimization
proposal. Our current implementation status:

| # | Strategy | Overhead | Status | Mode |
|---|----------|----------|--------|------|
| 1 | Pre-hash cache | 40% → 29% | Not implemented | Standalone |
| 2 | seccomp-BPF filter for bomtrace3 | 29% → 14% | Partially (Java only) | Standalone |
| 3 | Async tracer + hash worker | 14% → 10% | Not implemented | Standalone |
| 4 | Deferred post-build hashing | 10% → 7% | Not implemented | Standalone |
| **5** | **CC= compiler wrappers** | **40% → 3-5%** | **Partially implemented** (`CcWrapperStrategy`) | **Sidecar** |
| 6 | Full eBPF tracing | 40% → 1-3% | Design only | Sidecar |

**Key insight**: Strategies 1-4 (Path A) are incremental improvements to
the ptrace-based standalone pipeline. Strategies 5-6 (Path B) replace
ptrace entirely. They are **not cumulative** — pick one Path B strategy.

Strategy 5 (CC= wrappers) achieves 35-37pp reduction. Strategy 6 (eBPF)
achieves 37-39pp. The raw performance difference is only 2pp — but
**the real differentiator is not performance, it is applicability**.
Wrappers require build system cooperation (`$(CC)` variables). eBPF
operates at the kernel level and intercepts compiler invocations
regardless of how they were launched. For enterprise C/C++ builds with
hardcoded paths, custom build systems, or legacy orchestrations that
are 10+ years old, **eBPF may be the only viable sidecar strategy**.

---

## 3. eBPF Technical Feasibility — Target Environment Analysis

The sidecar runs on **customer build machines**, not our EC2. eBPF
feasibility must be assessed against the enterprise environments where
the sidecar will actually deploy.

### 3.1 Enterprise Build Machine Landscape

| OS | Kernel | eBPF Tracepoints | `CAP_BPF` (5.8+) | Likelihood in Enterprise |
|----|--------|-----------------|-------------------|-------------------------|
| **RHEL 8 / Rocky 8** | 4.18 | ✅ Available (backported) | ❌ Needs `CAP_SYS_ADMIN` | **Very common** — still in RHEL support until 2029 |
| **RHEL 9 / Rocky 9** | 5.14 | ✅ Available | ✅ Available | **Growing** — newer enterprise deployments |
| **Ubuntu 20.04 LTS** | 5.4 | ✅ Available | ❌ Needs `CAP_SYS_ADMIN` | **Common** — support until 2025 (ESM 2030) |
| **Ubuntu 22.04 LTS** | 5.15+ | ✅ Available | ✅ Available | **Common** — current LTS |
| **Ubuntu 24.04 LTS** | 6.8+ | ✅ Available | ✅ Available | **Growing** |
| **SLES 15 SP4+** | 5.14+ | ✅ Available | ✅ Available | Moderate (SUSE enterprise) |
| **Amazon Linux 2** | 4.14/5.10 | ⚠️ Varies by AMI | ❌/✅ Varies | Common in AWS shops |
| **Amazon Linux 2023** | 6.1+ | ✅ Available | ✅ Available | Growing |
| **Older RHEL 7** | 3.10 | ❌ No eBPF | ❌ No | **Still exists** — EOL but extended support |

**Key finding**: eBPF tracepoints are available on most current
enterprise Linux (RHEL 8+, Ubuntu 20.04+). However, `CAP_BPF`
(the non-root capability) requires kernel 5.8+. On older kernels,
eBPF program loading requires `CAP_SYS_ADMIN` — a significantly
harder ask in locked-down enterprise environments.

### 3.2 Enterprise Security Constraints

| Constraint | Impact on eBPF | Prevalence |
|-----------|---------------|------------|
| **SELinux enforcing** (RHEL default) | May block BPF program loading | Very common on RHEL |
| **Locked-down seccomp profiles** | May block `bpf()` syscall | Common in hardened containers |
| **No root in containers** | Blocks BPF without `CAP_BPF` grant | Common (rootless Docker/Podman) |
| **Read-only `/sys/kernel/debug`** | Blocks debugfs-based tracepoint discovery | Moderate |
| **Kernel lockdown mode** | Blocks unsigned BPF programs | Rare but increasing (Secure Boot) |
| **Corporate security policy** | May prohibit kernel instrumentation entirely | Varies by org |

These constraints are **not present in our EC2 dev environment** but
will be present in many customer deployments. The sidecar must handle
graceful fallback when eBPF is unavailable.

### 3.3 Our EC2 Dev/Test Environment (Reference Only)

Our EC2 (kernel 6.8, `sys_enter_execve` tracepoint verified, `libbpf`
installed) is suitable for **prototyping and testing** eBPF interception.
It is not representative of customer environments. Any eBPF solution
must be validated against the enterprise constraints in §3.2.

### 3.4 What an eBPF Build Interceptor Would Look Like

```c
SEC("tracepoint/syscalls/sys_enter_execve")
int trace_execve(struct trace_sys_enter_execve *ctx) {
    u32 pid = bpf_get_current_pid_tgid() >> 32;
    // Read filename from userspace
    char filename[256];
    bpf_probe_read_user_str(filename, sizeof(filename), ctx->filename);
    // Write to ring buffer for userspace daemon
    struct event e = { .pid = pid };
    __builtin_memcpy(e.filename, filename, sizeof(filename));
    bpf_ringbuf_output(&events, &e, sizeof(e), 0);
    return 0;
}
```

The eBPF program captures `execve` events (compiler invocations) without
stopping the tracee. A userspace daemon reads events from the ring buffer,
parses argv, tracks PID lifecycle, and hashes output files post-exit.

### 3.5 Technical Challenges

| Challenge | Severity | Detail |
|-----------|----------|--------|
| **argv parsing** | High | eBPF cannot iterate userspace string arrays of unknown length. Must read `argv` pointers one by one with `bpf_probe_read_user`, limited by BPF stack (512 bytes) and instruction count. Typically solved by capturing only `argv[0]` in-kernel and reading `/proc/PID/cmdline` from userspace. |
| **File I/O tracking** | High | `execve` alone doesn't capture which `.c` files are compiled into which `.o` files. Need to also trace `openat` (like bomtrace) or parse `-MD` dependency output post-build. |
| **PID lifecycle** | Medium | Must track process creation and exit to know when output files are ready for hashing. Requires `sched_process_exit` tracepoint or `/proc/PID` polling. |
| **Container PID namespace** | Medium | eBPF sees host PIDs. Mapping to container PIDs requires cgroup filtering or PID namespace awareness. |
| **Output format** | Medium | Must produce raw logfile compatible with `bomsh_create_bom.py`, or write a new adapter for our SPDX pipeline. |
| **Enterprise kernel diversity** | **High** | Sidecar must work across RHEL 7-9, Ubuntu 18-24, SLES, Amazon Linux. eBPF capabilities vary significantly. Must detect available features at runtime and degrade gracefully. |
| **`CAP_BPF` / `CAP_SYS_ADMIN`** | **High** | On kernel <5.8, eBPF requires `CAP_SYS_ADMIN` — many enterprise security teams will not grant this to a sidecar container. On 5.8+, `CAP_BPF` + `CAP_PERFMON` suffices but still requires explicit grant. |
| **SELinux / seccomp policies** | **High** | RHEL defaults to SELinux enforcing. The `bpf()` syscall may be blocked by container seccomp profiles. Sidecar must detect and report this clearly. |

---

## 4. ebomf External Project Assessment

| Field | Value |
|-------|-------|
| **Repository** | `github.com/marctjones/ebomf` |
| **Access** | **Still private** (404 as of June 10, 2026) |
| **Public information** | None found — no papers, blog posts, or FOSDEM talks |
| **Industry adoption** | Zero — no SBOM tool uses eBPF for build interception as of June 2026 |

**Without repo access, we cannot evaluate ebomf's output format,
accuracy, or integration feasibility.** The evaluation steps in
`ebpf-and-bpf.md` Appendix A remain blocked on access.

---

## 5. Comparative Assessment

### 5.1 eBPF vs Language-Native Wrappers

| Criterion | eBPF (Strategy 6) | Wrappers (Strategy 5) |
|-----------|-------------------|----------------------|
| **Overhead** | 1-3% | 3-5% |
| **Language coverage** | All (kernel-level) | Per-language (`CC=`, `-toolexec`, `RUSTC_WRAPPER`, dep:tree) |
| **Build modification** | None | `CC=` env vars or build flags |
| **Implementation effort** | High (new BPF program + userspace daemon + adapter) | Low (wrappers exist in pattern; `CcWrapperStrategy` already coded) |
| **Maturity** | Zero production SBOM usage | `ccache`, `distcc`, `sccache` all use this pattern |
| **Platform** | Linux only, 5.8+ kernel | Any OS (wrappers are shell scripts) |
| **Docker requirements** | `CAP_BPF` + `CAP_PERFMON` | Standard (no special capabilities) |
| **bomsh compatibility** | Unknown (new output format?) | Same raw logfile format |
| **Enterprise build coverage** | High (kernel-level, works regardless of build system) | Low (requires `$(CC)` compliance — most enterprise builds don't) |
| **Enterprise CI/CD security** | Risky (`CAP_BPF`/`CAP_SYS_ADMIN` may be blocked; SELinux) | Safe (no special capabilities) — but moot if wrappers can't inject |
| **Time to production** | Months (build from scratch) | Days-weeks (wire existing code) |

### 5.2 Decision Matrix

| Factor | Weight | eBPF Score | Wrapper Score |
|--------|--------|-----------|---------------|
| Time to value | Medium | 3/10 | 9/10 |
| Risk | Medium | 4/10 | 8/10 |
| Performance gain | Low | 9/10 | 8/10 |
| **Enterprise build coverage** | **High** | **9/10** | **3/10** |
| Open-source build coverage | Medium | 9/10 | 9/10 |
| Maintenance complexity | Low | 4/10 | 8/10 |
| **Weighted total** | | **Higher for enterprise** | **Higher for open-source** |

**Conclusion**: Both strategies are needed. Wrappers are faster to
deploy for compliant builds. eBPF is required for the enterprise
majority where wrappers cannot be injected.

### 5.3 What eBPF Solves That Wrappers Don't

eBPF provides clear value over wrappers in **common enterprise
scenarios**:

1. **Enterprise C/C++ builds with hardcoded compiler paths** — the
   majority of enterprise codebases (10+ years old) use hardcoded
   `gcc`/`g++` in Makefiles, shell scripts, and proprietary build
   systems. These do **not** respect `CC=` / `CXX=` env vars. Our 6
   open-source test repos all use `$(CC)` — but open-source projects
   are not representative of enterprise build environments.
2. **Proprietary or custom build systems** — many enterprises use
   in-house build orchestration (wrapper scripts, CI plugins, custom
   Make-like tools) that bypass standard env var mechanisms entirely.
3. **Multi-layer build orchestrations** — enterprise builds often chain
   multiple layers (outer Makefile → inner script → actual compiler).
   `CC=` set at the outer layer may not propagate through all layers.
4. **Zero-modification interception** — regulatory or contractual
   requirements may prohibit modifying the build command in any way.
5. **Generated build files** — tools like `gyp`, proprietary code
   generators, or legacy autoconf caches may embed absolute compiler
   paths that cannot be overridden.

Triggers 1-3 apply to the **primary enterprise deployment scenario**
for this project. The open-source test repos where wrappers work are
not representative of the target customer base.

---

## 6. Recommendation

### eBPF Is a Serious Enterprise Requirement — Not Just an Optimization

The case for eBPF is **not** about the 2pp performance margin over
wrappers. It is about **applicability to real enterprise C/C++ builds**.
Most enterprise builds will not work with `CC=` wrapper injection.
eBPF is the path to zero-modification sidecar interception for those
environments.

### Dual Strategy for C/C++ Sidecar

| Strategy | Target Environment | Status |
|----------|-------------------|--------|
| `CcWrapperStrategy` | Open-source and compliant builds that respect `$(CC)` | Implemented, needs wiring |
| `EbpfStrategy` | Enterprise builds with hardcoded paths / custom build systems | Needs development |

Both should be implemented. The pipeline selects the strategy via
config, so they coexist without conflict.

### Immediate Next Steps

1. **Wire `CcWrapperStrategy`** to the pipeline (low effort, covers
   open-source repos and compliant enterprise builds)
2. **Get ebomf access** — evaluate output format, accuracy, and
   integration feasibility per Appendix A of `ebpf-and-bpf.md`
3. **If ebomf is blocked**: prototype a minimal eBPF interceptor that
   traces `sys_enter_execve` + `sys_exit_execve`, captures compiler
   invocations, and produces raw logfile compatible with
   `bomsh_create_bom.py`
4. **Integration test both strategies** against the same golden files

### eBPF Development Path (If ebomf Unavailable)

| # | Task | Effort | Notes |
|---|------|--------|-------|
| 1 | Install `bpftrace` + `libbpf-dev` on EC2 | 0.25d | Package install |
| 2 | Prototype BPF program: `sys_enter_execve` tracepoint | 1d | Capture PID, filename, argv[0] |
| 3 | Userspace daemon: ring buffer reader + `/proc/PID/cmdline` | 2d | Full argv + cwd + exit tracking |
| 4 | Raw logfile writer (bomsh-compatible format) | 1d | Must match `bomsh_create_bom.py` input |
| 5 | `EbpfStrategy` implementation | 0.5d | Wire into strategy pattern |
| 6 | Docker capability config (`CAP_BPF` + `CAP_PERFMON`) | 0.25d | docker-compose update |
| 7 | Integration testing on 6 C/C++ repos | 1d | Golden file comparison |
| **Total** | | **~6d** | |

### seccomp-BPF Quick Win (Optional)

Adding `--seccomp-bpf` to bomtrace3 for C/C++ standalone builds is a
separate, low-effort optimization (~15pp reduction in standalone
overhead). This is independent of eBPF and can be done anytime by
enabling the existing strace `--seccomp-bpf` flag in bomtrace3's
invocation. It benefits standalone mode, which remains necessary for
enterprise teams with isolated build machines.

---

## 7. Architecture Readiness

The strategy pattern in `interception.py` was designed for exactly this
extensibility. If eBPF is ever needed:

```python
class EbpfStrategy(InterceptionStrategy):
    @property
    def name(self):
        return "ebpf"

    def instrument_command(self, build_cmd, repo_dir):
        # Start eBPF daemon, run build unmodified
        return f"ebomf --output /tmp/ebomf_adg -- {build_cmd}", {}

    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        # Parse ebomf output into treedb-compatible format
        ...
```

Selected via config:

```yaml
omnibor:
  sidecar:
    strategy: ebpf
```

**No pipeline code changes required.** The adapter between ebomf's
output format and our SPDX generators is the main engineering work.

---

## 8. Summary

| Question | Answer |
|----------|--------|
| Is eBPF feasible on enterprise build machines? | **Conditionally** — RHEL 8+/Ubuntu 20.04+ support it; older kernels and locked-down policies are blockers |
| Is eBPF needed for enterprise C/C++? | **Yes** — most enterprise builds won't work with `CC=` wrappers |
| Is eBPF better than wrappers? | **For enterprise**: yes (applicability). **For open-source**: marginal (2pp) |
| Should we invest in eBPF now? | **Yes** — needed for enterprise C/C++ where wrappers fail |
| Is our architecture ready for eBPF later? | **Yes** — strategy pattern supports plug-in |
| Is ebomf evaluable? | **No** — repo still private; prototype path documented if blocked |

---

*Investigation conducted June 10, 2026. Updated same day after
enterprise build environment analysis.*
