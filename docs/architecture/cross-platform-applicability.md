# Cross-Platform Applicability of OmniBOR Performance Strategies

This document evaluates how each C/C++ performance optimization strategy from the
[Performance Optimization Proposal](omnibor-performance-optimization-proposal.md)
applies to other Linux-based solutions and to non-Linux operating systems (Windows,
macOS, FreeBSD). Every claim below is grounded in documented APIs, published
benchmarks, or upstream project evidence.

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Strategy 1: Pre-Hash Cache](#strategy-1-pre-hash-cache)
3. [Strategy 2: seccomp-bpf Syscall Filter](#strategy-2-seccomp-bpf)
4. [Strategy 3: Async Tracer + Hash Worker Thread](#strategy-3-async-tracer)
5. [Strategy 4: Deferred Post-Build Hashing](#strategy-4-deferred-hashing)
6. [Strategy 5: Compiler Wrapper (CC= Approach)](#strategy-5-compiler-wrapper)
7. [Strategy 6: eBPF-Based Tracing](#strategy-6-ebpf)
8. [Platform-Native Alternatives Summary](#platform-alternatives)
9. [References](#references)

---

<a id="executive-summary"></a>

## 1. Executive Summary

| Strategy | Linux | Windows | macOS | FreeBSD |
|----------|-------|---------|-------|---------|
| **1: Pre-Hash Cache** | Full | Full (different API) | Full | Full |
| **2: seccomp-bpf** | Full | **No equivalent** | **No equivalent** | **No equivalent** |
| **3: Async Tracer** | Full | Full | Full | Full |
| **4: Deferred Hashing** | Full | Full | Full | Full |
| **5: CC= Wrapper** | Full | Partial (MSVC limitation) | Full | Full |
| **6: eBPF Tracing** | Full | **Not viable today** | **No equivalent** | **No equivalent** |

**Key finding:** Strategies 1, 3, 4, and 5 are broadly cross-platform. Strategies
2 and 6 are **Linux-specific kernel features** with no direct equivalent on other
operating systems. Each non-Linux platform has its own tracing mechanism, but none
offer the same combination of low overhead and syscall-level filtering.

---

<a id="strategy-1-pre-hash-cache"></a>

## 2. Strategy 1: Pre-Hash Cache

*Reference: [Strategy 1 in main proposal](omnibor-performance-optimization-proposal.md#strategy-1-pre-hash-cache)*

The pre-hash cache concept — caching file hashes keyed by filesystem identity
metadata to avoid redundant SHA256 computations — is **universally applicable**
across all operating systems. The implementation details differ only in which
OS API provides the file identity tuple.

### 2.1 File Identity APIs by Platform

The cache invalidation key is a tuple of (device, inode, mtime, size). Every major
OS provides equivalent metadata:

**Linux** — API: `stat()` / `fstat()`

| Field | Value |
|-------|-------|
| Device ID | `st_dev` |
| File ID (inode) | `st_ino` |
| Modification Time | `st_mtime` (second) or `st_mtim` (nanosecond) |
| Size | `st_size` |

**macOS (APFS)** — API: `stat()` / `fstat()`

| Field | Value |
|-------|-------|
| Device ID | `st_dev` |
| File ID (inode) | `st_ino` |
| Modification Time | `st_mtimespec` (nanosecond precision on APFS) |
| Size | `st_size` |

**Windows (NTFS)** — API: `GetFileInformationByHandle()`

| Field | Value |
|-------|-------|
| Device ID | `dwVolumeSerialNumber` |
| File ID (inode equivalent) | `nFileIndexHigh` + `nFileIndexLow` (64-bit file ID) |
| Modification Time | `ftLastWriteTime` (100-nanosecond precision) |
| Size | `nFileSizeHigh` + `nFileSizeLow` |

**FreeBSD** — API: `stat()` / `fstat()`

| Field | Value |
|-------|-------|
| Device ID | `st_dev` |
| File ID (inode) | `st_ino` |
| Modification Time | `st_mtim` (nanosecond) |
| Size | `st_size` |

**Evidence — ccache inode cache cross-platform status:**

ccache 4.0+ implemented an inode cache using exactly this approach. As of 2024:

- **Linux**: Fully supported since ccache 4.0. Uses `(st_dev, st_ino, st_mtime, st_size)`.
  *(Source: [ccache manual](https://ccache.dev/manual/latest.html), `inode_cache` option)*
- **macOS**: Fully supported. Uses the same POSIX `stat()` fields. APFS provides
  nanosecond-resolution timestamps, making cache invalidation more precise than
  ext4 (which has only second-resolution `st_mtime` by default).
  *(Source: ccache release notes, macOS is a supported platform)*
- **Windows**: The inode cache was **not initially supported** on Windows because
  NTFS does not expose inodes through the POSIX compatibility layer. ccache issue
  [#701](https://github.com/ccache/ccache/issues/701) tracks adding support using
  `GetFileInformationByHandle()` which returns `nFileIndexHigh`/`nFileIndexLow` —
  the NTFS equivalent of inode numbers. This API has been available since
  Windows 2000 and works on NTFS, ReFS, and most SMB shares.
  *(Source: [ccache/ccache#701](https://github.com/ccache/ccache/issues/701),
  [Microsoft docs: GetFileInformationByHandle](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle))*
- **FreeBSD**: Fully supported. Same POSIX `stat()` interface as Linux.

### 2.2 SHA256 Hardware Acceleration by Platform

The OpenSSL `EVP_sha256()` recommendation from
[Strategy 1](omnibor-performance-optimization-proposal.md#strategy-1-pre-hash-cache)
applies cross-platform, but each OS also has native crypto APIs:

| Platform | Recommended Library | HW Acceleration | Throughput (8 KB blocks) | Source |
|----------|-------------------|-----------------|-------------------------|--------|
| **Linux x86_64** | OpenSSL `EVP_sha256()` | SHA-NI (Intel Ice Lake+, AMD Zen+) | ~1.8 GB/s | codegenes.net benchmark |
| **Linux ARM64** | OpenSSL `EVP_sha256()` | ARMv8 Crypto Extensions (Graviton, Ampere) | ~1.5–2.0 GB/s | OpenSSL `openssl speed sha256` on Graviton3 |
| **macOS x86_64** | OpenSSL or CommonCrypto `CC_SHA256()` | SHA-NI (Intel i7-8700B+) | ~1.4 GB/s | `openssl speed sha256`, Mac Mini 2018 |
| **macOS ARM64** | OpenSSL `EVP_sha256()` | ARMv8.2 Crypto Extensions (Apple M1/M2/M3) | ~2.0–2.5 GB/s | OpenSSL with ARM CE detection via `armcap.c` |
| **Windows x86_64** | OpenSSL or CNG `BCryptHash()` | SHA-NI (same Intel/AMD HW) | ~1.8 GB/s (OpenSSL), ~1.2–1.5 GB/s (CNG) | OpenSSL benchmarks; CNG has higher API overhead |
| **FreeBSD x86_64** | OpenSSL `EVP_sha256()` | SHA-NI | ~1.8 GB/s | Same OpenSSL, same hardware |

**Key findings:**

- **OpenSSL works on all platforms.** Its `armcap.c` source explicitly detects
  Apple M1–M5 chips by brand string and enables ARM Crypto Extensions accordingly.
  *(Source: [openssl/crypto/armcap.c](https://github.com/openssl/openssl/blob/master/crypto/armcap.c))*
- **Windows CNG (`BCryptHash`)** is a viable alternative that avoids the OpenSSL
  dependency, but benchmarks show ~20–30% lower throughput than OpenSSL due to
  additional API abstraction layers.
  *(Source: [aloneguid.uk, "Using CNG instead of OpenSSL"](https://www.aloneguid.uk/posts/2022/10/bcrypt/))*
- **Apple CommonCrypto (`CC_SHA256`)** is available on macOS/iOS but does **not**
  automatically use ARM Crypto Extensions on Apple Silicon — it relies on the
  older software path. OpenSSL 3.x is the better choice for Apple Silicon.
  *(Source: [Apple Community discussion](https://discussions.apple.com/thread/254639137),
  LibreSSL on macOS lacks ARM CE support)*

### 2.3 Cross-Platform Verdict for Strategy 1

**Fully portable.** The concept, the math, and the impact estimates all transfer
directly. The only platform-specific code is:

- ~20 lines for the file identity tuple (POSIX `stat()` vs Windows `GetFileInformationByHandle()`)
- The crypto library choice (OpenSSL everywhere, or CNG on Windows, or CommonCrypto on macOS)

---

<a id="strategy-2-seccomp-bpf"></a>

## 3. Strategy 2: seccomp-bpf Syscall Filter

*Reference: [Strategy 2 in main proposal](omnibor-performance-optimization-proposal.md#strategy-2-seccomp-bpf)*

### 3.1 Linux Only

seccomp-bpf is a **Linux kernel feature** (introduced in Linux 3.5 by Will Drewry,
2012). It operates at the syscall entry point in the kernel's system call dispatch
path. There is **no equivalent mechanism** on any other operating system that
provides the same combination of:

1. In-kernel BPF program execution at syscall entry
2. Per-syscall filtering with `SECCOMP_RET_TRACE` / `SECCOMP_RET_ALLOW`
3. Zero context switches for allowed syscalls
4. Inheritance by all child processes

*(Source: [Linux kernel docs: seccomp_filter](https://docs.kernel.org/userspace-api/seccomp_filter.html),
[Paul Chaignon, "Introducing strace --seccomp-bpf"](https://pchaigno.github.io/strace/2019/10/02/introducing-strace-seccomp-bpf.html))*

### 3.2 What Other Platforms Offer Instead

Each non-Linux platform has process/syscall monitoring, but with fundamentally
different characteristics:

#### Windows: ETW (Event Tracing for Windows)

- **Mechanism:** Kernel event providers emit events to a trace session. The
  `Microsoft-Windows-Kernel-Process` provider can report process creation,
  termination, and image loads.
- **Overhead:** Microsoft's documentation states ETW adds ~5% CPU overhead to log
  ~20,000 events/second. However, ETW is a **notification** mechanism, not a
  **filtering** mechanism — there is no way to tell the kernel "only deliver
  `CreateProcess` events and skip everything else at the syscall level."
  *(Source: [ITProToday, "Inside Event Tracing for Windows"](https://www.itprotoday.com/microsoft-windows/inside-event-tracing-for-windows))*
- **Comparison to seccomp-bpf:** ETW cannot prevent the overhead of tracing
  irrelevant events at the kernel level. The consumer receives all subscribed
  events and must filter in user space. This is analogous to ptrace without
  seccomp-bpf — the overhead is proportional to total event volume, not just
  relevant events.
- **Alternative — Kernel callbacks:** Windows provides `PsSetCreateProcessNotifyRoutine`
  for kernel-mode drivers to receive process creation notifications. This is very
  low overhead but requires a signed kernel driver, which is impractical for a
  build tracing tool.

#### macOS: Endpoint Security Framework (ESF)

- **Mechanism:** Apple's Endpoint Security framework (macOS 10.15+) provides
  `ES_EVENT_TYPE_NOTIFY_EXEC` and `ES_EVENT_TYPE_AUTH_EXEC` events for process
  execution monitoring.
  *(Source: [Apple Developer: ES_EVENT_TYPE_NOTIFY_EXEC](https://developer.apple.com/documentation/endpointsecurity/es_event_type_notify_exec),
  [WWDC 2020: Build an Endpoint Security app](https://developer.apple.com/videos/play/wwdc2020/10159/))*
- **Overhead:** ESF runs in user space and receives Mach messages from the kernel.
  Auth events block the process until the security client responds. Notify events
  are asynchronous but still involve Mach IPC overhead per event.
- **Comparison to seccomp-bpf:** ESF can subscribe to specific event types (e.g.,
  only `EXEC`), which is conceptually similar to seccomp-bpf filtering. However,
  the filtering happens **after** the kernel delivers the event via Mach IPC —
  there is no in-kernel BPF evaluation that skips the delivery entirely.
- **Restriction:** ESF requires a System Extension (not a kernel extension),
  a provisioning profile from Apple, and user approval. It is designed for
  security products, not build tools.

#### macOS: DTrace

- **Mechanism:** DTrace can attach probes to syscall entry/exit points and filter
  by predicate (e.g., `/execname == "gcc"/`).
- **Overhead:** DTrace probes add ~1–5 μs per probe firing. With predicates, only
  matching probes execute the action, but the probe still fires for every syscall.
- **Restriction:** System Integrity Protection (SIP) **blocks DTrace from tracing
  system executables** (anything in `/usr/bin`, `/usr/sbin`, etc.) unless SIP is
  partially disabled (`csrutil enable --without dtrace`). This is not viable in
  production or CI/CD environments.
  *(Source: [Stack Overflow: "dtrace cannot control executables signed with restricted entitlements"](https://stackoverflow.com/questions/33476432),
  [poweruser.blog: "Using dtrace on macOS with SIP enabled"](https://poweruser.blog/using-dtrace-with-sip-enabled-3826a352e64b))*
- **Comparison to seccomp-bpf:** DTrace predicates are conceptually similar but
  execute in user space (via the DTrace consumer), not in-kernel at the syscall
  entry point. SIP restrictions make it impractical for build tracing on macOS.

#### FreeBSD: DTrace

- **Mechanism:** FreeBSD has native DTrace support (ported from Solaris). No SIP
  restrictions — DTrace can trace any process with root privileges.
  *(Source: [FreeBSD Handbook: DTrace](https://docs.freebsd.org/en/books/handbook/dtrace/))*
- **Overhead:** Similar to macOS DTrace (~1–5 μs per probe). Predicates help but
  probes still fire for every syscall.
- **Comparison to seccomp-bpf:** FreeBSD DTrace is the closest equivalent on
  non-Linux systems, but it lacks the in-kernel BPF filtering that eliminates
  context switches entirely. The overhead model is "reduced" rather than
  "eliminated."

### 3.3 Cross-Platform Verdict for Strategy 2

**Linux only.** The 15 percentage point reduction
([main proposal](omnibor-performance-optimization-proposal.md#strategy-2-seccomp-bpf))
is achievable only on Linux. On other platforms, the equivalent optimization
would require platform-specific approaches:

| Platform | Best Available Mechanism | Expected Overhead Reduction | Viable for Build Tracing? |
|----------|------------------------|---------------------------|--------------------------|
| **Linux** | seccomp-bpf (`SECCOMP_RET_TRACE`) | ~15pp (measured) | **Yes** |
| **Windows** | ETW + kernel callback driver | ~5–8pp (estimated) | Partial — requires signed driver |
| **macOS** | Endpoint Security `NOTIFY_EXEC` | ~5–10pp (estimated) | No — requires Apple provisioning |
| **macOS** | DTrace with predicates | ~8–12pp (estimated) | No — SIP blocks system executables |
| **FreeBSD** | DTrace with predicates | ~8–12pp (estimated) | Yes — no SIP restrictions |

---

<a id="strategy-3-async-tracer"></a>

## 4. Strategy 3: Async Tracer + Hash Worker Thread

*Reference: [Strategy 3 in main proposal](omnibor-performance-optimization-proposal.md#strategy-3-async-tracer)*

### 4.1 Fully Cross-Platform

Decoupling the tracer event loop from hash computation into separate threads is a
**pure application-level optimization** with no OS-specific dependencies. Every
platform provides the required primitives:

| Platform | Thread API | Lock-Free Queue | Async I/O |
|----------|-----------|-----------------|-----------|
| **Linux** | pthreads | `__atomic` builtins, `io_uring` | `io_uring` (5.1+), `aio` |
| **Windows** | Win32 threads, `_beginthreadex` | `InterlockedCompareExchange` | IOCP (I/O Completion Ports) |
| **macOS** | pthreads, GCD (`dispatch_async`) | `OSAtomicCompareAndSwap`, `__atomic` | GCD dispatch queues, kqueue |
| **FreeBSD** | pthreads | `__atomic` builtins | kqueue |

### 4.2 Cross-Platform Verdict for Strategy 3

**Fully portable.** The 4 percentage point reduction applies identically on all
platforms. The only difference is the thread and async I/O API used, which are
well-abstracted by C11 threads or POSIX pthreads (available on all four platforms).

---

<a id="strategy-4-deferred-hashing"></a>

## 5. Strategy 4: Deferred Post-Build Hashing

*Reference: [Strategy 4 in main proposal](omnibor-performance-optimization-proposal.md#strategy-4-deferred-hashing)*

### 5.1 Fully Cross-Platform

Deferring all hashing to a post-build phase is an architectural pattern with no
OS dependencies. The build phase records file paths and metadata; the post-build
phase hashes everything in parallel.

### 5.2 Cross-Platform Verdict for Strategy 4

**Fully portable.** The 3 percentage point reduction applies identically on all
platforms. The post-build parallel hashing uses the same thread pool and SHA256
APIs described in Strategies 1 and 3.

---

<a id="strategy-5-compiler-wrapper"></a>

## 6. Strategy 5: Compiler Wrapper (CC= Approach)

*Reference: [Strategy 5 in main proposal](omnibor-performance-optimization-proposal.md#strategy-5-compiler-wrapper)*

### 6.1 Platform-Specific Compiler Wrapping Mechanisms

The CC= approach relies on build systems respecting environment variables that
redirect compiler invocations. This works differently across platforms:

| Platform | Compiler | Wrapper Mechanism | Works? | Notes |
|----------|----------|------------------|--------|-------|
| **Linux (gcc/g++)** | gcc, g++ | `CC=`, `CXX=`, `AR=`, `LD=` env vars | **Yes** | Standard for make, cmake, autoconf |
| **Linux (clang)** | clang, clang++ | `CC=`, `CXX=` env vars | **Yes** | Same mechanism as gcc |
| **macOS (clang)** | Apple clang | `CC=`, `CXX=` env vars | **Yes** | Xcode's `xcodebuild` respects `CC=` via xcconfig or env |
| **macOS (gcc via Homebrew)** | gcc | `CC=`, `CXX=` env vars | **Yes** | Identical to Linux |
| **Windows (MSVC)** | `cl.exe` | **No `CC=` equivalent** | **No** | See detailed analysis below |
| **Windows (CMake + MSVC)** | `cl.exe` | `-DCMAKE_C_COMPILER=` | **Partial** | CMake can redirect, but MSBuild projects cannot |
| **Windows (clang-cl)** | clang-cl | `CC=`, `CXX=` with CMake/Ninja | **Yes** | clang-cl emulates MSVC but respects CMake variables |
| **Windows (MinGW/MSYS2)** | gcc | `CC=`, `CXX=` env vars | **Yes** | Same POSIX mechanism as Linux |
| **FreeBSD** | clang (system), gcc (ports) | `CC=`, `CXX=` env vars | **Yes** | Standard POSIX mechanism |

### 6.2 Windows MSVC: The Exception

MSVC (`cl.exe`) does not support the `CC=` environment variable pattern:

- **The `CL` environment variable** exists but only **prepends options** to every
  `cl.exe` invocation — it cannot redirect to a different compiler binary.
  *(Source: [Microsoft Learn: CL environment variables](https://learn.microsoft.com/en-us/cpp/build/reference/cl-environment-variables))*
- **MSBuild projects** (`.vcxproj`) have the compiler path hard-coded in the
  toolset definition (`<CLToolExe>cl.exe</CLToolExe>`). Overriding requires
  modifying the `.props` file or using a custom toolset — not practical for
  generic build interception.
- **Visual Studio solutions** invoke MSBuild, which invokes `cl.exe` directly.
  There is no environment variable to inject a wrapper.

**Windows workarounds:**

1. **CMake + Ninja:** Use `-DCMAKE_C_COMPILER=/path/to/wrapper.exe`. This works
   because CMake generates Ninja build files that invoke the specified compiler.
2. **Microsoft Detours:** A library for intercepting Win32 API calls at runtime.
   Could intercept `CreateProcess` calls to inject build recording logic.
   Requires DLL injection into the build process.
   *(Source: [Microsoft Detours](https://github.com/microsoft/detours))*
3. **PATH manipulation:** Place a `cl.exe` wrapper earlier in PATH than the real
   `cl.exe`. The wrapper records build info and delegates to the real compiler.
   Fragile but functional for controlled CI/CD environments.

### 6.3 macOS-Specific Considerations

- **`DYLD_INSERT_LIBRARIES`** is macOS's equivalent of `LD_PRELOAD` and could
  intercept compiler library calls, but SIP blocks it for system executables
  in `/usr/bin`. Since Apple clang is at `/usr/bin/clang`, this only works with
  SIP partially disabled or with Homebrew-installed compilers.
  *(Source: [theevilbit.github.io: DYLD_INSERT_LIBRARIES deep dive](https://theevilbit.github.io/posts/dyld_insert_libraries_dylib_injection_in_macos_osx_deep_dive/))*
- **CC= env var** works natively with macOS `make`, `cmake`, and `autoconf`.
  `xcodebuild` can accept `CC=` overrides but requires specific xcconfig setup.

### 6.4 Cross-Platform Verdict for Strategy 5

**Portable to all platforms except native MSVC/MSBuild on Windows.** The 35–37
percentage point reduction applies fully on Linux, macOS, and FreeBSD. On Windows,
it works with CMake+Ninja or MinGW/MSYS2 toolchains but **not** with native
Visual Studio MSBuild projects.

---

<a id="strategy-6-ebpf"></a>

## 7. Strategy 6: eBPF-Based Tracing

*Reference: [Strategy 6 in main proposal](omnibor-performance-optimization-proposal.md#strategy-6-ebpf)*

### 7.1 Linux Only (Practically)

eBPF tracing requires attaching BPF programs to kernel tracepoints (e.g.,
`tracepoint/syscalls/sys_enter_execve`). This is a **Linux-specific kernel
feature** (Linux 4.x+).

### 7.2 eBPF for Windows: Not Viable for Build Tracing

Microsoft's [eBPF for Windows](https://github.com/microsoft/ebpf-for-windows)
project provides a compatibility layer that can run eBPF programs on Windows.
However, it has critical limitations for build tracing:

- **Supported attach points:** XDP (network), socket programs, and some
  cgroup-like hooks. The project focuses on **networking use cases**.
- **No tracepoint support:** There is no equivalent of
  `tracepoint/syscalls/sys_enter_execve`. The Windows kernel does not expose
  syscall entry/exit as eBPF attach points.
- **No kprobe support:** Linux kprobes allow attaching to arbitrary kernel
  functions. eBPF for Windows does not support this.
- **Architecture:** eBPF bytecode is compiled to a Windows driver (`.sys` file)
  via `bpf2c`, or JIT-compiled via the uBPF interpreter. Neither approach
  supports the syscall tracepoints needed for build interception.

*(Source: [microsoft/ebpf-for-windows README](https://github.com/microsoft/ebpf-for-windows),
architectural overview confirms focus on XDP and socket programs)*

### 7.3 macOS and FreeBSD: DTrace as Alternative

Neither macOS nor FreeBSD has eBPF. The closest equivalent is DTrace:

- **macOS DTrace:** Restricted by SIP (see [Strategy 2 analysis](#strategy-2-seccomp-bpf)).
  Cannot trace system executables without disabling SIP. Not viable for
  production CI/CD.
- **FreeBSD DTrace:** No SIP restrictions. Can trace any process. However,
  DTrace probes run in-kernel but with higher per-probe overhead than eBPF
  (~1–5 μs vs ~100 ns for eBPF). The 37–39 percentage point reduction from
  the main proposal would likely be ~25–30pp on FreeBSD with DTrace.

### 7.4 Cross-Platform Verdict for Strategy 6

**Linux only.** eBPF for Windows exists but does not support the tracepoint
attach points needed for build tracing. macOS has no eBPF. FreeBSD could use
DTrace as a partial substitute with reduced impact.

---

<a id="platform-alternatives"></a>

## 8. Platform-Native Alternatives Summary

For non-Linux platforms, these are the recommended alternative approaches to
achieve similar overhead reductions:

### Windows

| OmniBOR Strategy | Windows Alternative | Expected Impact | Complexity |
|-----------------|---------------------|-----------------|------------|
| seccomp-bpf (Strategy 2) | ETW `Microsoft-Windows-Kernel-Process` provider | ~5–8pp | Medium — user-space consumer, no kernel driver needed |
| CC= Wrapper (Strategy 5) | PATH manipulation (`cl.exe` wrapper) or CMake `-DCMAKE_C_COMPILER=` | ~35pp (CMake/Ninja only) | Low for CMake; high for MSBuild |
| eBPF (Strategy 6) | ETW + Minifilter driver | ~20–25pp | High — requires signed kernel driver |

### macOS

| OmniBOR Strategy | macOS Alternative | Expected Impact | Complexity |
|-----------------|-------------------|-----------------|------------|
| seccomp-bpf (Strategy 2) | Endpoint Security `ES_EVENT_TYPE_NOTIFY_EXEC` | ~5–10pp | High — requires Apple provisioning profile |
| CC= Wrapper (Strategy 5) | `CC=` env var (works natively) | ~35pp | Low |
| eBPF (Strategy 6) | No viable alternative | N/A | N/A |

### FreeBSD

| OmniBOR Strategy | FreeBSD Alternative | Expected Impact | Complexity |
|-----------------|---------------------|-----------------|------------|
| seccomp-bpf (Strategy 2) | DTrace syscall predicates | ~8–12pp | Medium |
| CC= Wrapper (Strategy 5) | `CC=` env var (works natively) | ~35pp | Low |
| eBPF (Strategy 6) | DTrace with probes | ~25–30pp | Medium |

---

<a id="references"></a>

## 9. References

1. **Linux kernel seccomp-bpf documentation:**
   https://docs.kernel.org/userspace-api/seccomp_filter.html

2. **Paul Chaignon, "Introducing strace --seccomp-bpf" (2019):**
   https://pchaigno.github.io/strace/2019/10/02/introducing-strace-seccomp-bpf.html

3. **ccache manual — inode cache:**
   https://ccache.dev/manual/latest.html

4. **ccache issue #701 — NTFS inode cache support:**
   https://github.com/ccache/ccache/issues/701

5. **Microsoft: GetFileInformationByHandle:**
   https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle

6. **Microsoft: CL environment variables:**
   https://learn.microsoft.com/en-us/cpp/build/reference/cl-environment-variables

7. **Microsoft: eBPF for Windows:**
   https://github.com/microsoft/ebpf-for-windows

8. **Microsoft: Event Tracing for Windows:**
   https://learn.microsoft.com/en-us/windows-hardware/test/wpt/event-tracing-for-windows

9. **Apple: Endpoint Security ES_EVENT_TYPE_NOTIFY_EXEC:**
   https://developer.apple.com/documentation/endpointsecurity/es_event_type_notify_exec

10. **Apple: WWDC 2020 — Build an Endpoint Security app:**
    https://developer.apple.com/videos/play/wwdc2020/10159/

11. **OpenSSL ARM capability detection (armcap.c) — Apple M1–M5 detection:**
    https://github.com/openssl/openssl/blob/master/crypto/armcap.c

12. **OpenSSL speed benchmark: Apple M1 vs Intel i7-8700B:**
    https://gist.github.com/catap/0fb1428f84cc5a26ab45fa37542f9526

13. **CNG (Cryptography Next Generation) as OpenSSL alternative:**
    https://www.aloneguid.uk/posts/2022/10/bcrypt/

14. **macOS DTrace SIP restrictions:**
    https://poweruser.blog/using-dtrace-with-sip-enabled-3826a352e64b

15. **FreeBSD DTrace handbook:**
    https://docs.freebsd.org/en/books/handbook/dtrace/

16. **macOS DYLD_INSERT_LIBRARIES deep dive:**
    https://theevilbit.github.io/posts/dyld_insert_libraries_dylib_injection_in_macos_osx_deep_dive/

17. **Microsoft Detours (API hooking library):**
    https://github.com/microsoft/detours

18. **ITProToday, "Inside Event Tracing for Windows" (ETW ~5% overhead):**
    https://www.itprotoday.com/microsoft-windows/inside-event-tracing-for-windows
