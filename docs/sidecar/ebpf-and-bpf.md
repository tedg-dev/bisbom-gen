# eBPF and BPF in bisbom-gen

This document catalogs all eBPF and BPF usage, proposals, and external
projects relevant to OmniBOR build interception.

---

## Table of Contents

1. [What We Use Today: seccomp-BPF](#seccomp-bpf-today)
2. [What C/C++, Go, and Rust Use Instead](#other-languages)
3. [Proposed: seccomp-BPF for Other Languages](#seccomp-bpf-proposed)
4. [Proposed: Full eBPF Tracing (Strategy 6)](#ebpf-strategy-6)
5. [eBPF Deprioritization Decision](#ebpf-deprioritized)
6. [External Project: ebomf (eBPF-Based OmniBOR)](#ebomf)
7. [Cross-Platform Applicability](#cross-platform)
8. [Architecture Extensibility](#extensibility)
9. [References](#references)
- [Appendix A: Feasibility — Replacing bomtrace/strace with ebomf](#appendix-a)

---

<a id="seccomp-bpf-today"></a>

## 1. What We Use Today: seccomp-BPF

We use **seccomp-BPF** (classic BPF, not full eBPF) in one place: the
**Java standalone pipeline**. The strace `--seccomp-bpf` flag installs a
kernel-level BPF filter so only `openat` syscalls cause ptrace stops. All
other syscalls pass through untouched with zero context switches.

```yaml
# app/config.yaml
omnibor_java:
  strace_opts: -f -s99999 --seccomp-bpf -e trace=openat -qqq
```

The Docker Compose standalone service disables the default seccomp profile
so strace can install its own filter:

```yaml
# docker/docker-compose.yml
security_opt:
  - seccomp:unconfined
```

**Key distinction:** seccomp-BPF is classic BPF (cBPF) — a simple packet
filter repurposed for syscall filtering. It is NOT the same as full eBPF,
which supports tracepoints, ring buffers, maps, and complex programs.

---

<a id="other-languages"></a>

## 2. What C/C++, Go, and Rust Use Instead

None of C/C++, Go, or Rust use seccomp-BPF or eBPF today. They use raw
ptrace via bomtrace3/bomtrace2, tracing syscalls without kernel-level
filtering:

| Language | Tracer | seccomp-BPF? | Syscalls Traced |
|----------|--------|-------------|-----------------|
| **C/C++** | bomtrace3 (patched strace 6.11) | **No** | All (~400 per gcc invocation) |
| **Go** | bomtrace2 + bomtrace_go.conf | **No** | execve + openat (via conf, not kernel filter) |
| **Rust** | bomtrace2 (no conf) | **No** | All |
| **Java** | stock strace | **Yes** | openat only |

---

<a id="seccomp-bpf-proposed"></a>

## 3. Proposed: seccomp-BPF for Other Languages

### C/C++ (Strategy 2 — not yet implemented)

Documented in `strategy-2-seccomp-bpf.md` and the main performance
optimization proposal.

Paul Chaignon (strace maintainer) measured **~97% overhead reduction** on
a Linux kernel build:

| Build Mode | Wall Time | Overhead vs Native |
|------------|----------|-------------------|
| Native (no tracing) | 12m 27s | — |
| strace (no seccomp-bpf) | 24m 54s | ~100% |
| strace --seccomp-bpf | 12m 49s | ~3% |

For bomtrace3: would reduce context switches from ~800 per gcc invocation
to ~4. Estimated **15 percentage point reduction** in overhead.

The seccomp-BPF infrastructure already exists in bomtrace3's codebase
(patched strace 6.11). The work is configuring the BPF filter to match
bomsh's needs (trace only `execve` + `exit_group`).

### Rust (not yet implemented)

bomtrace2 for Rust has no seccomp-bpf and no conf file. ptrace stops on
ALL syscalls during `rustc` even though only `execve` is consumed. Adding
seccomp-bpf would eliminate thousands of unnecessary context switches per
crate. Estimated 15–25% overhead reduction.

### Go (marginal value)

Go's bomtrace2 already filters to execve + openat via conf file, so
seccomp-BPF would only formalize this at the kernel level. Estimated
5–10% improvement.

---

<a id="ebpf-strategy-6"></a>

## 4. Proposed: Full eBPF Tracing (Strategy 6)

Full eBPF tracing is documented in the performance optimization proposal
as Strategy 6. It has **zero implementation** in the codebase — it exists
only as a design proposal.

**Concept:** Attach a BPF program to `tracepoint/syscalls/sys_enter_execve`
to trace compiler invocations with zero ptrace overhead. The tracee is never
stopped. A userspace daemon reads a perf ring buffer asynchronously.

```c
SEC("tracepoint/syscalls/sys_enter_execve")
int trace_execve(struct trace_event_raw_sys_enter *ctx) {
    // Capture pid, ppid, argv[0], timestamp
    // Write to perf ring buffer
    // Tracee is NEVER stopped
    return 0;
}
```

**Projected impact:** 37–39 percentage point reduction (40% → 1–3%)

**Requirements:** Linux 5.x+ kernel, `BPF_PROG_TYPE_TRACEPOINT` capability.

---

<a id="ebpf-deprioritized"></a>

## 5. eBPF Deprioritization Decision

In `sidecar-refactoring-plan.md`, eBPF was explicitly deprioritized to a
research track (ranked #10 of 10 priority items):

| Factor | Assessment |
|--------|-----------|
| **Production precedent** | No major SBOM or build tool uses eBPF for compiler interception (as of early 2026) |
| **Portability** | Linux 5.x+ only — not portable to Windows, macOS, or older Linux |
| **Complexity** | BPF verifier constraints, 512-byte stack limit, argv parsing in userspace |
| **Go coverage** | `-toolexec` covers Go better; eBPF doesn't solve the `-a` problem |
| **Language-native wrappers** | `CC=`, `-toolexec`, `RUSTC_WRAPPER` are simpler and proven |

**Conclusion:** Language-native wrappers are the priority path. eBPF is a
future extensibility point for edge cases where no wrapper mechanism exists.

eBPF would only be justified if:

1. Go never gets `-toolexec` cache integration (Go issue #41145)
2. A language emerges with no compiler wrapper mechanism
3. Truly zero-modification interception is required (no `CC=`, no `-toolexec`)

---

<a id="ebomf"></a>

## 6. External Project: ebomf (eBPF-Based OmniBOR)

**Repository:** https://github.com/marctjones/ebomf (private — access
pending)

**Author:** Marc T. Jones

### What It Does

ebomf is an external project that uses eBPF (not seccomp-BPF) for build
interception to generate OmniBOR manifests. It operates as a sidecar — it
monitors any build process and constructs the DAG of files touched during
the build, associating build artifacts with their corresponding gitoids.

### Key Characteristics

- **Language-agnostic:** Tested with C, Rust, Java, Python, and Node.js
  builds. Because eBPF operates at the kernel syscall level, it does not
  require language-specific hooks or compiler wrappers.
- **Non-invasive:** The build runs as the current user, completely
  unmodified. No `CC=` overrides, no `-toolexec`, no strace wrapping.
- **Requires sudo:** The eBPF program must be loaded with root privileges
  (standard eBPF requirement for tracepoint attachment). Once loaded, the
  monitored build process runs as the normal user.
- **Sidecar architecture:** Observation-only — does not modify the build
  process or inject any instrumentation into the compiled artifacts.

### Comparison to Current bomsh/strace Approach

| Aspect | bomsh/bomtrace (current) | ebomf (eBPF) |
|--------|-------------------------|--------------|
| **Interception mechanism** | ptrace (bomtrace3) or strace | eBPF tracepoints |
| **Tracee stopped?** | Yes — 2 context switches per traced syscall | No — tracee never stopped |
| **Overhead** | 20–60% (varies by language and project size) | Expected to be significantly lower (TBD — limited testing) |
| **Language support** | C/C++, Go, Rust, Java (each with different tracer) | Language-agnostic (C, Rust, Java, Python, Node.js tested) |
| **Root required?** | No (`SYS_PTRACE` capability sufficient) | Yes (sudo for eBPF program load) |
| **Build modification** | None (wraps the build command) | None (observes via kernel) |
| **Platform** | Linux only | Linux only (eBPF is Linux-specific) |
| **Maturity** | Production — used for all omnibor-analysis runs | Early stage — limited testing |

### Potential Impact

If ebomf proves reliable at scale, it could address several limitations
of the current ptrace-based approach:

1. **Eliminates the single-threaded tracer bottleneck** — eBPF programs
   run in-kernel at the tracepoint, writing to ring buffers. No single
   ptrace event loop serializing all events.
2. **Eliminates per-syscall context switches** — the dominant overhead
   source in bomtrace3 (18 of 40 percentage points).
3. **Unifies language support** — one interception mechanism for all
   languages, instead of four different tracers with different
   configurations.
4. **Simplifies the sidecar story** — no need for compiler wrappers
   (`CC=`, `-toolexec`, `RUSTC_WRAPPER`) which have build-system
   compatibility issues.

### Open Questions

- How does it handle file-to-artifact association accuracy compared to
  bomsh's hash_tree / treedb approach?
- What is the measured overhead on large projects (FFmpeg, Node.js,
  spring-boot)?
- How does it handle multi-module builds (e.g., Gradle subprojects,
  Maven multi-module)?
- Does it produce OmniBOR ADG-compatible output that can feed into our
  existing SPDX generation pipeline?
- What kernel version is the minimum requirement?
- How does the sudo requirement affect CI/CD integration (GitHub Actions,
  Jenkins, etc.)?

### Status

Access to the repository has been requested. Further evaluation pending.

---

<a id="cross-platform"></a>

## 7. Cross-Platform Applicability

Both seccomp-BPF and eBPF are Linux-specific:

| Platform | eBPF Available? | seccomp-BPF Available? | Alternative |
|----------|----------------|----------------------|-------------|
| **Linux** | Yes (4.x+) | Yes (3.5+) | — |
| **Windows** | Networking only (no tracepoints) | No | ETW + Minifilter driver |
| **macOS** | No | No | Endpoint Security / DTrace (SIP-blocked) |
| **FreeBSD** | No | No | DTrace (no SIP restrictions) |

See `cross-platform-applicability.md` for detailed per-platform analysis.

---

<a id="extensibility"></a>

## 8. Architecture Extensibility

The sidecar implementation design (`sidecar-implementation-design.md`)
includes an extensibility point for eBPF via the strategy pattern:

```python
class EbpfStrategy(InterceptionStrategy):
    def instrument_command(self, build_cmd, config):
        # Attach eBPF program, run build unmodified
        ...

    def generate_adg(self, output_dir):
        # Read ring buffer data, build ADG
        ...
```

Selected via config:

```yaml
omnibor:
  sidecar:
    strategy: ebpf  # Selects EbpfStrategy
```

No pipeline code changes would be required — the strategy plugs into the
existing architecture.

---

<a id="references"></a>

## 9. References

1. **Paul Chaignon, "Introducing strace --seccomp-bpf" (2019):**
   https://pchaigno.github.io/strace/2019/10/02/introducing-strace-seccomp-bpf.html

2. **Linux kernel seccomp-bpf documentation:**
   https://docs.kernel.org/userspace-api/seccomp_filter.html

3. **eBPF ecosystem documentation:**
   https://ebpf.io/

4. **eBPF for Windows (networking only, no tracepoints):**
   https://github.com/microsoft/ebpf-for-windows

5. **ebomf — eBPF-based OmniBOR manifest generation:**
   https://github.com/marctjones/ebomf

6. **OmniBOR Performance Optimization Proposal (Strategies 2 and 6):**
   `omnibor-performance-optimization-proposal.md`

7. **Cross-Platform Applicability Analysis:**
   `cross-platform-applicability.md`

8. **Sidecar Refactoring Plan (eBPF deprioritization):**
   `sidecar-refactoring-plan.md`

9. **Sidecar Implementation Design (Strategy pattern extensibility):**
   `sidecar-implementation-design.md`

---

<a id="appendix-a"></a>

## Appendix A: Feasibility — Replacing bomtrace/strace with ebomf

### Blocker: Repository Access Pending

The ebomf repo at `https://github.com/marctjones/ebomf` is private. Until
access is granted, we cannot evaluate the output format, CLI interface, or
metadata captured. The analysis below is based on the user's limited testing
and the known properties of eBPF tracepoint programs.

### What Would Change

| Component | Current (ptrace/strace) | With ebomf (eBPF) |
|-----------|------------------------|-------------------|
| **Docker capability** | `SYS_PTRACE` + `seccomp:unconfined` | `CAP_BPF` + `CAP_PERFMON` (or `CAP_SYS_ADMIN` on kernel <5.8) |
| **C/C++ tracer** | `bomtrace3 make -j$(nproc)` | `ebomf <build_cmd>` (TBD) |
| **Go tracer** | `bomtrace2 -c bomtrace_go.conf go build -a` | `ebomf go build` (no `-a` needed?) |
| **Rust tracer** | `bomtrace2 cargo build --release` | `ebomf cargo build --release` |
| **Java tracer** | `strace --seccomp-bpf -e trace=openat mvn package` | `ebomf mvn package` |
| **ADG generation** | `bomsh_create_bom.py` / `bomsh_create_bom_java.py` | ebomf's DAG output (format TBD) |
| **SPDX generation** | `AdgSpdxGenerator` / `JavaSpdxGenerator` | Likely reusable with adapter layer |
| **bomsh dependency** | Required (patched strace + Python scripts) | **Eliminated** |

### What Would Stay the Same

- **SPDX emission** — `app/spdx/` generators write SPDX JSON from
  structured data. As long as ebomf's output can be parsed into the same
  internal model, these stay.
- **Config-driven pipeline** — `app/config.yaml` repo definitions, build
  steps, etc.
- **Golden file comparison** — same baselines, same validation.
- **Syft baseline SBOMs** — independent of interception mechanism.

### Integration Design

The strategy pattern in `sidecar-implementation-design.md` was designed
for exactly this scenario:

```python
class EbomfStrategy(InterceptionStrategy):
    def instrument_command(self, build_cmd, config):
        # sudo ebomf --output <adg_path> -- <build_cmd>
        ...

    def generate_adg(self, output_dir):
        # Parse ebomf's DAG output into treedb-compatible format
        ...
```

The **adapter layer** between ebomf's output format and our SPDX
generators is the main engineering work.

### Key Advantages If Proven Reliable

1. **Eliminates the single-threaded tracer bottleneck** — eBPF programs
   run in-kernel at the tracepoint, writing to ring buffers. No single
   ptrace event loop serializing all events.
2. **Eliminates per-syscall context switches** — the dominant overhead
   source in bomtrace3 (18 of 40 percentage points).
3. **Unifies language support** — one interception mechanism for all
   languages, instead of four different tracers with different
   configurations.
4. **Simplifies the sidecar story** — no need for compiler wrappers
   (`CC=`, `-toolexec`, `RUSTC_WRAPPER`) which have build-system
   compatibility issues.
5. **Eliminates bomsh dependency** — the patched strace (bomtrace3),
   bomtrace2, and the Python hook scripts would no longer be needed.

### Key Risks and Open Questions

| Risk | Severity | Detail |
|------|----------|--------|
| **Accuracy vs treedb** | High | Does ebomf's DAG produce equivalent or better provenance chains compared to bomsh's hash_tree / treedb? |
| **Multi-module builds** | High | Gradle buildSrc caching, Maven multi-module — does ebomf see the same blind spots? |
| **Capability grant on customer build machines** | **High** | The sidecar runs on customer infrastructure, not ours. Enterprise build machines may run RHEL 8 (kernel 4.18, needs `CAP_SYS_ADMIN`), have SELinux enforcing, or prohibit kernel instrumentation via corporate policy. Sidecar must detect and degrade gracefully. |
| **Kernel version floor** | Medium | eBPF tracepoints require Linux 4.x+. `CAP_BPF` (instead of `CAP_SYS_ADMIN`) requires 5.8+. |
| **Output format compatibility** | Medium | Unknown whether ebomf produces treedb-compatible JSON, ADG, or a novel format requiring a new adapter. |
| **Go `-a` flag** | Low | If ebomf sees all file I/O at the kernel level, the mandatory `-a` cache bypass for Go may no longer be needed. Needs verification. |

### Recommended Evaluation Steps

1. **Get access** to `marctjones/ebomf`
2. **Run ebomf on one repo per language** from our test matrix:
   - C/C++: curl
   - Go: fzf
   - Rust: oxipng
   - Java: spring-boot
3. **Capture and document ebomf's output format** — structure, fields,
   how it maps to our treedb/ADG model
4. **Compare ebomf's DAG against our treedb** for the same builds —
   identify gaps and extras
5. **Compare SPDX derived from ebomf against golden files** — write
   adapter if needed, then run `scripts/compare_golden.py`
6. **Measure overhead** on the same EC2 instance (c6i.xlarge) for
   apples-to-apples comparison against bomtrace3/bomtrace2/strace
7. **Decision gate:** If accuracy matches golden files and overhead is
   lower, proceed with full integration. If accuracy gaps exist, document
   them and assess whether they are fixable.
