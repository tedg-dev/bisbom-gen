# Strategy 2: seccomp-bpf Syscall Filter

**Impact:** 15 percentage points reduction (29% → 14%)

**Complexity:** Medium

**Target budget category:** ptrace context switches (18pp → 3pp)

## The Problem

bomtrace3 currently traces **all** syscalls that strace traces by default. A single
gcc invocation makes **200–500 syscalls**:

```text
execve, brk, mmap, access, openat, fstat, read, close, mmap,
mprotect, arch_prctl, set_tid_address, set_robust_list,
rt_sigaction, rt_sigprocmask, prlimit64, stat, openat, read,
close, stat, openat, read, close, stat, stat, stat, openat,
fstat, mmap, close, stat, openat, read, fstat, mmap, close,
write, write, exit_group, ...
```

Of these, **only `execve` is needed** for build interception. The `open`/`openat` calls
are useful but not essential — bomsh already discovers input files from gcc's `-MD`
dependency output and argv parsing.

Each traced syscall requires **2 kernel context switches** (stop tracee + resume tracee).
For 400 syscalls per gcc invocation, that's **800 context switches per compilation
unit** — and only 2 of them (the `execve` stop + resume) are actually needed.

## Measured Proof: Linux Kernel Build with strace --seccomp-bpf

This is not a theoretical optimization. Paul Chaignon (strace maintainer) introduced
`--seccomp-bpf` in strace 5.3 and published measured results on a **Linux kernel build**
— the gold-standard benchmark for build tracing overhead:

| Build Mode | Wall Time | Overhead vs Native |
|------------|----------|-------------------|
| `make -j$(nproc)` (native, no tracing) | **12m 27s** | — |
| `strace -f -econnect make -j$(nproc)` (ptrace, no filter) | **24m 54s** | **~100%** |
| `strace -f -econnect --seccomp-bpf make -j$(nproc)` | **12m 49s** | **~3%** |

*(Source: Paul Chaignon, ["Introducing strace --seccomp-bpf"](https://pchaigno.github.io/strace/2019/10/02/introducing-strace-seccomp-bpf.html),
strace maintainer, 2019. Also presented at FOSDEM 2020.)*

**seccomp-bpf reduced tracing overhead from ~100% to ~3%** — nearly eliminating it.
The mechanism: instead of 2 context switches per syscall (stop + resume), the kernel's
BPF filter runs inline at the syscall entry point and returns `SECCOMP_RET_ALLOW` for
irrelevant syscalls — the tracee is **never stopped**. Only the syscalls matching the
filter cause a `SECCOMP_RET_TRACE` which notifies the tracer.

The independent seccomp-bpf benchmark by Zatoichi Engineering confirmed the per-syscall
cost: **~5.8 μs overhead per filtered syscall** — but this is the in-kernel BPF
evaluation cost, which is negligible compared to the **~20–30 μs per ptrace
stop+resume context switch pair** that is eliminated.

## How This Applies to bomtrace3

bomtrace3 is a **patched strace 6.11**. The `--seccomp-bpf` infrastructure already
exists in its codebase. The key adaptation is configuring the BPF filter to match
bomsh's needs:

| Syscall | bomsh Needs It? | Why | Filter Action |
|---------|----------------|-----|---------------|
| `execve` | **Yes** | Pre-hook: identify compiler, parse argv, record command | `SECCOMP_RET_TRACE` |
| `exit_group` | **Yes** | Post-hook: process exit triggers hashing + logging | `SECCOMP_RET_TRACE` |
| `openat` | **Optional** | Can supplement `-MD` dependency discovery | `SECCOMP_RET_ALLOW` |
| All others (~398/400) | **No** | `brk`, `mmap`, `mprotect`, `stat`, `read`, `write`, `close`, etc. | `SECCOMP_RET_ALLOW` |

The filter allows ~99% of syscalls to pass through without stopping the tracee.

## Viability Across All Compilers and Build Toolsets

> *"Do all compilers work this way? Is this viable for all build toolsets?"*

**Yes.** seccomp-bpf operates at the kernel level, below the application layer. It
doesn't modify compiler behavior — it filters which kernel events the tracer sees.
Every program that runs on Linux makes syscalls through the same kernel interface,
regardless of language or toolchain:

| Build Tool | Uses `execve`? | Uses `fork`/`clone` + `exec`? | seccomp-bpf Compatible? |
|-----------|---------------|------------------------------|------------------------|
| **gcc/g++** | Yes — `cc1`, `cc1plus`, `as`, `collect2`, `ld` | Yes — gcc spawns subprocesses | **Yes** |
| **clang/LLVM** | Yes — `clang`, `ld.lld` | Yes — same pattern as gcc | **Yes** |
| **MSVC (cross-compile)** | N/A (Windows only) | N/A | N/A |
| **Go compiler** (`compile`, `link`) | Yes — invoked via `go build` | Yes — Go toolchain forks | **Yes** |
| **rustc** | Yes — invoked by `cargo` | Yes — cargo spawns rustc | **Yes** |
| **javac** (via Maven/Gradle) | Yes — JVM invokes javac | Yes — build tool spawns JVM | **Yes** |
| **make** | Yes — spawns compiler processes | Yes — make forks per recipe | **Yes** |
| **cmake** (via Ninja/make) | Yes — delegates to underlying build | Yes | **Yes** |
| **Bazel** | Yes — spawns sandboxed actions | Yes — each action is a subprocess | **Yes** |
| **Meson** (via Ninja) | Yes — delegates to Ninja | Yes | **Yes** |

**The reason is fundamental:** seccomp-bpf filters are inherited by all child
processes (this is mandated by the Linux kernel's seccomp architecture). When
bomtrace3 installs a filter and then runs `make -j16`, every forked compiler
process inherits the filter. The filter is transparent to the compiler — it
doesn't change what syscalls the compiler can make (all are `ALLOW`ed). It only
changes which ones cause the tracer to wake up.

This is the same mechanism used by:
- **Docker/containerd** — seccomp profiles filter syscalls for every containerized process
- **Chromium** — seccomp-bpf sandboxes the renderer process (which runs V8, Skia, etc.)
- **Firefox** — seccomp-bpf sandboxes content processes
- **Android** — seccomp-bpf is mandatory for all apps since Android 8.0
- **systemd** — `SystemCallFilter=` directive uses seccomp-bpf for service sandboxing

All of these filter syscalls for arbitrary programs — compilers, interpreters,
JVMs, runtimes — without any application-level changes.

## Quantified Impact on bomtrace3

Applying the kernel build benchmark proportionally to bomtrace3's overhead budget:

| Metric | Current bomtrace3 | With seccomp-bpf |
|--------|-------------------|-----------------|
| Syscalls per gcc invocation | ~400 | ~400 (unchanged) |
| Syscalls causing ptrace stops | ~400 (all) | ~2 (`execve` + `exit_group`) |
| Context switches per gcc invocation | ~800 (2 per syscall) | ~4 (2 per filtered syscall) |
| ptrace overhead (18pp of 40pp total) | 18pp | ~1–3pp |
| **Expected reduction** | — | **~15pp** |

The strace kernel build benchmark showed a reduction from ~100% overhead to ~3%.
bomtrace3's overhead is lower because it doesn't decode/print syscalls, but the
proportional reduction in context switch overhead is the same.
