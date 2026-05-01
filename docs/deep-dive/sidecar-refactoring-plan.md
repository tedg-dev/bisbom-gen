# Sidecar Architecture Refactoring Plan

| | |
|---|---|
| **Date** | 2026-05-01 |
| **Authors** | Ted G. (architect), Cascade AI |
| **Status** | Proposal — pending implementation |
| **Triggered by** | Review of clean-room → sidecar architecture gap across all source languages |
| **Prerequisites** | [Sidecar vs Clean-Room Analysis](sidecar-vs-cleanroom-analysis.md), [Performance Optimization Proposal](omnibor-performance-optimization-proposal.md), [Cross-Language Build Timing Improvements](cross-language-build-timing-improvements.md) |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Industry Validation](#3-industry-validation)
4. [Per-Language Sidecar Strategy](#4-per-language-sidecar-strategy)
   - [4.1 Java — strace openat / Maven dep:tree](#41-java-strace-openat--maven-deptree)
   - [4.2 C/C++ — CC= Wrapper](#42-cc-cc-wrapper)
   - [4.3 Go — -toolexec Wrapper](#43-go-toolexec-wrapper)
   - [4.4 Rust — RUSTC_WRAPPER](#44-rust-rustc_wrapper)
   - [4.5 Python — pip Metadata](#45-python-pip-metadata)
5. [Cross-Cutting Recommendations](#5-cross-cutting-recommendations)
   - [5.1 Wrapper Language Choice](#51-wrapper-language-choice)
   - [5.2 Dual-Mode Container Image](#52-dual-mode-container-image)
   - [5.3 ARM64 Support via Wrappers](#53-arm64-support-via-wrappers)
   - [5.4 eBPF — Deprioritize](#54-ebpf-deprioritize)
6. [Priority-Ordered Action Items](#6-priority-ordered-action-items)
7. [Bibliography](#7-bibliography)
8. [Appendix A: Source Code Audit — Current vs. Sidecar](#8-appendix-a-source-code-audit--current-vs-sidecar)
9. [Appendix B: Build Rules Impact Guide for Development Teams](#9-appendix-b-build-rules-impact-guide-for-development-teams)
   - [B.1 C/C++ (autoconf / CMake / Meson / Makefile)](#b1-cc-autoconf--cmake--meson--makefile)
   - [B.2 Go](#b2-go)
   - [B.3 Rust](#b3-rust)
   - [B.4 Java (Maven / Gradle)](#b4-java-maven--gradle)
   - [B.5 Python (pip / setuptools / poetry)](#b5-python-pip--setuptools--poetry)
   - [B.6 Cross-Language Concerns](#b6-cross-language-concerns)
10. [Appendix C: Reference Document Updates](#10-appendix-c-reference-document-updates)

---

<a id="1-executive-summary"></a>

## 1. Executive Summary

The `omnibor-analysis` project currently operates in **clean-room mode**: the
Docker container provides all build toolchains (gcc, Go, Rust, Java) and builds
source code internally. The generated SBOM reflects what the container builds —
not what the customer's CI/CD pipeline produces.

For enterprise adoption, the architecture must transition to **true sidecar
mode**: the container provides only interception and analysis tools, while
builds use the customer's native toolchains. The SBOM must reflect the
production binary.

This document evaluates the refactoring plan for each supported language,
validates the proposed strategies against industry best practices, and
identifies gaps and additions to the existing plan.

**Key findings:**

- **Java is already sidecar-compatible.** The strace+Maven/Gradle approach
  works with whatever JDK is on PATH — no wrappers or bomtrace needed.
  The only optimization is replacing strace with Maven `dep:tree` to
  eliminate the `SYS_PTRACE` capability requirement.
- **Python is metadata-only.** SBOM generation uses pip metadata and
  `dist-info` records — no build tracing needed, inherently cross-platform.
- **C/C++, Go, and Rust require compiler wrappers.** Language-native
  mechanisms (`CC=` for C/C++, `-toolexec` for Go, `RUSTC_WRAPPER` for
  Rust) are the industry-standard path to sidecar mode. Each is a proven,
  stable mechanism used by major tools (ccache, distcc, sccache, DataDog
  Orchestrion).
- **eBPF should be deprioritized** in favor of these wrapper-based
  approaches.
- **⚠️ Unrecognized benefit: ARM64 support unlocked at zero cost.** The
  wrapper-based sidecar architecture works on ARM64 (AWS Graviton, Apple
  Silicon) for C/C++, Go, and Rust without any bomtrace3 porting work.
  Wrappers have no architecture dependency — this eliminates the single
  largest platform blocker for enterprise adoption.

---

<a id="2-problem-statement"></a>

## 2. Problem Statement

### The Architectural Gap

The current `Dockerfile` installs all build toolchains into a single image:

| Category | What's installed |
|----------|-----------------|
| C/C++ toolchains | gcc 11, g++ 11, clang 14, make, cmake, autotools |
| Go SDK | Go 1.26.0 at `/usr/local/go/` |
| Rust toolchain | stable via rustup at `/root/.cargo/` |
| Java JDKs | OpenJDK 17 + 21, Maven 3.6 + 3.9 |
| OmniBOR tools | bomtrace3, bomtrace2, bomsh scripts |
| Analysis pipeline | Python scripts, Syft, spdx-tools |

Source repos are cloned inside the container and built using the container's
toolchains. This is **standalone / clean-room mode**. The SBOM reflects the
container's build environment, not any external build machine.

### Why This Matters

bomtrace3's value proposition is **transparent interception** — it observes a
build without changing it. If the container substitutes the build toolchain,
it is rebuilding in a controlled environment and producing an SBOM for *its
own* build. The checksums differ, the linked libraries differ, and the binary
is a different binary entirely.

**For open-source analysis** (the current demo use case), clean-room mode is
acceptable — there is no canonical "native" build environment for a GitHub
project.

**For production/enterprise adoption**, clean-room mode is insufficient.
Customers need SBOMs that match their actual CI/CD output — same compiler
version, same linked libraries, same binary. A standalone container with
fixed toolchains cannot serve this need — teams use different compiler
versions, different OS distributions, and different library versions.
Even if teams built custom standalone images with their own toolchains,
the maintenance burden would be significant and adoption would suffer.
Sidecar mode eliminates this problem entirely by using the team's native
toolchains.

*(Source: [sidecar-vs-cleanroom-analysis.md](sidecar-vs-cleanroom-analysis.md), Sections 1–4)*

---

<a id="3-industry-validation"></a>

## 3. Industry Validation

The strategies proposed in this project's existing documentation align with
industry best practices. The following table maps each proposed mechanism to
its real-world precedent.

<table>
<colgroup>
<col style="width:20%">
<col style="width:22%">
<col style="width:58%">
</colgroup>
<tr>
  <th>Mechanism</th>
  <th>Industry Precedent</th>
  <th>Evidence</th>
</tr>
<tr>
  <td><code>CC=</code> wrapper for C/C++</td>
  <td>ccache, distcc, scan-build (Clang), Coverity</td>
  <td>ccache 4.0+ uses the same <code>CC=</code> interposition pattern for build caching [1]. distcc uses it for distributed compilation [2]. Clang's <code>scan-build</code> wraps <code>CC=</code> for static analysis [3].</td>
</tr>
<tr>
  <td>Go <code>-toolexec</code> wrapper</td>
  <td>DataDog Orchestrion</td>
  <td>Orchestrion uses <code>-toolexec</code> for compile-time Go instrumentation at production scale. Go issue #69887 documents their challenges and the Go team's response [4].</td>
</tr>
<tr>
  <td><code>RUSTC_WRAPPER</code> for Rust</td>
  <td>sccache, mold linker</td>
  <td>sccache uses <code>RUSTC_WRAPPER</code> for build caching [5]. It is a stable, documented Cargo feature [6].</td>
</tr>
<tr>
  <td><code>strace --seccomp-bpf</code> for Java</td>
  <td>strace project (Paul Chaignon)</td>
  <td>Paul Chaignon (strace maintainer) introduced <code>--seccomp-bpf</code> in strace 5.3, demonstrating ~97% overhead reduction on syscall-heavy workloads such as Linux kernel builds [7]. Overhead reduction varies by workload — Java/Maven builds make fewer syscalls, so the reduction is smaller. OmniBOR's Java pipeline already uses <code>--seccomp-bpf</code>; the remaining 5–17% overhead is <em>after</em> this optimization.</td>
</tr>
<tr>
  <td>Pre-hash cache (inode-based)</td>
  <td>ccache inode cache, Bazel CAS, Buck2</td>
  <td>ccache 4.0+ implemented inode-based caching to avoid re-hashing popular headers [1]. Bazel and Buck2 use content-addressable stores [9].</td>
</tr>
<tr>
  <td>seccomp-bpf syscall filtering</td>
  <td>Docker, Chromium, Firefox, Android</td>
  <td>seccomp-bpf is used universally for process sandboxing. Docker applies seccomp profiles to all containers. Chromium and Firefox sandbox renderer processes. Android mandates it since 8.0 [10].</td>
</tr>
<tr>
  <td>eBPF for build tracing</td>
  <td>No production precedent</td>
  <td>No major SBOM or build tool uses eBPF for compiler interception as of 2026. eBPF ecosystem focuses on networking, security, and observability [8].</td>
</tr>
</table>

### Go `-toolexec` Evolution

Go issue [#69887](https://github.com/golang/go/issues/69887) (opened Oct
2024) documents DataDog's experience building Orchestrion, a compile-time
instrumentation tool that uses `-toolexec`. Key challenges relevant to
OmniBOR's Go wrapper:

1. **Adding dependency edges** — Orchestrion modifies `importcfg` files
   to register new dependencies. For OmniBOR's read-only interception,
   this is not needed (we observe, not modify).

2. **Parsing tool arguments** — "there is no programmatic way to get these
   in a structured way. We have to resort to parsing the help output of
   these commands." This matches OmniBOR's `bomsh_hook2.py` experience
   with `get_all_subfiles_in_golang_compile_cmdline()`.

3. **Build caching** — Go issue [#41145](https://github.com/golang/go/issues/41145)
   proposes allowing `-toolexec` tools to opt in to build caching. This
   would solve the `-a` flag problem permanently but is not yet implemented.

*(Source: [4], [11])*

---

<a id="4-per-language-sidecar-strategy"></a>

## 4. Per-Language Sidecar Strategy

<a id="41-java-strace-openat--maven-deptree"></a>

### 4.1 Java — strace `openat` / Maven `dep:tree`

| | |
|---|---|
| **Mechanism** | `strace --seccomp-bpf -e trace=openat mvn package` |
| **Sidecar ready** | **Yes — already is** |
| **Current overhead** | 5–17% |
| **Expected overhead** | <2% (with Maven dep:tree optimization) |

#### Current State

Java is already the closest to true sidecar mode. The strace wrapper captures
`openat` events while Maven runs with whatever JDK is natively installed. The
overhead is already the lowest of all languages.

*(Source: [cross-language-build-timing-improvements.md](cross-language-build-timing-improvements.md), Section 3)*

#### Pros

- Already wraps the native `mvn`/`gradle` — true sidecar from day one
- Already uses `seccomp-bpf` (the optimization proposed for C/C++ is
  already implemented for Java)
- Post-build hashing pattern is already the Java default
- Lowest overhead of all languages

#### Cons

- Still requires `SYS_PTRACE` for strace
- Gradle's `--daemon` mode conflicts with clean strace capture — must
  use `--no-daemon`, altering native build behavior
- The strace log is collected but was historically not consumed by the
  post-build script (this gap is documented as resolved in
  [cross-language-build-timing-improvements.md](cross-language-build-timing-improvements.md),
  Section 3)

#### Highest-Impact Optimization: Replace strace with Maven `dep:tree`

The single most impactful Java-specific improvement is **replacing strace
with Maven's own dependency metadata**:

```bash
mvn dependency:tree -DoutputType=dot -DoutputFile=deps.dot
```

This provides the declared dependency graph without any tracing overhead.

**Accuracy caveat:** `dependency:tree` reflects Maven's dependency mediation
rules, which may differ from what's actually compiled if Maven profiles,
shade/assembly plugins, or optional dependencies are in play. For exact
results, the CycloneDX Maven Plugin runs *during* the build as a lifecycle
participant. OmniBOR should validate `dependency:tree` output against strace
logs when both are available, and document known discrepancies.
Combined with `bomsh_create_bom_java.py` for source-to-class mapping, this
reduces overhead from 5–17% to **<2%** and — critically — **eliminates the
`SYS_PTRACE` requirement for Java entirely**.

This approach is aligned with the industry-standard pattern used by the
[CycloneDX Maven Plugin](https://github.com/CycloneDX/cyclonedx-maven-plugin),
which generates CycloneDX SBOMs from Maven dependency metadata without build
tracing [13].

#### Recommendation

1. Implement Maven `dep:tree` as the primary Java dependency resolution
   mechanism
2. Keep strace as an optional supplementary data source for file-level
   provenance evidence
3. This removes `SYS_PTRACE` as a requirement for Java sidecar deployments

---

<a id="42-cc-cc-wrapper"></a>

### 4.2 C/C++ — `CC=` Wrapper

| | |
|---|---|
| **Mechanism** | `CC=/opt/bomsh/gcc-wrapper CXX=/opt/bomsh/g++-wrapper make -j$(nproc)` |
| **Sidecar ready** | **Yes** |
| **Current overhead** | 20–60% (ptrace via bomtrace3) |
| **Expected overhead** | 5–15% (wrapper — depends on binary size and I/O; benchmarks pending) |

#### How it works

Each wrapper script:

1. Records `argv` (the full command line)
2. Invokes the **real compiler**: `exec /usr/bin/gcc "$@"` — whatever is on PATH
3. After the compiler exits: hashes the output file
4. Writes a raw logfile record
5. For `.h` dependencies: reads the `-MD` dependency output

The wrapper does not care what gcc version it calls. It does not need ptrace.
It interposes on the compiler invocation and calls through to whatever the
native toolchain is.

*(Source: [omnibor-performance-optimization-proposal.md](omnibor-performance-optimization-proposal.md), Strategy 5; [sidecar-vs-cleanroom-analysis.md](sidecar-vs-cleanroom-analysis.md), Section 5)*

#### Pros

- **Industry-standard pattern** — ccache [1], distcc [2], scan-build [3],
  and Coverity all use this exact mechanism
- **Natural parallelism** — each wrapper runs in its own process; `make -j16`
  means 16 wrappers run in parallel with no single-threaded bottleneck
- **Build system compatibility** — works with make, cmake, autoconf, Ninja,
  Meson out of the box; all respect `CC=`/`CXX=` environment variables
- **True sidecar** — wrapper calls whatever `gcc`/`clang` is on PATH
- **No kernel capabilities** — no `SYS_PTRACE`, no `seccomp:unconfined`
- **Architecture-independent** — works on x86_64, ARM64, or any architecture

#### Cons

- Build system must respect `CC=`/`CXX=`/`AR=`/`LD=` (rare exceptions:
  hard-coded compiler paths in some Makefiles)
- Must wrap **all** tools to avoid SBOM gaps: `gcc`, `g++`, `ar`, `ld`,
  `as`, `ranlib`, `strip`
- Does not capture dynamic library linkage at runtime (still need
  `readelf -d` post-build)

#### Recommendation

The full wrapper set (`gcc-wrapper`, `g++-wrapper`, `ar-wrapper`,
`ld-wrapper`, `as-wrapper`, `ranlib-wrapper`) is defined in
[sidecar-implementation-design.md](sidecar-implementation-design.md),
Section 6.2. All wrappers are written in C for minimal startup overhead.

---

<a id="43-go-toolexec-wrapper"></a>

### 4.3 Go — `-toolexec` Wrapper

| | |
|---|---|
| **Mechanism** | `go build -toolexec=/opt/bomsh/bomsh_go_wrapper -o binary .` |
| **Sidecar ready** | **Yes, with caveats** |
| **Current overhead** | 150–400% (bomtrace2 + Python hook + `-a`) |
| **Expected overhead** | 10–15% overhead **vs. a full rebuild** (wrapper cost only). Total overhead **vs. a cached build** is 100–215% due to the `-a` flag forcing full recompilation. See the three-phase mitigation below. |

#### How it works

Go's stable `-toolexec` flag allows a custom program to wrap every `compile`
and `link` invocation. The wrapper receives the full tool command line as
arguments, records inputs/outputs, executes the real tool, and hashes the
results.

```bash
# Current (ptrace-based):
bomtrace2 -c /opt/bomsh/bomtrace_go.conf go build -a -o binary .

# Proposed (wrapper-based):
go build -a -toolexec="/opt/bomsh/bomsh_go_wrapper" -o binary .
```

*(Source: [cross-language-build-timing-improvements.md](cross-language-build-timing-improvements.md), Section 4; Go documentation [12])*

#### Pros

- **Officially supported**, stable Go mechanism
- **Production-proven** — DataDog's Orchestrion uses `-toolexec` for
  compile-time Go instrumentation at scale [4]
- **Eliminates ptrace** entirely — no `SYS_PTRACE` needed
- Wrapper receives full `compile` and `link` command lines — all inputs
  discoverable from arguments
- Per-invocation cost drops from ~50ms (Python startup) to ~2–5ms
  (compiled wrapper)

#### Cons

- **The `-a` problem is the primary blocker.** Without `-a`, Go's build
  cache serves cached results and the wrapper never sees cached packages.
  With `-a`, every build is forced full — adding 100–200% overhead on
  top of a normal cached build.
- **Go issue [#41145](https://github.com/golang/go/issues/41145)** proposes
  allowing `-toolexec` tools to opt in to build caching. This would solve
  the `-a` problem permanently, but it is not yet implemented (open since
  2020) [11].
- **DataDog's Orchestrion required a custom job server** to avoid redundant
  dependency resolution — complexity is higher than for Rust/C/C++ [4].
- `-toolexec` provides no events for packages served from cache — there is
  no way to inspect cached packages without `-a`.

#### The `-a` Problem: Three-Phase Solution

| Phase | Approach | Overhead vs. Cached Build | Complexity |
|-------|----------|--------------------------|------------|
| **Short-term** | `-toolexec` + `-a` (full rebuild every time) | ~100–200% | Low |
| **Medium-term** | Read `go.sum` + `$GOPATH/pkg/mod/cache/` for third-party modules; `-a` only for first-party | ~30–50% | Medium |
| **Long-term** | Go issue #41145 — `-toolexec` cache integration | ~10–15% | Depends on upstream |

For the medium-term phase: Go modules in `$GOPATH/pkg/mod/` are immutable
once downloaded. Their checksums are in `go.sum`. The SBOM for third-party
modules can be derived from this metadata without tracing. Only first-party
packages (the repository being built) need live tracing.

#### Recommendation

The `-toolexec` wrapper is written in **Go** (not Python) to avoid ~50ms
startup overhead per invocation. The `bomsh_hook2.py` parsing functions
are ported to Go natively. The three-phase mitigation for `-a` overhead
is detailed in
[sidecar-implementation-design.md](sidecar-implementation-design.md),
Section 7.3:

1. **Phase A:** Accept `-a` penalty (~100–200% — still a major
   improvement over bomtrace2's 150–400%)
2. **Phase B:** Derive third-party module info from `go.sum` to skip
   tracing them
3. **Phase C:** Monitor Go issue [#41145](https://github.com/golang/go/issues/41145)
   for `-toolexec` cache integration

---

<a id="44-rust-rustc_wrapper"></a>

### 4.4 Rust — `RUSTC_WRAPPER`

| | |
|---|---|
| **Mechanism** | `RUSTC_WRAPPER=/opt/bomsh/bomsh_rustc_wrapper cargo build --release` |
| **Sidecar ready** | **Yes — cleanest of all languages** |
| **Current overhead** | 100–250% (bomtrace2 + Python hook) |
| **Expected overhead** | 5–10% |

#### How it works

Cargo's stable `RUSTC_WRAPPER` environment variable allows a custom program
to wrap every `rustc` invocation. Cargo calls
`$RUSTC_WRAPPER rustc <args>` for every compilation unit. The wrapper records
args, calls the real rustc, then hashes outputs.

```bash
# Current (ptrace-based):
bomtrace2 cargo build --release

# Proposed (wrapper-based):
RUSTC_WRAPPER=/opt/bomsh/bomsh_rustc_wrapper cargo build --release
```

*(Source: [cross-language-build-timing-improvements.md](cross-language-build-timing-improvements.md), Section 5; Cargo documentation [6])*

#### Pros

- **Officially supported**, stable Cargo mechanism (used by sccache [5],
  mold linker)
- Cargo resolves the real `rustc` path and passes it as the first argument —
  sidecar works automatically regardless of rustc install location
- **Minimal cache problem** — Rust's build cache DOES exist for release
  builds (unchanged crates are not recompiled), but `Cargo.lock` provides
  complete dependency metadata (names, versions, checksums) for all crates.
  The SBOM for third-party crates can be derived from `Cargo.lock` without
  tracing, so the wrapper is only needed for first-party code hashing.
  Incremental compilation is disabled in release mode, but the crate-level
  cache is active.
- `Cargo.lock` provides exact checksums for all third-party crates — SBOM
  can be derived without tracing them
- Cleanest overhead profile of all compiled languages

#### Cons

- `RUSTC_WRAPPER` wraps `rustc` only — it does not see `build.rs` (build
  scripts) or proc-macro crate compilation directly. These are compiled
  separately and their outputs feed into downstream `rustc` invocations.
  The wrapper still sees the *results* but not the build script execution.
- For proc-macro crates, `RUSTC_WRAPPER` is invoked on the host architecture,
  not the target. Correct behavior, but needs awareness in cross-compilation.

#### Recommendation

The `rustc-wrapper` is written in **Rust** for minimal startup overhead.
The implementation uses a two-tier approach defined in
[sidecar-implementation-design.md](sidecar-implementation-design.md),
Section 8:

1. **`RUSTC_WRAPPER`** — wraps all crate compilations (initial approach)
2. **`RUSTC_WORKSPACE_WRAPPER`** — wraps only workspace crates, derives
   third-party info from `Cargo.lock` checksums. Avoids wrapping ~85% of
   crate compilations. See Section 8.3 for `RustcWorkspaceWrapperStrategy`.

Rust uses a build cache (`target/` directory). `Cargo.lock` provides
complete dependency metadata even for cached crates, so the SBOM is
complete from metadata. See Section 8.5 for details.

*(Source: [Cargo documentation — environment variables](https://doc.rust-lang.org/cargo/reference/environment-variables.html) [6])*

---

<a id="45-python-pip-metadata"></a>

### 4.5 Python — pip Metadata

| | |
|---|---|
| **Mechanism** | `pip freeze` + `pipdeptree --json` |
| **Sidecar ready** | **N/A — no build tracing needed** |
| **Current overhead** | N/A (not yet supported) |
| **Expected overhead** | Zero build overhead (SBOM generation itself takes 5–30s depending on package count) |

Python's package metadata is fully declarative. The SBOM can be derived from
`pip freeze`, `pip show`, or the `importlib.metadata` API with **zero impact
on build time**. No tracing, no ptrace, no strace. The SBOM generation step
runs post-install and has its own runtime cost, but does not affect the
`pip install` performance.

*(Source: [cross-language-build-timing-improvements.md](cross-language-build-timing-improvements.md), Section 6; [python-omnibor-support-analysis.md](python-omnibor-support-analysis.md))*

#### Recommendation

No changes needed. Start with pip metadata when Python support begins.
Add strace-based `pip install` tracing or import hooks only if
runtime-discovered dependencies need to be captured.

---

<a id="5-cross-cutting-recommendations"></a>

## 5. Cross-Cutting Recommendations

<a id="51-wrapper-language-choice"></a>

### 5.1 Wrapper Language Choice

Each wrapper should be written in the language it instruments to minimize
startup overhead and maximize ecosystem integration.

| Wrapper | Language | Rationale |
|---------|----------|-----------|
| C/C++ wrapper | **C** or **Go** | Minimal startup, can link against OpenSSL for SHA256; Go provides easier cross-compilation |
| Go wrapper | **Go** | Native `-toolexec` integration, no startup penalty, same build system |
| Rust wrapper | **Rust** | Native `RUSTC_WRAPPER` integration, zero-cost abstractions |
| Java (if needed) | **Java** | Maven plugin or Gradle task; runs inside the build JVM |

Each wrapper ports `bomsh_hook2.py` argument parsing to its native
language (not via subprocess). This eliminates the ~50ms Python startup
per invocation that dominates non-ptrace overhead.

*(Source: [cross-language-build-timing-improvements.md](cross-language-build-timing-improvements.md), Sections 4 and 5 — overhead breakdown showing Python startup at 15–35% of total)*

<a id="52-dual-mode-container-image"></a>

### 5.2 Dual-Mode Container Image

The container should offer two modes as distinct image variants:

| Mode | Contents | Use Case | Owned By |
|------|----------|----------|----------|
| **Sidecar** (new) | Interception tools + analysis pipeline only (no compilers) | Enterprise CI/CD integration | Published to containers.cisco.com |
| **Standalone (default)** | Interception tools + reference toolchains + analysis pipeline | Open-source analysis, demos, evaluation | Published to containers.cisco.com |
| **Standalone (custom)** | Team extends base image with their specific toolchains via `FROM` | Teams requiring standalone mode with their own build environment | Team-owned and team-maintained |

**Why three models:** The default standalone image bundles fixed toolchain
versions (e.g., gcc 12.2, JDK 17, Go 1.21). If a team uses different
versions, the SBOM reflects the container's toolchains — not theirs.
Teams that require standalone mode due to environment constraints extend
the published image via `FROM omnibor-env:standalone` in their own
Dockerfile, adding their specific toolchains. This ensures SBOM accuracy
in all deployment models.

**Standalone (custom) — extend, don't fork.** Teams MUST use Docker
`FROM` inheritance (extending the published base image), NOT fork the
omnibor-analysis repository. This follows the industry-standard pattern
used by every major enterprise container platform:

- **`FROM` inheritance** — team gets automatic security patches and
  pipeline updates when we publish a new base image tag. Team's
  Dockerfile is 5–20 lines (just toolchain additions).
- **Repo forking** (anti-pattern) — creates drift, merge conflicts on
  every upstream update, duplicated CI/CD, and security patch lag.
  Forks diverge within weeks and become unmaintainable.

The team's custom Dockerfile should live in their own repo (or a
dedicated `omnibor-custom/` directory), not in the omnibor-analysis repo.

Implementation: multi-stage Dockerfile where the sidecar image is a strict
subset of the standalone image with build toolchains removed. The standalone
base image is designed to be extensible via `FROM omnibor-env:standalone`.

```dockerfile
# Stage 1: Full standalone (current)
FROM ubuntu:22.04 AS standalone
# ... install everything (gcc, go, rust, java, bomtrace3, bomsh, pipeline)

# Stage 2: Sidecar (new)
FROM ubuntu:22.04 AS sidecar
COPY --from=standalone /opt/bomsh/ /opt/bomsh/
COPY --from=standalone /workspace/app/ /workspace/app/
# Interception tools + analysis pipeline only
# No gcc, go, rust, java
```

*(Source: [enterprise-integration-guide.md](../guides/enterprise-integration-guide.md), Section 6 — Integration Architecture)*

<a id="53-arm64-support-via-wrappers"></a>

### 5.3 ARM64 Support via Wrappers

`platform-support.md` documents that bomtrace3 is x86_64-only due to
register access in `<sys/reg.h>`. **The wrapper-based sidecar architecture
makes ARM64 support significantly easier** — documented in
[sidecar-implementation-design.md](sidecar-implementation-design.md),
Section 14.2 (Platform Scope) and Phase 4 (ARM64 validation on Graviton).

| Mechanism | Architecture Dependency | ARM64 Ready? |
|-----------|----------------------|-------------|
| bomtrace3 (ptrace) | x86_64 register layout (`ORIG_RAX`, `RDI`, etc.) | **No** — requires porting |
| `CC=` wrapper | None — calls compiler, hashes output | **Yes** |
| `-toolexec` wrapper | None — Go wrapper runs on build host arch | **Yes** |
| `RUSTC_WRAPPER` | None — Rust wrapper runs on build host arch | **Yes** |
| strace for Java | x86_64 ptrace (same as bomtrace3) | **No** — but Maven dep:tree has no arch dependency |

By implementing wrappers for C/C++, Go, and Rust, and Maven `dep:tree` for
Java, the sidecar mode would work on **ARM64 without any bomtrace3 porting
work**. This unlocks:

- **AWS Graviton** instances (30–40% better price-performance than x86_64
  for compute workloads)
- **Apple Silicon** (M1–M5) for local development
- **ARM64 CI runners** (GitHub Actions, GitLab CI)

*(Source: [platform-support.md](../architecture/platform-support.md), Sections on Architecture Constraint and Future ARM64 Support; AWS Graviton pricing documentation [15])*

<a id="54-ebpf-deprioritize"></a>

### 5.4 eBPF — Deprioritize

Earlier analysis positioned eBPF (Strategy 6) as the "most
transparent" option and the "cleanest long-term path for Go." After industry
research, eBPF is deprioritized to a future extensibility point (see
[sidecar-implementation-design.md](sidecar-implementation-design.md),
Section 13.2):

| Factor | Assessment |
|--------|-----------|
| **Production precedent** | No major SBOM or build tool uses eBPF for compiler interception [8] |
| **Portability** | Linux 5.x+ only — not portable to Windows, macOS, or older Linux [14] |
| **Complexity** | BPF verifier constraints, limited stack space (512 bytes), argv parsing must happen in userspace [8] |
| **Go coverage** | `-toolexec` covers Go better than eBPF; eBPF does not solve the `-a` problem |
| **Language-native wrappers** | `CC=`, `-toolexec`, `RUSTC_WRAPPER` provide better per-language coverage with lower complexity |

eBPF would only be justified if:

1. Go never gets `-toolexec` cache integration (Go issue [#41145](https://github.com/golang/go/issues/41145))
2. A language emerges with no compiler wrapper mechanism
3. Truly zero-modification interception is required (no `CC=`, no `-toolexec`)

**Recommendation:** Reclassify eBPF as a **research track**, not a priority
implementation item. The language-native wrapper approach (items 1–3 in
[Section 6](#6-priority-ordered-action-items)) delivers sidecar mode for all
four compiled languages with proven, lower-complexity mechanisms.

*(Source: [cross-platform-applicability.md](cross-platform-applicability.md), Sections 3 and 7; eBPF ecosystem documentation [8])*

---

<a id="6-priority-ordered-action-items"></a>

## 6. Priority-Ordered Action Items

### Ordering Rationale

**Java is the first pilot language** with engineering teams. C/C++ is
the second. This reverses the previous overhead-reduction ordering
because enterprise adoption depends on having production-ready sidecar
support for the languages engineering teams are actually using — not
the languages with the largest theoretical overhead improvement.

Java is already sidecar-compatible for build interception (strace wraps
whatever JDK is on PATH). However, deploying to enterprise teams reveals
infrastructure gaps that must be closed first:

1. **Package resolver abstraction** — enterprise teams run RHEL, not
   Ubuntu. Without `rpm -qf` support, `metadata_collector.py` and
   `resolver.py` cannot resolve system library metadata on RHEL/CentOS.
   This blocks meaningful SBOMs for both Java and C/C++ on enterprise
   distros.

2. **Config mode selection + CommandRunner env support** — the pipeline
   must support `--mode sidecar` to select wrapper-based interception
   and pass environment variables (`CC=`, `RUSTC_WRAPPER`) to builds.
   Required for C/C++ sidecar, and the config infrastructure benefits
   all languages.

3. **Dual-mode Docker image** — engineering teams need a delivery
   mechanism. The sidecar image (interception tools + analysis pipeline,
   no compilers) is how teams install OmniBOR alongside their existing
   build environment. This is a **prerequisite for any enterprise
   deployment**, not a nice-to-have.

### Dependency Graph

<a href="sidecar-dependency-graph.png"><img src="sidecar-dependency-graph.png" width="600" alt="Sidecar Priority Dependency Graph — click to enlarge"></a>

*Click image to enlarge. Source: [sidecar-dependency-graph.drawio](sidecar-dependency-graph.drawio)*

### Priority-Ordered Action Items

<table>
<tr>
  <th style="width:3%">#</th>
  <th style="width:22%">Action</th>
  <th style="width:8%">Languages</th>
  <th style="width:9%">Predecessors</th>
  <th style="width:14%">Impact</th>
  <th style="width:7%">Effort</th>
  <th style="width:37%">Rationale</th>
</tr>
<tr>
  <td>1</td>
  <td><strong>Package resolver abstraction</strong> — <code>dpkg</code>, <code>rpm</code>, <code>apk</code> behind a common interface; auto-detect distro at runtime</td>
  <td>Java, C/C++, all</td>
  <td>None</td>
  <td><strong>Blocks enterprise deployment</strong> on RHEL/CentOS</td>
  <td>1–2 weeks</td>
  <td>Enterprise teams run RHEL, not Ubuntu. Without this, <code>metadata_collector.py</code> calls <code>dpkg-query</code> which does not exist on RHEL. PURLs hardcode <code>pkg:deb/ubuntu/</code>. This is the #1 enterprise blocker.</td>
</tr>
<tr>
  <td>2</td>
  <td><strong>Java Maven <code>dep:tree</code></strong> to replace strace for dependency graph</td>
  <td>Java</td>
  <td>#1 (RHEL metadata)</td>
  <td>5–17% → &lt;2% overhead; <strong>removes <code>SYS_PTRACE</code></strong></td>
  <td>1–2 weeks</td>
  <td>Java is the first pilot language. It already works in sidecar mode via strace, but enterprise security teams restrict <code>SYS_PTRACE</code>. Replacing strace with Maven's own dependency metadata eliminates this blocker. Aligns with CycloneDX Maven Plugin pattern.</td>
</tr>
<tr>
  <td>3</td>
  <td><strong>Config mode selection + CommandRunner env support</strong> — <code>config.yaml</code> gains <code>mode: sidecar</code>; <code>CommandRunner.run()</code> gains <code>env</code> parameter</td>
  <td>All</td>
  <td>None</td>
  <td>Enables all wrapper-based strategies</td>
  <td>1 week</td>
  <td>Infrastructure prerequisite for C/C++, Rust, and Go sidecar mode. Without <code>env</code> support, wrapper paths (<code>CC=</code>, <code>RUSTC_WRAPPER</code>) must be embedded in command strings. Without mode selection, the pipeline cannot choose between ptrace and wrapper strategies.</td>
</tr>
<tr>
  <td>4</td>
  <td><strong>Dual-mode Docker image</strong> (standalone + sidecar) — multi-stage Dockerfile producing two image variants</td>
  <td>All</td>
  <td>None</td>
  <td><strong>Enterprise delivery mechanism</strong></td>
  <td>1 week</td>
  <td>Engineering teams need a way to install OmniBOR tools alongside their existing toolchain. The sidecar image contains interception tools + analysis pipeline but no compilers. Without this, there is no deployment path for pilot teams.</td>
</tr>
<tr>
  <td>5</td>
  <td><strong>C/C++ <code>CC=</code> wrappers</strong> (written in C/Go); add <code>as-wrapper</code> and <code>ranlib-wrapper</code></td>
  <td>C/C++</td>
  <td>#3 (config + env), #4 (delivery)</td>
  <td>20–60% → 3–5% overhead; eliminates <code>SYS_PTRACE</code></td>
  <td>2–3 weeks</td>
  <td>C/C++ is the second pilot language. Wrappers are upstream bomsh deliverables. The omnibor-analysis strategy integration (~3 days) depends on the config infrastructure from #3 and the wrappers being available from upstream.</td>
</tr>
<tr>
  <td>6</td>
  <td><strong>Go <code>-toolexec</code> wrapper</strong> (written in Go)</td>
  <td>Go</td>
  <td>#3 (config + env)</td>
  <td>150–400% → 10–15% overhead</td>
  <td>2–3 weeks</td>
  <td>Single biggest overhead improvement across all languages. Deprioritized vs. previous plan because Go is not in the initial enterprise pilot. Can proceed in parallel with #5 since the upstream wrapper work is independent.</td>
</tr>
<tr>
  <td>7</td>
  <td><strong>Rust <code>RUSTC_WRAPPER</code></strong> (written in Rust); use <code>RUSTC_WORKSPACE_WRAPPER</code> for workspace crates</td>
  <td>Rust</td>
  <td>#3 (config + env)</td>
  <td>100–250% → 5–10% overhead</td>
  <td>2 weeks</td>
  <td>Cleanest sidecar implementation (no <code>-a</code> problem). Deprioritized because Rust is not in the initial pilot. Lowest upstream effort — single wrapper binary.</td>
</tr>
<tr>
  <td>8</td>
  <td><strong>Go cache integration</strong> (read <code>go.sum</code> for third-party modules)</td>
  <td>Go</td>
  <td>#6 (Go wrapper)</td>
  <td>Eliminates <code>-a</code> for third-party packages</td>
  <td>2–3 weeks</td>
  <td>Phase B optimization. Third-party Go modules are immutable and checksummed in <code>go.sum</code> — perfect SBOM cache targets. Contingent on Go wrapper (#6) being complete.</td>
</tr>
<tr>
  <td>9</td>
  <td><strong>ARM64 validation</strong> via wrappers (no bomtrace3 porting)</td>
  <td>C/C++, Go, Rust</td>
  <td>#5, #6, #7</td>
  <td>Unlocks Graviton + Apple Silicon</td>
  <td>1 week</td>
  <td>Quick win once wrappers exist: wrappers have no architecture dependency. Cannot proceed until at least one language's wrapper is available.</td>
</tr>
<tr>
  <td>10</td>
  <td><strong>eBPF research track</strong></td>
  <td>All (future)</td>
  <td>None</td>
  <td>Ultimate transparency for edge cases</td>
  <td>Ongoing</td>
  <td>Deprioritized — language-native wrappers cover all current needs</td>
</tr>
</table>

### Fast-Track for Java Pilot (Weeks 1–4)

Items #1, #2, and #4 can proceed **in parallel** since they have no
dependencies on each other. This means the Java pilot can be fully
operational in ~4 weeks:

| Week | Parallel Track A | Parallel Track B | Parallel Track C |
|------|-----------------|-----------------|-----------------|
| 1–2 | Package resolver (#1) | Java Maven dep:tree (#2) | Config + CommandRunner (#3) |
| 3 | RPM/Alpine testing | Integration tests | Dual-mode Docker (#4) |
| 4 | **Java pilot on RHEL: ready** | | C/C++ wrappers begin (#5) |

After week 4, Java sidecar mode is production-ready on RHEL with no
`SYS_PTRACE` requirement. C/C++ follows 2–3 weeks later once upstream
wrappers are available.

---

<a id="7-bibliography"></a>

## 7. Bibliography

### Project Documentation (Internal)

- [sidecar-vs-cleanroom-analysis.md](sidecar-vs-cleanroom-analysis.md) — Core architecture discussion, per-language sidecar feasibility
- [omnibor-performance-optimization-proposal.md](omnibor-performance-optimization-proposal.md) — Strategies 1–6, overhead budget, implementation roadmap
- [cross-language-build-timing-improvements.md](cross-language-build-timing-improvements.md) — Per-language optimization analysis (Java, Go, Rust, Python)
- [cross-platform-applicability.md](cross-platform-applicability.md) — Cross-platform viability of each strategy
- [platform-support.md](../architecture/platform-support.md) — Architecture constraints, ARM64 limitations
- [enterprise-integration-guide.md](../guides/enterprise-integration-guide.md) — Enterprise gap analysis, turnkey packaging, CI/CD integration patterns

### External References

[1] **ccache manual — inode cache and compiler wrapping:**
https://ccache.dev/manual/latest.html

[2] **distcc — distributed C/C++ compilation:**
https://distcc.github.io/

[3] **Clang scan-build — CC= based static analysis wrapper:**
https://clang-analyzer.llvm.org/scan-build.html

[4] **DataDog Orchestrion — Go `-toolexec` instrumentation at scale; Go issue #69887:**
https://github.com/golang/go/issues/69887
https://github.com/DataDog/orchestrion

[5] **sccache — shared compilation cache using `RUSTC_WRAPPER`:**
https://github.com/mozilla/sccache

[6] **Cargo documentation — `RUSTC_WRAPPER` and `RUSTC_WORKSPACE_WRAPPER` environment variables:**
https://doc.rust-lang.org/cargo/reference/environment-variables.html

[7] **Paul Chaignon, "Introducing strace --seccomp-bpf" (2019) — measured ~97% overhead reduction on Linux kernel build:**
https://pchaigno.github.io/strace/2019/10/02/introducing-strace-seccomp-bpf.html

[8] **eBPF ecosystem documentation and application landscape:**
https://ebpf.io/
https://ebpf.io/applications/
https://eunomia.dev/blog/2025/02/12/ebpf-ecosystem-progress-in-20242025-a-technical-deep-dive/

[9] **Bazel content-addressable store and remote caching:**
https://bazel.build/remote/caching

[10] **Linux kernel seccomp-bpf documentation:**
https://docs.kernel.org/userspace-api/seccomp_filter.html

[11] **Go issue #41145 — allow `-toolexec` tools to opt in to build caching:**
https://github.com/golang/go/issues/41145

[12] **Go `-toolexec` documentation:**
https://pkg.go.dev/cmd/go#hdr-Compile_packages_and_dependencies

[13] **CycloneDX Maven Plugin — industry-standard Maven SBOM generation from dependency metadata:**
https://github.com/CycloneDX/cyclonedx-maven-plugin

[14] **Cross-platform eBPF limitations (eBPF for Windows — networking only, no tracepoints):**
https://github.com/microsoft/ebpf-for-windows

[15] **AWS Graviton processor — ARM64 compute instances:**
https://aws.amazon.com/ec2/graviton/

[16] **Go `-toolexec` flag specification:**
https://pkg.go.dev/cmd/go#hdr-Build_and_test_caching

[17] **OpenSSL EVP_sha256 — cross-platform hardware-accelerated SHA256:**
https://www.openssl.org/docs/man3.0/man3/EVP_sha256.html

[18] **OpenSSL ARM capability detection (armcap.c) — Apple M1–M5 detection:**
https://github.com/openssl/openssl/blob/master/crypto/armcap.c

---

---

<a id="8-appendix-a-source-code-audit--current-vs-sidecar"></a>

## 8. Appendix A: Source Code Audit — Current vs. Sidecar

This appendix maps every pipeline module to its sidecar impact based on
a line-by-line review of the source code. Files are referenced by their
path under the repository root.

### A.1 Pipeline Orchestration Layer

#### `app/pipeline/facade.py` — AnalysisPipeline

The facade composes all pipeline steps. It is **language-agnostic** — it
delegates to the appropriate builder method and SPDX generator based on
the `language` field in `config.yaml`.

**Sidecar impact: None.** The facade does not reference toolchains,
container paths, or architecture-specific logic. It passes through
whatever `config.yaml` provides.

#### `app/pipeline/runners.py` — CLI entry point / main()

The `lang_omnibor_keys` dict (lines 81–86) maps language names to
config sections:

```python
lang_omnibor_keys = {
    "c-cpp": "omnibor",
    "rust": "omnibor_rust",
    "java": "omnibor_java",
    "go": "omnibor_go",
}
```

**Sidecar impact: Extend the dict** to include a `"python": "omnibor_python"`
entry when Python support is added. No other changes needed — the runner
already dispatches to `lang_runners.py` per language.

#### `app/pipeline/lang_runners.py` — Per-language pipeline functions

Four runner functions exist today:

| Function | Lines | Tracer Used | Sidecar Change |
|----------|-------|-------------|----------------|
| `run_c_cpp_pipeline()` | 20–89 | `BomtraceBuilder.build()` → bomtrace3 | Replace with `CC=` wrapper build |
| `run_rust_pipeline()` | 96–160 | `BomtraceBuilder.build()` → bomtrace2 | Replace with `RUSTC_WRAPPER` build |
| `run_go_pipeline()` | 394–460 | `BomtraceBuilder.build()` → bomtrace2 + `bomtrace_go.conf` | Replace with `-toolexec` build |
| `run_java_pipeline()` | 167–231 | `BomtraceBuilder.build_java()` → strace | **Already sidecar-ready** — strace wraps native `mvn`/`gradle` |

**Key observation:** All four runners call the same `pipeline.builder.build()`
or `pipeline.builder.build_java()` method. The builder constructs the
instrumented command by prefixing the build step with the tracer:

```python
# builder.py line 82
instrumented = f"{tracer} {make_cmd}"
```

For sidecar mode, **only `config.yaml` needs to change** if we keep the
same prefix-based approach. The `tracer` field would become the wrapper
invocation instead of `bomtrace3`:

```yaml
# Current (clean-room):
omnibor:
  tracer: bomtrace3
# Sidecar (proposed):
omnibor:
  tracer: ""  # Empty — CC= env var wraps instead
```

However, for Go `-toolexec` and Rust `RUSTC_WRAPPER`, the wrapper is
specified as **an environment variable**, not a command prefix. This
means `BomtraceBuilder.build()` cannot handle sidecar mode for Go
and Rust with its current design — it only supports prefixing.

**Required change for Go/Rust sidecar:**

Option A: Add `env_vars` support to `build()`:

```python
def build(self, ..., env_vars=None):
    env = env_vars or {}
    instrumented = f"{tracer} {make_cmd}" if tracer else make_cmd
    self.runner.run(instrumented, env=env, ...)
```

Option B: Embed the env vars in `build_steps` in config.yaml:

```yaml
# Go sidecar:
build_steps:
  - 'go build -a -toolexec=/opt/bomsh/bomsh_go_wrapper -trimpath -ldflags="-s -w" -o binary .'
# Rust sidecar:
build_steps:
  - 'RUSTC_WRAPPER=/opt/bomsh/bomsh_rustc_wrapper cargo build --release'
```

Option B is simpler and requires **zero code changes** — the wrapper
invocation moves into the build step string. However, Option A is
cleaner architecturally (config-driven).

**Missing: `run_python_pipeline()`.** No Python runner exists today.
When added, it should follow the Java pattern: no build tracing,
dependency graph from pip metadata.

### A.2 Build Instrumentation Layer

#### `app/pipeline/builder.py` — BomtraceBuilder

Two methods:

**`build()` (lines 26–112)** — Used by C/C++, Go, Rust:

1. Runs `clean_cmd` (line 53–62)
2. Runs pre-build steps (lines 65–78)
3. Runs `{tracer} {last_build_step}` (lines 80–92)
4. Runs `bomsh_create_bom.py -r {raw_logfile} -b {bom_dir}` (lines 95–106)

**Sidecar impact for `build()`:**

- **C/C++:** The `tracer` field becomes empty; `CC=`/`CXX=` must be set.
  This requires either env var support in `CommandRunner.run()` or
  embedding the env vars in the build step.
- **Go:** `-toolexec=<wrapper>` is embedded in the build step. The `tracer`
  field becomes empty. Step 4 (`bomsh_create_bom.py`) still runs — the
  Go wrapper writes its own raw logfile in the same format.
- **Rust:** `RUSTC_WRAPPER=<wrapper>` is set as an env var. Same
  considerations as Go.

**`build_java()` (lines 114–221)** — Used by Java:

1. Runs `clean_cmd`
2. Runs pre-build steps
3. Runs `strace {strace_opts} -o {strace_log} {build_cmd}` (line 165–167)
4. Runs `bomsh_create_bom_java.py -r {repo_dir} -j {treedb_file}` (lines 183–189)
5. Archives strace log to metadata dir (lines 199–215)

**Sidecar impact for `build_java()`: None.** The strace-based approach
already wraps whatever `mvn`/`gradle` is on PATH. The JDK used is
whatever is installed on the host.

**One optimization opportunity:** Replace strace with `mvn dependency:tree`
(see Section 4.4). This would require a new `build_java_no_strace()` method
or a config flag to skip strace.

#### `app/config.yaml` — Tracer Configuration

Current per-language tracer config:

```yaml
omnibor:              # C/C++
  tracer: bomtrace3
  raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1

omnibor_rust:         # Rust
  tracer: bomtrace2
  raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1

omnibor_go:           # Go
  tracer: bomtrace2 -c /opt/bomsh/bin/bomtrace_go.conf
  raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1

omnibor_java:         # Java — already uses strace, not bomtrace
  strace_opts: -f -s99999 --seccomp-bpf -e trace=openat -qqq
  strace_logfile: /tmp/strace_java_logfile
```

**Sidecar mode config (proposed additions):**

```yaml
omnibor_sidecar:      # C/C++ sidecar
  tracer: ""          # No tracer prefix — CC= wrapper handles it
  wrapper_cc: /opt/bomsh/gcc-wrapper
  wrapper_cxx: /opt/bomsh/g++-wrapper
  wrapper_ar: /opt/bomsh/ar-wrapper
  wrapper_ld: /opt/bomsh/ld-wrapper
  wrapper_as: /opt/bomsh/as-wrapper
  wrapper_ranlib: /opt/bomsh/ranlib-wrapper
  raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1

omnibor_go_sidecar:   # Go sidecar
  tracer: ""
  toolexec: /opt/bomsh/bomsh_go_wrapper
  raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1

omnibor_rust_sidecar: # Rust sidecar
  tracer: ""
  rustc_wrapper: /opt/bomsh/bomsh_rustc_wrapper
  raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1
```

### A.3 ADG Parsing and SPDX Generation Layer

#### `app/spdx/parser.py` — AdgParser

The parser reads `bomsh_omnibor_treedb` (JSON) and classifies artifacts
into categories. Current classification logic (lines 51–108):

```python
go_stdlib_prefix = "/usr/local/go/src/"
# Classification by path:
# /usr/local/go/src/  → go_stdlib
# /usr/lib             → system_lib or crt_object
# /usr/include          → system_header
# {repos_dir}           → project_source or build_intermediate
# /.cargo/registry/src/ → project_source (Rust crates)
# everything else       → system_header
```

**Sidecar impact:**

- **`go_stdlib_prefix`** is hardcoded to `/usr/local/go/src/`. In sidecar
  mode, the Go SDK may be at a different path (e.g., `/usr/lib/go/src/`
  on some distros, or `$GOROOT/src/`). This needs to be **configurable
  or auto-detected** from `GOROOT`.
- **`/usr/lib` classification** assumes Debian/Ubuntu dpkg-based paths.
  In sidecar mode on RHEL/CentOS, system libs are at `/usr/lib64/`.
  The classifier needs **distro-agnostic path matching**.
- **`/.cargo/registry/src/`** is hardcoded. In sidecar mode, Cargo
  registry may be at `$CARGO_HOME/registry/src/` which could differ.

#### `app/spdx/emitter.py` — SpdxEmitter (911 lines — flagged for refactoring)

This is the largest file in the codebase. It handles all three compiled
languages: C/C++, Go, Rust.

**Go-specific logic (lines 413–504):**

- Detects Go compiler version from stdlib build commands or
  `/usr/local/go/VERSION` (hardcoded path)
- Adds Go compiler as `BUILD_TOOL_OF`
- Adds `go-stdlib` as `DEPENDS_ON` with file count
- Parses `go.mod` for direct vs. indirect classification
- Parses `vendor/modules.txt` for module versions

**Sidecar impact:** The `/usr/local/go/VERSION` fallback path (line 118
in `lang_parsers.py`) is container-specific. In sidecar mode, Go version
should come from `go version` output or `$GOROOT/VERSION`.

**Rust-specific logic (lines 596–690):**

- Parses `Cargo.lock` for crate versions
- Parses `Cargo.toml` for direct dependency classification
- Uses `STATIC_LINK` relationship for all Rust crates
- Detects crate names from `/.cargo/registry/src/` paths

**Sidecar impact:** The Cargo registry path regex
(`_CARGO_REGISTRY_RE` in `lang_parsers.py`) hardcodes
`/.cargo/registry/src/[^/]+/`. In sidecar mode, `$CARGO_HOME` may
differ. Make the path configurable.

**C/C++ logic (lines 506–814):**

- Adds GCC as `BUILD_TOOL_OF` (always, even for Go — CGo)
- Detects vendored libraries via path patterns
- Uses `VendoredVersionDetector` for C/C++ version detection
  (12 strategies in `app/version_detection/`)
- Applies `DYNAMIC_LINK` for system libraries
- Applies `STATIC_LINK` + `CONTAINS` for vendored libraries

**Sidecar impact:** The GCC build tool is added unconditionally (lines
508–547). In sidecar mode with Go or Rust, GCC may not be the compiler.
Need conditional: only add GCC if the language is `c-cpp` or if CGo
was detected.

#### `app/spdx/java_generator.py` — JavaSpdxGenerator (627 lines)

**Already sidecar-compatible.** The Java generator:

1. Reads treedb from `bomsh_create_bom_java.py` output
2. Calls `mvn dependency:tree` or `./gradlew dependencies` at runtime
3. Filters by Maven/Gradle scope
4. Uses strace `openat` log to verify file access

**Sidecar impact: Minimal.** The only change would be if strace is
replaced with `mvn dependency:tree` — the `strace_accessed` filter
(lines 241–249) would become optional.

#### `app/spdx/maven_parser.py` / `app/spdx/gradle_parser.py`

**Already sidecar-compatible.** These parsers call `mvn` and `./gradlew`
directly via `subprocess.run()`. They work with whatever JDK/Maven/Gradle
is on PATH.

#### `app/spdx/lang_parsers.py` — Go/Rust parsers

**Mostly sidecar-compatible.** Key hardcoded paths to fix:

| Function | Hardcoded Path | Sidecar Fix |
|----------|---------------|-------------|
| `detect_go_version()` | `/usr/local/go/VERSION` | Read `$GOROOT/VERSION` or `go version` output |
| `rust_crate_from_registry_path()` | `/.cargo/registry/src/` | Read `$CARGO_HOME/registry/src/` |
| `go_module_from_vendor_path()` | None — relative paths | No change needed |

### A.4 Metadata and Dependency Resolution Layer

#### `app/pipeline/metadata_collector.py` — MetadataCollector

Calls `collect_metadata.py` (in-container bomsh script) to:

1. Parse `bomsh_omnibor_treedb` for system file paths
2. Run `dpkg-query` to get metadata for each system library
3. Write `component_metadata.json`

**Sidecar impact: Major.** The `dpkg-query` approach is
**Debian/Ubuntu-specific**. In sidecar mode on RHEL/CentOS/Fedora, the
equivalent is `rpm -qf`. On Alpine, it's `apk info --who-owns`.

This is the **Package Resolver Abstraction** identified in
`enterprise-integration-guide.md` — distro-specific implementations
for resolving system packages. The current code must be abstracted
behind a distro-detection layer.

#### `app/pipeline/validator.py` — DependencyValidator

Runs `dpkg-query -W` to check apt dependencies.

**Sidecar impact: Major.** Same distro-specific problem as
`MetadataCollector`. In sidecar mode, `apt_deps` becomes irrelevant
since the host manages its own packages. This validator should be
**skipped entirely** in sidecar mode — the host's package manager
owns system dependency management.

#### `app/spdx/resolver.py` — ComponentResolver

Generates PURLs with `pkg:deb/ubuntu/` prefix (line 181):

```python
return (
    f"pkg:deb/ubuntu/{dpkg_pkg}"
    f"@{version}"
    f"?arch={arch}&distro={distro}"
)
```

**Sidecar impact:** PURL prefix must be distro-aware: `pkg:deb/`
for Debian/Ubuntu, `pkg:rpm/` for RHEL/CentOS/Fedora,
`pkg:apk/` for Alpine. The `distro_codename` property already
extracts "ubuntu-22.04" but only handles Ubuntu.

### A.5 Binary Collection and Post-Processing

#### `app/pipeline/binary_collector.py` — BinaryCollector

Copies output binaries from build tree to timestamped output dirs.

**Sidecar impact: None.** The collector is path-based and does not
depend on toolchains or container-specific logic.

#### `app/pipeline/spdx_generator.py` — SpdxGenerator

Calls `bomsh_sbom.py` to generate initial SPDX, then patches metadata.
The `_bomtrace_version()` method (lines 77–104) reads version from
`strings bomtrace3` output.

**Sidecar impact:** In sidecar mode without bomtrace3, the version
helper returns "unknown." The `creators` list should reflect the
actual tracing mechanism used (e.g., `Tool: bomsh-go-wrapper-1.0`
instead of `Tool: bomtrace3-unknown`).

### A.6 Python Support — Current State

**No pipeline runner exists.** The `runners.py` `lang_omnibor_keys`
dict has no `"python"` entry. The `lang_runners.py` has no
`run_python_pipeline()`.

**No SPDX generator exists.** There is no `PythonSpdxGenerator` class.

**Analysis doc exists:** `docs/deep-dive/python-omnibor-support-analysis.md`
(1342 lines) provides a comprehensive gap analysis:

- `bomsh_pylib.py` (upstream) does static AST import analysis only
- Missing: venv awareness, pip metadata parsing, C extension detection,
  requirements.txt/pyproject.toml parsing, wheel/sdist awareness
- The `RECORD` file in `dist-info/` is Python's raw logfile equivalent
- `pip install` IS the build command for Python

**Sidecar impact for Python:** Python is inherently sidecar-friendly.
There is no compilation step to intercept (except for C extensions).
The SBOM comes from `pip freeze` + `importlib.metadata` + `dist-info/RECORD`.
No bomtrace, strace, or wrapper is needed for pure Python packages.

For packages with C extensions, strace during `pip install` would capture
`gcc`/`g++` invocations — similar to the Java strace pattern in
`build_java()`.

### A.7 Summary: Files That Must Change for Sidecar Mode

| File | Change Type | Description |
|------|-------------|-------------|
| `app/config.yaml` | **Extend** | Add sidecar-mode config sections with wrapper paths |
| `app/pipeline/builder.py` | **Extend** | Support env-var-based instrumentation (Option A) or no change (Option B) |
| `app/pipeline/lang_runners.py` | **Extend** | Add `run_python_pipeline()` |
| `app/pipeline/runners.py` | **Extend** | Add `"python"` to `lang_omnibor_keys` |
| `app/spdx/parser.py` | **Fix** | Make Go stdlib prefix and system lib paths configurable |
| `app/spdx/lang_parsers.py` | **Fix** | Replace hardcoded `/usr/local/go/VERSION` and `/.cargo/registry/src/` with env-var-based paths |
| `app/spdx/emitter.py` | **Fix** | Conditional GCC build-tool addition (only for C/C++); refactor (>400 lines) |
| `app/pipeline/metadata_collector.py` | **Major** | Abstract dpkg-query behind distro-agnostic package resolver |
| `app/pipeline/validator.py` | **Skip** | Disable in sidecar mode (host manages its own deps) |
| `app/spdx/resolver.py` | **Fix** | Distro-aware PURL generation (deb/rpm/apk) |
| `app/pipeline/spdx_generator.py` | **Fix** | Tracer version detection for wrapper-based mode |

| File | Change Type | Description |
|------|-------------|-------------|
| `app/spdx/java_generator.py` | **None** | Already sidecar-compatible |
| `app/spdx/maven_parser.py` | **None** | Already sidecar-compatible |
| `app/spdx/gradle_parser.py` | **None** | Already sidecar-compatible |
| `app/spdx/relationships.py` | **None** | Already language-agnostic |
| `app/spdx/vendored.py` | **None** | Already path-based |
| `app/pipeline/binary_collector.py` | **None** | Already path-based |
| `app/pipeline/facade.py` | **None** | Already language-agnostic |
| `app/config.py` | **None** | Already generic |

### A.8 New Files Required for Sidecar Mode

| New File | Purpose |
|----------|---------|
| `app/pipeline/python_spdx_generator.py` | Python SPDX generation from pip metadata |
| `app/pipeline/package_resolver.py` | Distro-agnostic system package resolver (dpkg/rpm/apk) |
| `wrappers/gcc-wrapper` (or `.go`/`.c`) | C/C++ compiler wrapper for sidecar mode |
| `wrappers/bomsh_go_wrapper.go` | Go `-toolexec` wrapper |
| `wrappers/bomsh_rustc_wrapper.rs` | Rust `RUSTC_WRAPPER` wrapper |

### A.9 Hardcoded Paths Inventory

All container-specific hardcoded paths that must become configurable
for sidecar mode:

| File | Line | Hardcoded Path | Used For |
|------|------|----------------|----------|
| `app/spdx/parser.py` | 51 | `/usr/local/go/src/` | Go stdlib classification |
| `app/spdx/parser.py` | 67 | `/usr/lib` | System library classification |
| `app/spdx/parser.py` | 86 | `/usr/include` | System header classification |
| `app/spdx/parser.py` | 99 | `/.cargo/registry/src/` | Rust crate detection |
| `app/spdx/lang_parsers.py` | 118 | `/usr/local/go/VERSION` | Go version detection |
| `app/spdx/lang_parsers.py` | 37 | `/.cargo/registry/src/[^/]+/` | Rust crate name/version extraction |
| `app/spdx/emitter.py` | 496 | `/usr/local/go/src/` | Go stdlib source info |
| `app/spdx/emitter.py` | 539 | `{self.distro}` | GCC source info (assumes container distro) |
| `app/pipeline/spdx_generator.py` | 28 | `/opt/bomsh` | Bomsh install directory |
| `app/config.yaml` | 311 | `/workspace/repos` | Container repos directory |
| `app/config.yaml` | 312 | `/workspace/output` | Container output directory |
| `app/config.yaml` | 314 | `/opt/bomsh` | Container bomsh directory |
| `app/config.yaml` | 319 | `/tmp/bomsh_hook_raw_logfile.sha1` | Tracer raw logfile |
| `app/config.yaml` | 335 | `/tmp/strace_java_logfile` | Java strace logfile |

---

---

<a id="9-appendix-b-build-rules-impact-guide-for-development-teams"></a>

## 9. Appendix B: Build Rules Impact Guide for Development Teams

**Audience:** Development teams whose products will be analyzed by
`omnibor-analysis` to produce build-time SPDX SBOMs. This appendix
describes, per source language, what build practices are compatible
with OmniBOR interception, what must be modified, and common pitfalls.

### Compatibility Rating Legend

| Rating | Meaning |
|--------|---------|
| **Compatible** | Works with OmniBOR interception as-is — no build changes needed |
| **Minor change** | Small, mechanical change to build config (env var, flag, option) |
| **Requires review** | Build system design may need adjustment — team should evaluate |
| **Incompatible** | This practice prevents or degrades SBOM generation — must be changed |

---

<a id="b1-cc-autoconf--cmake--meson--makefile"></a>

### B.1 C/C++ (autoconf / CMake / Meson / Makefile)

#### Interception mechanism

OmniBOR interposes on the compiler toolchain via environment variables:

```bash
CC=/opt/bomsh/gcc-wrapper    \
CXX=/opt/bomsh/g++-wrapper   \
AR=/opt/bomsh/ar-wrapper      \
LD=/opt/bomsh/ld-wrapper      \
make -j$(nproc)
```

Each wrapper calls the real compiler, then hashes the output. The build
itself is unchanged — same source, same flags, same binary output.

#### What must be true about your build

<table>
<tr>
  <th style="min-width:280px">Requirement</th>
  <th style="min-width:80px">Rating</th>
  <th>Details</th>
</tr>
<tr>
  <td><strong>Build system respects <code>CC=</code> / <code>CXX=</code></strong></td>
  <td><strong>Compatible</strong></td>
  <td>autoconf, CMake, Meson, and GNU Make all honor <code>CC</code>/<code>CXX</code> by default. This is the standard mechanism used by ccache, distcc, scan-build, and Coverity.</td>
</tr>
<tr>
  <td><strong>Build system respects <code>AR=</code> / <code>LD=</code></strong></td>
  <td><strong>Compatible</strong></td>
  <td>Same as above. Most build systems propagate these automatically.</td>
</tr>
<tr>
  <td><strong>No hardcoded compiler paths</strong></td>
  <td><strong>Requires review</strong></td>
  <td>If your Makefile contains <code>/usr/bin/gcc</code> or <code>/usr/bin/g++</code> instead of <code>$(CC)</code> / <code>$(CXX)</code>, the wrapper will be bypassed for those invocations, creating gaps in the SBOM. Search your build files for absolute compiler paths.</td>
</tr>
<tr>
  <td><strong>No compiler invoked via <code>$(shell ...)</code></strong></td>
  <td><strong>Requires review</strong></td>
  <td>Some Makefiles invoke the compiler in <code>$(shell ...)</code> expressions for feature detection. These bypass <code>CC=</code>. If your configure step compiles test programs via shell, those will be missed — but this usually only affects feature probes, not production code.</td>
</tr>
<tr>
  <td><strong>Assembly files via <code>as</code> or <code>nasm</code>/<code>yasm</code></strong></td>
  <td><strong>Minor change</strong></td>
  <td>If your project compiles <code>.s</code> or <code>.asm</code> files directly (e.g., FFmpeg, Linux kernel), <code>AS=</code> must also be set. OmniBOR provides an <code>as-wrapper</code> for this.</td>
</tr>
<tr>
  <td><strong>Release builds (not debug)</strong></td>
  <td><strong>Requires review</strong></td>
  <td>SBOMs must reflect production binaries. Ensure your build uses release optimization flags (<code>-O2</code>/<code>-O3</code>), not debug (<code>-g -O0</code>). Do not pass <code>--enable-debug</code> to <code>./configure</code>. Do not set <code>CFLAGS="-g -O0"</code>.</td>
</tr>
<tr>
  <td><strong>Parallel builds (<code>-j</code>)</strong></td>
  <td><strong>Compatible</strong></td>
  <td><code>make -j$(nproc)</code> works correctly — each wrapper invocation runs independently. No serialization bottleneck.</td>
</tr>
<tr>
  <td><strong>Out-of-tree builds</strong></td>
  <td><strong>Compatible</strong></td>
  <td>CMake out-of-tree builds (<code>cmake -B build && cmake --build build</code>) work normally. The wrapper follows the compiler invocation regardless of working directory.</td>
</tr>
<tr>
  <td><strong>Cross-compilation with custom sysroot</strong></td>
  <td><strong>Minor change</strong></td>
  <td>If you set <code>CC=arm-linux-gnueabihf-gcc</code>, the OmniBOR wrapper must be configured to delegate to the cross-compiler instead of the native one. The wrapper's <code>REAL_CC</code> variable must point to the cross-compiler.</td>
</tr>
<tr>
  <td><strong>Managed toolchain from internal repository</strong></td>
  <td><strong>Requires review</strong></td>
  <td>Enterprise teams may pull compilers from trusted artifact repositories (Artifactory, Nexus, internal RPM/DEB repos) and install them at non-standard paths like <code>/opt/cisco-toolchain/bin/gcc-12</code>, <code>/opt/rh/devtoolset-11/root/usr/bin/gcc</code>, or <code>/tools/vendor/arm-gcc-12/bin/arm-none-eabi-gcc</code>. The OmniBOR wrapper must discover the real compiler on <code>PATH</code> (skipping itself) rather than assuming <code>/usr/bin/gcc</code>. If the toolchain binary has a non-standard name (e.g., <code>cisco-gcc-12</code>), bomsh's compiler detection regex must also be extended.</td>
</tr>
<tr>
  <td><strong>Red Hat Software Collections (<code>scl enable</code>)</strong></td>
  <td><strong>Requires review</strong></td>
  <td><code>scl enable devtoolset-11 -- make -j$(nproc)</code> creates a sub-shell with <code>PATH</code> and <code>CC</code>/<code>CXX</code> pointing to <code>/opt/rh/devtoolset-11/...</code>. If <code>CC=</code> is set <em>before</em> <code>scl enable</code>, the SCL environment may override it. <code>CC=</code> must be set <em>inside</em> the SCL shell, or the wrapper must appear earlier in <code>PATH</code> than the SCL toolchain.</td>
</tr>
<tr>
  <td><strong>Nix / Guix build environments</strong></td>
  <td><strong>Incompatible</strong></td>
  <td>Nix-based builds (<code>nix-shell</code>, <code>nix develop</code>) set <code>CC=/nix/store/&lt;hash&gt;-gcc-12/bin/gcc</code> with immutable paths. The build system resolves compilers from the Nix store at evaluation time. Injecting <code>CC=</code> externally conflicts with Nix's hermetic guarantees. <strong>Nix builds require a custom Nix overlay</strong> that wraps the compiler derivation, or falling back to <code>bomtrace3</code> (ptrace) which operates below the build system.</td>
</tr>
<tr>
  <td><strong>Bazel / Buck2 / Pants (hermetic builds)</strong></td>
  <td><strong>Incompatible</strong></td>
  <td>Bazel ignores <code>CC=</code>/<code>CXX=</code> entirely. It uses <code>--crosstool_top</code> or <code>cc_toolchain</code> rules to resolve compilers from its own toolchain registry. Bazel may also download toolchains at build time. <strong><code>CC=</code> wrapping does not work with Bazel.</strong> See section B.7 for mitigation strategies.</td>
</tr>
<tr>
  <td><strong>Yocto / OpenEmbedded / BitBake</strong></td>
  <td><strong>Incompatible</strong></td>
  <td>BitBake recipes set their own <code>CC</code>/<code>CXX</code>/<code>LD</code>/<code>AR</code> per recipe, overriding any external values. The cross-compilation sysroot and toolchain are managed by Yocto. External <code>CC=</code> injection is ignored or actively overwritten. <strong>Requires a Yocto-specific class</strong> that wraps the recipe's toolchain variables.</td>
</tr>
<tr>
  <td><strong>Existing <code>CC=</code> wrapper conflict (ccache, distcc, Coverity)</strong></td>
  <td><strong>Requires review</strong></td>
  <td>If the team already uses <code>CC="ccache gcc"</code> or <code>CC="distcc gcc"</code>, adding OmniBOR's wrapper creates a conflict — <code>CC=</code> can only hold one value. <strong>The OmniBOR wrapper must support chaining:</strong> <code>CC="/opt/omnibor/gcc-wrapper"</code> where the wrapper calls <code>ccache gcc</code> (preserving the existing wrapper). Alternatively, <code>CMAKE_C_COMPILER_LAUNCHER</code> can stack wrappers in CMake projects.</td>
</tr>
<tr>
  <td><strong>CMake <code>CMAKE_C_COMPILER</code> hardcoded in CMakeLists.txt</strong></td>
  <td><strong>Incompatible</strong></td>
  <td>Some projects set <code>set(CMAKE_C_COMPILER /opt/gcc-12/bin/gcc)</code> directly in <code>CMakeLists.txt</code>, bypassing both <code>CC=</code> and CMake's toolchain file. The <code>CC=</code> env var is only consulted on the first CMake configure; if the cache already has <code>CMAKE_C_COMPILER</code>, it is ignored on subsequent runs. <strong>Delete <code>CMakeCache.txt</code></strong> and set <code>-DCMAKE_C_COMPILER=</code> on the command line, or use <code>CMAKE_C_COMPILER_LAUNCHER</code> which does chain.</td>
</tr>
<tr>
  <td><strong>Meson cross-file with hardcoded binaries</strong></td>
  <td><strong>Requires review</strong></td>
  <td>Meson cross-compilation files (<code>[binaries] c = '/opt/arm-gcc/bin/arm-gcc'</code>) override <code>CC=</code>. The wrapper path must be specified in the cross file instead, with the wrapper configured to delegate to the real cross-compiler.</td>
</tr>
<tr>
  <td><strong><code>zig cc</code> as C compiler</strong></td>
  <td><strong>Requires review</strong></td>
  <td>Zig is increasingly used as a C cross-compiler (<code>CC="zig cc"</code>) because it bundles musl and targets many platforms. The OmniBOR wrapper can wrap <code>zig cc</code> like any other compiler, but bomsh's compiler detection must recognize <code>zig</code> as a compiler invocation.</td>
</tr>
<tr>
  <td><strong>CMake <code>ExternalProject_Add</code></strong></td>
  <td><strong>Requires review</strong></td>
  <td>CMake's <code>ExternalProject_Add</code> downloads and builds external dependencies in a sub-build with its own compiler settings. The <code>CC=</code> from the parent build may not propagate to external projects. Each external project may need explicit <code>CMAKE_ARGS -DCMAKE_C_COMPILER=...</code> passthrough.</td>
</tr>
</table>

#### Common C/C++ pitfalls

1. **Static libraries built with `ar` but `AR=` not set** — The SBOM will
   show the final binary's inputs but miss intermediate `.a` archive
   composition. Always set `AR=/opt/bomsh/ar-wrapper`.

2. **`ranlib` invoked separately** — Some build systems run `ranlib` after
   `ar` to regenerate the archive index. Set `RANLIB=/opt/bomsh/ranlib-wrapper`.

3. **`strip` applied post-build** — Stripping symbols changes the binary
   hash but doesn't affect SBOM accuracy. However, if `strip` runs between
   the link step and SBOM generation, the recorded hash will differ from the
   shipped binary. Run SBOM generation before stripping, or record both hashes.

4. **Vendored third-party code in non-standard directories** — OmniBOR
   detects vendored libraries under `/deps/`, `/vendor/`, `/third_party/`,
   `/thirdparty/`, `/external/`, and `/contrib/`. If your vendored code
   lives elsewhere (e.g., `/3rdparty/`, `/subprojects/`), declare the
   custom path in `config.yaml` via the `vendored_dirs` field.

5. **Autotools `./configure` regenerates build system files** — Running
   `autoreconf -fi` before `./configure` is standard practice. These
   generated files (e.g., `Makefile.in`, `config.h`) are intermediate
   artifacts, not source code. OmniBOR classifies them as
   `build_intermediate` automatically.

6. **Wrapper stacking order matters** — If the team uses ccache, the call
   chain must be: `OmniBOR wrapper → ccache → real compiler`. If reversed,
   ccache returns a cached result and OmniBOR never sees the real compiler
   invocation. The OmniBOR wrapper must be the **outermost** wrapper.

7. **CMake cache persists the compiler path** — CMake stores the resolved
   `CMAKE_C_COMPILER` in `CMakeCache.txt` on the first configure. Setting
   `CC=` on subsequent runs has **no effect** unless the cache is deleted.
   Always delete `CMakeCache.txt` and the build directory before an
   OmniBOR-instrumented build, or use `CMAKE_C_COMPILER_LAUNCHER`.

8. **Toolchain wrappers that fork** — Some enterprise toolchains wrap `gcc`
   in a shell script that performs license checks, telemetry, or environment
   setup before calling the real compiler. If this wrapper uses `exec`, the
   OmniBOR wrapper sees it correctly. If it uses a child process (no `exec`),
   the real compiler invocation may have a different PID and the wrapper's
   output-hash step may fail. Test the specific toolchain wrapper behavior.

9. **Makefile recipes that use `$(shell which gcc)`** — This resolves the
   compiler path at Makefile parse time, before `CC=` takes effect. The
   resolved path bypasses the wrapper. Audit Makefiles for `$(shell which ...)`
   or `$(shell gcc ...)` patterns.

#### Example: curl (reference C/C++ project)

```yaml
# config.yaml entry — no special modifications needed
curl:
  build_steps:
    - autoreconf -fi
    - ./configure --with-openssl --with-zlib
    - make -j$(nproc)           # CC=/CXX= injected by OmniBOR
  output_binaries:
    - src/.libs/curl
    - lib/.libs/libcurl.so
```

The build steps are identical to a normal curl build. OmniBOR injects
`CC=`/`CXX=`/`AR=`/`LD=` when running the final `make` step.

---

<a id="b2-go"></a>

### B.2 Go

#### Interception mechanism

OmniBOR uses Go's built-in `-toolexec` flag:

```bash
go build -a -toolexec=/opt/bomsh/bomsh_go_wrapper \
    -trimpath -ldflags="-s -w" -o binary .
```

The wrapper intercepts every `compile` and `link` invocation that Go's
build system makes.

#### What must be true about your build

<table>
<tr>
  <th style="min-width:280px">Requirement</th>
  <th style="min-width:80px">Rating</th>
  <th>Details</th>
</tr>
<tr>
  <td><strong>Standard <code>go build</code> invocation</strong></td>
  <td><strong>Compatible</strong></td>
  <td>Any project built with <code>go build</code> or <code>go install</code> is compatible. The <code>-toolexec</code> flag is a stable Go feature.</td>
</tr>
<tr>
  <td><strong>The <code>-a</code> flag (rebuild all)</strong></td>
  <td><strong>Incompatible without</strong></td>
  <td>OmniBOR <strong>requires <code>-a</code></strong> to force a full rebuild. Without it, Go's build cache serves cached results and the wrapper never sees cached packages — creating SBOM gaps. This is the single biggest impact for Go teams: <strong>every OmniBOR build is a clean build</strong>. Build times increase ~100–200%.</td>
</tr>
<tr>
  <td><strong><code>-trimpath</code> flag</strong></td>
  <td><strong>Minor change</strong></td>
  <td>Required for release builds. Strips local filesystem paths from the binary. Without it, the SBOM may contain host-specific paths.</td>
</tr>
<tr>
  <td><strong><code>-ldflags="-s -w"</code></strong></td>
  <td><strong>Minor change</strong></td>
  <td>Required for release builds. Strips symbol table and DWARF debug info. Without it, the binary is a debug build.</td>
</tr>
<tr>
  <td><strong><code>go generate</code> step</strong></td>
  <td><strong>Compatible</strong></td>
  <td>If your project uses <code>go generate</code>, run it as a separate pre-build step. The generated <code>.go</code> files will be picked up by the instrumented <code>go build</code>.</td>
</tr>
<tr>
  <td><strong>CGo (C code called from Go)</strong></td>
  <td><strong>Requires review</strong></td>
  <td>CGo invokes the system C compiler. The <code>-toolexec</code> wrapper does <strong>not</strong> intercept CGo's C compilation — it only wraps Go's own <code>compile</code> and <code>link</code> tools. If your project uses CGo extensively, you may also need <code>CC=</code> wrapping for complete coverage.</td>
</tr>
<tr>
  <td><strong>Vendored dependencies (<code>go mod vendor</code>)</strong></td>
  <td><strong>Compatible</strong></td>
  <td>OmniBOR detects vendored Go modules under <code>vendor/</code> and extracts full module names (e.g., <code>github.com/fatih/color</code>). Versions are read from <code>vendor/modules.txt</code>. Direct vs. indirect classification comes from <code>go.mod</code>.</td>
</tr>
<tr>
  <td><strong>Module proxy (<code>GOPROXY</code>)</strong></td>
  <td><strong>Compatible</strong></td>
  <td>OmniBOR does not interact with the module proxy. Dependencies resolved via <code>GOPROXY</code> end up in the module cache and are compiled normally.</td>
</tr>
<tr>
  <td><strong>Custom build tags (<code>-tags</code>)</strong></td>
  <td><strong>Compatible</strong></td>
  <td>Build tags do not interfere with <code>-toolexec</code>. The wrapper sees whatever files the Go compiler selects.</td>
</tr>
<tr>
  <td><strong>Multi-binary builds (monorepo)</strong></td>
  <td><strong>Minor change</strong></td>
  <td>Each <code>go build</code> invocation produces one SBOM. If your project builds multiple binaries, each needs a separate <code>go build -toolexec=...</code> invocation listed in <code>config.yaml</code>'s <code>build_steps</code>.</td>
</tr>
<tr>
  <td><strong>Bazel with <code>rules_go</code></strong></td>
  <td><strong>Incompatible</strong></td>
  <td>Bazel's <code>rules_go</code> does not use <code>go build</code> at all. It invokes the Go compiler and linker directly via Bazel actions. There is no <code>-toolexec</code> injection point. <strong>See section B.7.</strong> Bazel Go builds require either a custom Bazel rule that wraps the Go toolchain, or falling back to <code>bomtrace3</code> ptrace mode.</td>
</tr>
<tr>
  <td><strong><code>GOTOOLCHAIN</code> auto-download (Go 1.21+)</strong></td>
  <td><strong>Requires review</strong></td>
  <td>Go 1.21+ reads <code>toolchain go1.X.Y</code> from <code>go.mod</code> and auto-downloads a specific Go version to <code>$HOME/sdk/go1.X.Y</code>. The <code>-toolexec</code> wrapper still works because Go invokes its own <code>compile</code>/<code>link</code> tools via <code>-toolexec</code> regardless of which SDK is active. However, the Go version used may differ from what's on <code>$PATH</code> — OmniBOR's version detection must read the <code>GOVERSION</code> from the actual SDK, not from <code>go version</code> on PATH.</td>
</tr>
<tr>
  <td><strong>CGo with vendored C libraries</strong></td>
  <td><strong>Requires review</strong></td>
  <td>Projects like SQLite bindings (<code>mattn/go-sqlite3</code>) vendor significant C code and compile it via CGo. The <code>-toolexec</code> wrapper only intercepts Go's own tools; it does <strong>not</strong> see CGo's <code>gcc</code>/<code>clang</code> invocations. To capture vendored C dependencies, <code>CC=</code> must also be set: <code>CC=/opt/omnibor/gcc-wrapper CGO_ENABLED=1 go build -a -toolexec=...</code></td>
</tr>
<tr>
  <td><strong><code>replace</code> directives in <code>go.mod</code></strong></td>
  <td><strong>Requires review</strong></td>
  <td><code>replace github.com/foo => ../local-foo</code> substitutes a dependency with a local directory. These replacements are invisible to <code>go.sum</code> (no checksum for local modules). OmniBOR must parse <code>go.mod</code> <code>replace</code> directives and flag them in the SBOM, as the actual code compiled differs from what the module path implies.</td>
</tr>
<tr>
  <td><strong>Makefile / shell script wrapping <code>go build</code></strong></td>
  <td><strong>Requires review</strong></td>
  <td>Many Go projects use a <code>Makefile</code> or <code>build.sh</code> that invokes <code>go build</code> with project-specific flags, ldflags, and version injection. The <code>-toolexec</code> flag must be added to <em>that</em> invocation — there is no environment variable equivalent. If the build script constructs the <code>go build</code> command programmatically, it must be modified to accept <code>-toolexec</code> as an additional flag.</td>
</tr>
</table>

#### Common Go pitfalls

1. **Forgetting `-a` creates silent SBOM gaps** — The SBOM will only
   contain packages that were actually compiled. Cached packages are
   invisible to the wrapper. This is the #1 source of incomplete Go SBOMs.

2. **`go build ./...` builds all packages but only links one binary** —
   If your monorepo has multiple `main` packages, `./...` will compile
   everything but only the first binary's SBOM is captured. Build each
   binary explicitly.

3. **Build scripts that invoke `go build` without `-toolexec`** — If your
   Makefile or shell script calls `go build` directly, the `-toolexec`
   flag must be added to that invocation. OmniBOR cannot inject it
   automatically — it must appear in `build_steps` in `config.yaml`.

4. **`go.sum` must be committed** — OmniBOR reads `go.sum` for module
   integrity verification. If `go.sum` is `.gitignore`'d (which violates
   Go best practices), dependency checksums cannot be verified.

5. **CGo projects silently miss C dependencies** — If the project uses
   CGo and `CC=` is not set alongside `-toolexec`, the C compilation
   is invisible. The SBOM will show Go packages but miss C library
   inputs. This is especially dangerous for security-sensitive code
   like crypto bindings.

6. **`replace` directives create phantom dependencies** — A `replace`
   directive substitutes module code without changing the import path.
   The SBOM will list the original module path, but the actual code
   compiled is from the replacement. This can mask vulnerability
   scanning results.

#### Example: fzf (reference Go project)

```yaml
fzf:
  build_steps:
    # -a forces full rebuild for complete SBOM
    # -toolexec injected by OmniBOR
    - 'go build -a -trimpath -ldflags="-s -w" -o fzf .'
  output_binaries:
    - fzf
```

---

<a id="b3-rust"></a>

### B.3 Rust

#### Interception mechanism

OmniBOR uses Cargo's built-in `RUSTC_WRAPPER` environment variable:

```bash
RUSTC_WRAPPER=/opt/bomsh/bomsh_rustc_wrapper cargo build --release
```

Cargo calls the wrapper for every `rustc` invocation. The wrapper
records inputs, calls the real `rustc`, and hashes outputs.

#### What must be true about your build

<table>
<tr>
  <th style="min-width:280px">Requirement</th>
  <th style="min-width:80px">Rating</th>
  <th>Details</th>
</tr>
<tr>
  <td><strong>Standard <code>cargo build --release</code></strong></td>
  <td><strong>Compatible</strong></td>
  <td>Any project built with <code>cargo build</code> is compatible. <code>RUSTC_WRAPPER</code> is a stable Cargo feature, used by sccache and mold.</td>
</tr>
<tr>
  <td><strong><code>--release</code> flag</strong></td>
  <td><strong>Incompatible without</strong></td>
  <td>OmniBOR <strong>requires <code>--release</code></strong>. Without it, Cargo produces a debug build at <code>target/debug/</code>. The SBOM must reflect production binaries at <code>target/release/</code>.</td>
</tr>
<tr>
  <td><strong>No <code>-a</code> problem (unlike Go)</strong></td>
  <td><strong>Compatible</strong></td>
  <td>Cargo release builds disable incremental compilation by default. Every crate is compiled fresh — no equivalent of Go's cache-skip problem.</td>
</tr>
<tr>
  <td><strong><code>Cargo.lock</code> committed</strong></td>
  <td><strong>Incompatible without</strong></td>
  <td>OmniBOR reads <code>Cargo.lock</code> for exact crate versions. For applications (not libraries), <code>Cargo.lock</code> <strong>must be committed</strong> to the repository. This is standard Rust practice for applications.</td>
</tr>
<tr>
  <td><strong><code>build.rs</code> (build scripts)</strong></td>
  <td><strong>Requires review</strong></td>
  <td><code>RUSTC_WRAPPER</code> wraps <code>rustc</code> invocations only — it does <strong>not</strong> intercept <code>build.rs</code> execution. If your <code>build.rs</code> compiles C code via the <code>cc</code> crate, that C compilation is invisible to the Rust wrapper. Teams with significant <code>build.rs</code> C compilation should also set <code>CC=</code>.</td>
</tr>
<tr>
  <td><strong>Proc-macro crates</strong></td>
  <td><strong>Compatible</strong></td>
  <td>Proc-macro crates are compiled via <code>rustc</code> and are wrapped normally. They compile for the host architecture (not the target), which is correct behavior.</td>
</tr>
<tr>
  <td><strong>Workspace builds</strong></td>
  <td><strong>Compatible</strong></td>
  <td>Cargo workspaces work with <code>RUSTC_WRAPPER</code>. Additionally, <code>RUSTC_WORKSPACE_WRAPPER</code> can be used to wrap only workspace crates (skip third-party), reducing overhead for large dependency trees.</td>
</tr>
<tr>
  <td><strong>Custom target specifications</strong></td>
  <td><strong>Compatible</strong></td>
  <td>Cross-compilation with <code>--target</code> works. The wrapper receives the target triple as part of the <code>rustc</code> invocation.</td>
</tr>
<tr>
  <td><strong>Feature flags (<code>--features</code>)</strong></td>
  <td><strong>Compatible</strong></td>
  <td>Feature flags do not interfere with <code>RUSTC_WRAPPER</code>. The wrapper sees whatever crates Cargo resolves.</td>
</tr>
<tr>
  <td><strong>Existing <code>RUSTC_WRAPPER</code> conflict (sccache)</strong></td>
  <td><strong>Incompatible</strong></td>
  <td>Cargo supports <strong>only one</strong> <code>RUSTC_WRAPPER</code>. If the team already uses <code>RUSTC_WRAPPER=sccache</code>, setting it to the OmniBOR wrapper displaces sccache. <strong>Mitigation:</strong> The OmniBOR wrapper must support chaining — call sccache (or the previous wrapper) as the "real rustc" delegate. Alternatively, use <code>RUSTC_WORKSPACE_WRAPPER</code> for OmniBOR (workspace crates only) alongside <code>RUSTC_WRAPPER=sccache</code> (all crates) — Cargo supports both simultaneously.</td>
</tr>
<tr>
  <td><strong><code>cross</code> tool for cross-compilation</strong></td>
  <td><strong>Requires review</strong></td>
  <td><code>cross build --target aarch64-unknown-linux-gnu</code> runs Cargo inside a Docker container with the cross-compilation toolchain. <code>RUSTC_WRAPPER</code> set on the host is <strong>not forwarded</strong> into the container. The wrapper must be installed inside the cross container image, or cross's <code>CROSS_CONFIG</code> must be modified to pass the wrapper through.</td>
</tr>
<tr>
  <td><strong>Custom linker via <code>CARGO_TARGET_*_LINKER</code></strong></td>
  <td><strong>Requires review</strong></td>
  <td>Some projects set <code>CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=lld</code> or use <code>[target.x86_64-unknown-linux-gnu] linker = "clang"</code> in <code>.cargo/config.toml</code>. <code>RUSTC_WRAPPER</code> wraps <code>rustc</code> invocations but does <strong>not</strong> wrap the linker. If the linker is non-standard, the final link step may produce outputs that the wrapper doesn't track. This is usually acceptable since the wrapper sees the <code>rustc</code> link invocation, which passes <code>-C linker=...</code> to the real linker.</td>
</tr>
<tr>
  <td><strong>Bazel with <code>rules_rust</code></strong></td>
  <td><strong>Incompatible</strong></td>
  <td>Bazel's <code>rules_rust</code> invokes <code>rustc</code> directly via Bazel actions, bypassing Cargo entirely. <code>RUSTC_WRAPPER</code> is a Cargo feature — it has no effect when <code>rustc</code> is called directly. <strong>See section B.7.</strong></td>
</tr>
<tr>
  <td><strong>Nightly-only features / custom <code>rustup</code> toolchains</strong></td>
  <td><strong>Compatible</strong></td>
  <td><code>rustup run nightly cargo build --release</code> works with <code>RUSTC_WRAPPER</code>. Cargo resolves the nightly <code>rustc</code> path and passes it to the wrapper as the first argument. The wrapper delegates to whatever <code>rustc</code> Cargo resolved.</td>
</tr>
<tr>
  <td><strong>Cargo <code>[patch]</code> / <code>[replace]</code> sections</strong></td>
  <td><strong>Requires review</strong></td>
  <td><code>[patch.crates-io]</code> in <code>Cargo.toml</code> substitutes a crate with a local path or git source. The patched crate is compiled normally (visible to the wrapper), but <code>Cargo.lock</code> may show the original crate version while the actual code differs. OmniBOR should detect <code>[patch]</code> entries and annotate them in the SBOM.</td>
</tr>
</table>

#### Common Rust pitfalls

1. **`cargo build` without `--release` produces debug binaries** — The
   SBOM will have paths containing `target/debug/` instead of
   `target/release/`. OmniBOR's parser explicitly excludes
   `target/debug/` artifacts from vendored detection to avoid this.

2. **`build.rs` compiling C/FFI code via the `cc` crate** — Crates
   like `openssl-sys`, `libz-sys`, `ring`, and `git2` compile C code
   through `build.rs`. This C compilation is invisible to
   `RUSTC_WRAPPER`. For projects with significant native code, set
   `CC=/opt/bomsh/gcc-wrapper` in addition to `RUSTC_WRAPPER`.

3. **`Cargo.lock` not committed for binary projects** — Without
   `Cargo.lock`, OmniBOR cannot determine exact dependency versions.
   The SBOM will have `versionInfo: NOASSERTION` for all third-party
   crates.

4. **Crate registry at non-standard location** — OmniBOR detects
   crate source files via the pattern `/.cargo/registry/src/`. If
   `$CARGO_HOME` is set to a custom location, this detection fails.
   Declare the custom path in config or set `$CARGO_HOME` to the
   default (`~/.cargo`).

5. **sccache and OmniBOR wrapper conflict** — Only one `RUSTC_WRAPPER`
   can be active. Teams using sccache must either: (a) configure the
   OmniBOR wrapper to chain through sccache, or (b) use
   `RUSTC_WORKSPACE_WRAPPER` for OmniBOR (which only wraps workspace
   crates) while keeping `RUSTC_WRAPPER=sccache` for all crates. Option
   (b) is preferred as it provides both caching and SBOM generation.

6. **`[patch]` sections mask the real dependency** — A `[patch.crates-io]`
   entry compiles local code under a crate's name. Vulnerability scanners
   querying the SBOM by crate name will get false results because the
   patched code may have different vulnerabilities than the published crate.

#### Example: oxipng (reference Rust project)

```yaml
oxipng:
  build_steps:
    - cargo build --release   # RUSTC_WRAPPER injected by OmniBOR
  output_binaries:
    - target/release/oxipng
```

---

<a id="b4-java-maven--gradle"></a>

### B.4 Java (Maven / Gradle)

#### Interception mechanism

Java uses a **post-build analysis** approach rather than compiler
wrapping:

1. **strace** captures `openat` syscalls during `mvn package` or
   `./gradlew build` to identify every file the JVM reads
2. **`bomsh_create_bom_java.py`** maps `.class` files to `.java` source
   files using `javap -v` analysis
3. **`mvn dependency:tree`** or **`./gradlew dependencies`** provides the
   full dependency graph with scope classification

This is already sidecar-compatible — the build runs with whatever
JDK/Maven/Gradle is natively installed.

#### What must be true about your build

<table>
<tr>
  <th style="min-width:280px">Requirement</th>
  <th style="min-width:80px">Rating</th>
  <th>Details</th>
</tr>
<tr>
  <td><strong>Standard Maven or Gradle build</strong></td>
  <td><strong>Compatible</strong></td>
  <td><code>mvn package</code> and <code>./gradlew build</code> both work. OmniBOR wraps the command with strace — no build system changes needed.</td>
</tr>
<tr>
  <td><strong><code>-DskipTests</code> (Maven) or <code>-x test</code> (Gradle)</strong></td>
  <td><strong>Minor change</strong></td>
  <td>OmniBOR requires tests to be skipped to ensure the SBOM reflects only production code. Test-scope dependencies should not appear in the production SBOM. Add <code>-DskipTests</code> for Maven or <code>-x test</code> for Gradle.</td>
</tr>
<tr>
  <td><strong>Gradle daemon mode</strong></td>
  <td><strong>Incompatible</strong></td>
  <td>Gradle's daemon (<code>--daemon</code>) persists across builds, which conflicts with strace capture — strace must trace the full build lifecycle from start to finish. <strong>Always use <code>--no-daemon</code></strong> for OmniBOR builds.</td>
</tr>
<tr>
  <td><strong><code>pom.xml</code> with resolvable dependencies</strong></td>
  <td><strong>Compatible</strong></td>
  <td>OmniBOR runs <code>mvn dependency:tree</code> to extract the dependency graph. All dependencies must be resolvable (available in configured repositories). If your project uses private Maven repositories, they must be accessible at analysis time.</td>
</tr>
<tr>
  <td><strong>Multi-module Maven/Gradle projects</strong></td>
  <td><strong>Compatible</strong></td>
  <td>Multi-module builds are supported. Use <code>-pl &lt;module&gt; -am</code> (Maven) or <code>:module:build</code> (Gradle) to target specific modules. OmniBOR generates one SBOM per output JAR.</td>
</tr>
<tr>
  <td><strong>Shade / Assembly / Fat JAR plugins</strong></td>
  <td><strong>Requires review</strong></td>
  <td>Shade plugins (Maven) and Shadow plugins (Gradle) repackage dependencies into a single JAR. The strace/treedb approach captures the final fat JAR. However, if test-scope dependencies are bundled by the shade plugin, they will appear in the SBOM. Annotate these in the SPDX <code>comment</code> field.</td>
</tr>
<tr>
  <td><strong>JDK version constraints</strong></td>
  <td><strong>Compatible</strong></td>
  <td>OmniBOR uses whatever JDK is installed (<code>$JAVA_HOME</code>). If your project requires a specific JDK version, ensure it is installed. The SBOM records the JDK version used.</td>
</tr>
<tr>
  <td><strong>Maven wrapper (<code>mvnw</code>)</strong></td>
  <td><strong>Compatible</strong></td>
  <td>If your project ships a Maven wrapper (<code>./mvnw</code>), OmniBOR can use it instead of system <code>mvn</code>. Configure this in <code>build_steps</code>.</td>
</tr>
<tr>
  <td><strong>Annotation processors (Lombok, MapStruct)</strong></td>
  <td><strong>Compatible</strong></td>
  <td>Annotation processors run inside <code>javac</code> during compilation. The strace approach captures all file I/O regardless of annotation processing. The <code>javap -v</code> analysis maps the generated <code>.class</code> files to their declaring source files.</td>
</tr>
<tr>
  <td><strong>Kotlin / Scala mixed-language JVM projects</strong></td>
  <td><strong>Requires review</strong></td>
  <td>The <code>javap -v</code> class-to-source mapping works for Java <code>.class</code> files. Kotlin produces standard <code>.class</code> files, so the mapping generally works, but may require <code>kotlinc</code>-aware analysis for accurate source attribution.</td>
</tr>
<tr>
  <td><strong>GraalVM <code>native-image</code></strong></td>
  <td><strong>Incompatible</strong></td>
  <td>GraalVM's <code>native-image</code> compiles Java bytecode to a native binary via ahead-of-time (AOT) compilation. This is a fundamentally different compilation model — the output is an ELF binary, not a JAR. The strace approach captures the <code>native-image</code> process's file I/O, but <code>javap -v</code> analysis does not apply to AOT-compiled code. <strong>Requires a dedicated GraalVM strategy</strong> that reads the native-image build report (<code>-H:+BuildReport</code>) for dependency information.</td>
</tr>
<tr>
  <td><strong>Quarkus native build</strong></td>
  <td><strong>Incompatible</strong></td>
  <td>Quarkus with <code>-Pnative</code> uses GraalVM native-image under the hood. Same limitations as GraalVM above. The Quarkus Maven plugin orchestrates the native compilation, but the output is a native binary, not a JAR.</td>
</tr>
<tr>
  <td><strong>Apache Ant builds</strong></td>
  <td><strong>Requires review</strong></td>
  <td>Ant does not have a <code>dependency:tree</code> equivalent. Dependencies are typically managed via <code>lib/</code> directories with manually downloaded JARs, or via Ivy (<code>ivy.xml</code>). OmniBOR's Maven/Gradle dependency parsers do not apply. <strong>Ant builds require a separate dependency resolution approach</strong> — either Ivy metadata parsing or classpath analysis from the <code>javac</code> invocation captured by strace.</td>
</tr>
<tr>
  <td><strong>JNI native code (Java calling C via JNI)</strong></td>
  <td><strong>Requires review</strong></td>
  <td>If the Java project includes JNI native code (<code>.c</code>/<code>.cpp</code> files compiled to <code>.so</code>/<code>.dll</code>), the C compilation is invisible to strace of <code>javac</code>/<code>mvn</code>. The JNI <code>.so</code> is typically built by a separate Makefile or CMake step. OmniBOR must instrument <em>both</em> the Java build (strace) and the native build (<code>CC=</code> wrapper) to produce a complete SBOM.</td>
</tr>
<tr>
  <td><strong>Gradle composite builds (<code>includeBuild</code>)</strong></td>
  <td><strong>Requires review</strong></td>
  <td><code>includeBuild("../other-project")</code> substitutes a dependency with a local project build. The included project is compiled as part of the main build, but its dependencies are resolved from its own <code>build.gradle</code>. OmniBOR's dependency tree from <code>./gradlew dependencies</code> shows the substitution, but the included project's transitive dependencies may be incomplete if its build files are not fully self-contained.</td>
</tr>
<tr>
  <td><strong>Maven BOM imports (<code>dependencyManagement</code> with <code>import</code> scope)</strong></td>
  <td><strong>Compatible</strong></td>
  <td>Maven BOM imports are resolved by <code>mvn dependency:tree</code> transparently. The imported BOM's version constraints are applied, and the resolved dependency tree reflects the actual versions used. No special handling needed.</td>
</tr>
<tr>
  <td><strong>Bazel with <code>rules_java</code> / <code>rules_jvm_external</code></strong></td>
  <td><strong>Incompatible</strong></td>
  <td>Bazel Java builds do not use Maven or Gradle. Dependencies are declared in <code>BUILD</code> files or fetched via <code>rules_jvm_external</code> from Maven Central. There is no <code>pom.xml</code> or <code>build.gradle</code> to parse. <strong>See section B.7.</strong></td>
</tr>
<tr>
  <td><strong>Private Maven repository with authentication</strong></td>
  <td><strong>Requires review</strong></td>
  <td>If <code>mvn dependency:tree</code> requires credentials (configured in <code>~/.m2/settings.xml</code>), those credentials must be available at OmniBOR analysis time. In CI, this typically means injecting <code>settings.xml</code> as a secret. If credentials are missing, <code>dependency:tree</code> fails and OmniBOR falls back to <code>pom.xml</code> parsing (which misses transitive dependencies from the private repo).</td>
</tr>
</table>

#### Common Java pitfalls

1. **Gradle `--daemon` creates invisible background compilation** — The
   daemon process outlives strace, causing incomplete capture. Always
   pass `--no-daemon`. Example from `config.yaml`:
   ```yaml
   build_steps:
     - ./gradlew :module:build -x test --no-daemon -q
   ```

2. **Private Maven repositories not accessible** — If `mvn dependency:tree`
   cannot resolve a dependency, OmniBOR falls back to `pom.xml` parsing,
   which may miss transitive dependencies. Ensure all repositories
   configured in `settings.xml` or `pom.xml` are reachable.

3. **Maven property references not resolvable** — If `pom.xml` uses
   property references (e.g., `${project.version}`, `${revision}`) that
   require parent POM resolution, and the parent POM is not available,
   version detection fails. Use CI-friendly properties
   (`-Drevision=1.2.3`) or ensure parent POMs are resolvable.

4. **Multi-module builds without `-pl`** — Building an entire
   multi-module project produces multiple JARs. If `output_binaries`
   uses `**/target/*.jar`, OmniBOR generates one SBOM per JAR. Use
   `-pl <module> -am` to target specific modules if you only want
   specific JARs analyzed.

5. **Test JARs (Maven `tests` classifier)** — OmniBOR's binary collector
   automatically skips JARs with classifiers like `tests`, `sources`,
   `javadoc`. No action needed if your project follows Maven naming
   conventions.

6. **GraalVM native-image produces native binaries, not JARs** — The
   entire Java SPDX pipeline assumes JAR output. GraalVM native-image
   produces ELF binaries that should be analyzed with the C/C++ pipeline
   (ADG from `bomtrace3` or `CC=` wrappers), augmented with Maven/Gradle
   dependency metadata for the Java dependency graph.

7. **JNI projects have split provenance** — The Java SBOM covers the
   JAR's dependencies, but the native `.so` has its own C/C++ dependency
   graph. A complete product SBOM must merge both. This is a known gap
   that requires manual composition until OmniBOR supports multi-language
   SBOM merging.

#### Example: checkstyle (reference Maven project)

```yaml
checkstyle:
  build_steps:
    - mvn package -DskipTests -q   # strace wrapping injected by OmniBOR
  output_binaries:
    - '**/target/*.jar'
```

#### Example: spring-boot (reference Gradle project)

```yaml
spring-boot:
  build_steps:
    - ./gradlew :spring-boot-project:spring-boot:build -x test -x check --no-daemon -q
  output_binaries:
    - '**/build/libs/*.jar'
```

---

<a id="b5-python-pip--setuptools--poetry"></a>

### B.5 Python (pip / setuptools / poetry)

#### Interception mechanism

Python does not require build interception for pure Python packages.
The SBOM is derived from **pip metadata**:

1. **`pip freeze`** — lists all installed packages with exact versions
2. **`importlib.metadata`** — reads `dist-info/METADATA` for each
   package (name, version, license, dependencies)
3. **`dist-info/RECORD`** — SHA-256 hash of every installed file
   (Python's equivalent of a raw logfile)

For packages with C extensions, `pip install` invokes the C compiler,
which can optionally be traced via strace or `CC=` wrapping.

#### What must be true about your build

<table>
<tr>
  <th style="min-width:280px">Requirement</th>
  <th style="min-width:80px">Rating</th>
  <th>Details</th>
</tr>
<tr>
  <td><strong>Virtual environment (<code>venv</code> / <code>virtualenv</code>)</strong></td>
  <td><strong>Incompatible without</strong></td>
  <td>OmniBOR requires a virtual environment for Python analysis. Installing packages system-wide pollutes the SBOM with unrelated system packages. <strong>Always use a venv.</strong></td>
</tr>
<tr>
  <td><strong>Pinned dependencies (<code>requirements.txt</code> with <code>==</code>)</strong></td>
  <td><strong>Incompatible without</strong></td>
  <td>Reproducible SBOMs require pinned versions. <code>pip freeze > requirements.txt</code> produces exact pins. Unpinned dependencies (e.g., <code>requests>=2.0</code>) produce non-deterministic SBOMs.</td>
</tr>
<tr>
  <td><strong><code>pyproject.toml</code> with build system declaration</strong></td>
  <td><strong>Compatible</strong></td>
  <td>Modern Python projects using <code>pyproject.toml</code> with <code>[build-system]</code> are fully supported. OmniBOR reads the declared dependencies from the metadata.</td>
</tr>
<tr>
  <td><strong>Lock file (<code>poetry.lock</code>, <code>Pipfile.lock</code>, <code>uv.lock</code>)</strong></td>
  <td><strong>Compatible</strong></td>
  <td>Lock files provide exact dependency resolution and hashes — ideal for SBOM generation. These are preferred over plain <code>requirements.txt</code>.</td>
</tr>
<tr>
  <td><strong>Packages with C extensions (<code>numpy</code>, <code>cryptography</code>, etc.)</strong></td>
  <td><strong>Requires review</strong></td>
  <td>When pip compiles C extensions from source (sdist), the C compilation is invisible to pip metadata. To capture C extension provenance, OmniBOR can optionally wrap <code>pip install</code> with strace or set <code>CC=</code> during installation.</td>
</tr>
<tr>
  <td><strong>Pre-built wheels (<code>.whl</code>)</strong></td>
  <td><strong>Compatible</strong></td>
  <td>Most pip installs use pre-built wheels. The wheel's <code>RECORD</code> file contains SHA-256 hashes of all installed files. No compilation occurs — metadata is sufficient.</td>
</tr>
<tr>
  <td><strong>Vendored dependencies (e.g., <code>pip._vendor</code>)</strong></td>
  <td><strong>Requires review</strong></td>
  <td>Some Python packages vendor their dependencies internally (e.g., pip vendors <code>requests</code>, <code>urllib3</code>, etc.). These vendored packages do not appear in <code>pip freeze</code> output. OmniBOR must scan <code>dist-info/RECORD</code> to detect vendored modules.</td>
</tr>
<tr>
  <td><strong>Conda environments</strong></td>
  <td><strong>Requires review</strong></td>
  <td>Conda packages use a different metadata format (<code>conda-meta/</code> instead of <code>dist-info/</code>). OmniBOR's initial Python support targets pip-installed packages only. Conda support would require a separate metadata parser.</td>
</tr>
<tr>
  <td><strong><code>setup.py</code> (legacy build system)</strong></td>
  <td><strong>Compatible</strong></td>
  <td>Legacy <code>setup.py</code>-based builds are supported — pip still generates <code>dist-info/</code> metadata after installation.</td>
</tr>
<tr>
  <td><strong><code>uv</code> package manager</strong></td>
  <td><strong>Requires review</strong></td>
  <td><code>uv</code> is a fast Python package manager written in Rust. It generates <code>dist-info/</code> and <code>RECORD</code> files compatible with pip's format, so OmniBOR's metadata-based analysis works. However, <code>uv</code> uses its own lock file (<code>uv.lock</code>) instead of <code>requirements.txt</code>. OmniBOR must parse <code>uv.lock</code> for direct vs. transitive classification. <code>uv pip freeze</code> output is identical to pip's.</td>
</tr>
<tr>
  <td><strong>PDM with PEP 582 (<code>__pypackages__/</code>)</strong></td>
  <td><strong>Requires review</strong></td>
  <td>PDM can install packages to <code>__pypackages__/</code> instead of a venv. The <code>dist-info/</code> metadata structure is the same, but the path is different. OmniBOR must accept a configurable packages directory rather than assuming <code>.venv/lib/</code>.</td>
</tr>
<tr>
  <td><strong>Cython (<code>.pyx</code> → C → <code>.so</code>)</strong></td>
  <td><strong>Requires review</strong></td>
  <td>Cython compiles <code>.pyx</code> files to C code, then compiles the C to a shared library. This is a two-stage compilation: (1) <code>cython *.pyx → *.c</code>, (2) <code>gcc *.c → *.so</code>. Neither stage is visible to pip metadata. Full provenance requires strace during <code>pip install</code> to capture both the Cython and GCC invocations.</td>
</tr>
<tr>
  <td><strong>Docker container as virtual environment</strong></td>
  <td><strong>Compatible</strong></td>
  <td>When building Python projects in Docker, the container itself provides isolation — a venv inside Docker is redundant. <code>pip install --no-cache-dir -r requirements.txt</code> in a Dockerfile works. OmniBOR can read <code>dist-info/</code> metadata from the container's <code>site-packages/</code> directory without requiring a venv.</td>
</tr>
<tr>
  <td><strong>Monorepo with multiple Python packages</strong></td>
  <td><strong>Requires review</strong></td>
  <td>Monorepos may have multiple <code>pyproject.toml</code> files, one per package, with inter-package dependencies (<code>pkg-a</code> depends on <code>pkg-b</code>, both in the same repo). Each package must be installed and analyzed separately, or the venv must contain all packages and OmniBOR must attribute files to the correct package using <code>dist-info/RECORD</code>.</td>
</tr>
<tr>
  <td><strong>Private PyPI index</strong></td>
  <td><strong>Requires review</strong></td>
  <td>Teams using <code>--index-url https://internal.corp/pypi</code> may have packages with the same name as public packages but different content (typosquatting risk). OmniBOR records the PURL as <code>pkg:pypi/&lt;name&gt;@&lt;version&gt;</code> regardless of source index. The SBOM should annotate the source index when a private registry is used.</td>
</tr>
</table>

#### Common Python pitfalls

1. **No `requirements.txt` or lock file** — Without pinned dependencies,
   the SBOM is non-reproducible. Different runs may install different
   versions. Always pin with `pip freeze > requirements.txt` or use a
   lock file.

2. **System Python (no venv)** — Without a virtual environment, `pip freeze`
   lists every system-installed package, not just project dependencies.
   The SBOM will contain hundreds of irrelevant packages.

3. **`pip install -e .` (editable installs)** — Editable installs create
   symlinks instead of copying files. The `RECORD` file may be
   incomplete or absent. For SBOM generation, use non-editable installs:
   `pip install .`

4. **Namespace packages (implicit)** — Python 3 supports implicit namespace
   packages (no `__init__.py`). Static import analysis
   (`bomsh_pylib.py`) can miss these. Metadata-based analysis is
   unaffected.

5. **Direct vs. transitive dependencies** — `pip freeze` lists all
   installed packages without distinguishing direct from transitive.
   Use `pipdeptree --json` or parse `requirements.txt` /
   `pyproject.toml` `[project.dependencies]` to identify direct
   dependencies. OmniBOR marks transitive dependencies accordingly.

6. **Conda and pip packages mixed in the same environment** — Some
   teams install packages via both conda and pip in the same env.
   `pip freeze` only shows pip-installed packages. Conda packages
   appear in `conda list` with metadata under `conda-meta/`, not
   `dist-info/`. A complete SBOM requires reading both metadata stores.

7. **`uv` lock file is not `requirements.txt`** — If the team uses `uv`,
   the pinned dependencies are in `uv.lock` (TOML format), not
   `requirements.txt`. Using `uv pip compile` to generate a
   `requirements.txt` is the recommended bridge until OmniBOR natively
   parses `uv.lock`.

8. **C extensions compiled during `pip install` have no RECORD hashes** —
   The `RECORD` file contains hashes for pre-built `.so` files in wheels,
   but when pip compiles C extensions from source (sdist), the compiled
   `.so` is added to `RECORD` with an empty hash field. OmniBOR must
   detect these empty hash entries and flag them as requiring build-time
   tracing for full provenance.

#### Example: future Python project

```yaml
my-python-app:
  url: https://github.com/org/my-python-app.git
  branch: v1.0.0
  language: python
  build_steps:
    - python3 -m venv .venv
    - .venv/bin/pip install --no-cache-dir -r requirements.txt
    - .venv/bin/pip install --no-cache-dir .
  output_binaries:
    - .venv/bin/my-app     # entry point script
```

---

<a id="b6-cross-language-concerns"></a>

### B.6 Cross-Language Concerns

These apply to all languages.

#### B.6.1 Build reproducibility

OmniBOR generates one SBOM per build. If builds are non-reproducible
(different outputs from the same inputs), successive SBOMs will differ.
Teams should ensure:

- **Pinned dependency versions** — Lock files (`go.sum`, `Cargo.lock`,
  `Pipfile.lock`, `pom.xml` with exact versions)
- **Deterministic build flags** — No timestamps in binaries, no random
  UUIDs embedded at build time
- **Pinned toolchain versions** — Compiler version changes alter binary
  output and SBOM content

#### B.6.2 CI/CD integration

When integrating OmniBOR into CI/CD, the build pipeline must:

1. **Not modify the build command itself** — OmniBOR wraps the build; it
   does not replace it. The same `make`, `go build`, `cargo build`,
   `mvn package` command is used.

2. **Allow environment variable injection** — `CC=`, `RUSTC_WRAPPER`,
   and `-toolexec` are injected via environment variables or command-line
   flags. The CI pipeline must allow these to be set.

3. **Provide access to build metadata** — Lock files, `go.mod`, `pom.xml`,
   `Cargo.toml` must be available at analysis time (not `.gitignore`'d).

4. **Run release builds** — Debug builds produce different SBOMs.
   The CI pipeline should use the same build configuration as
   production releases.

#### B.6.3 Docker / container builds

If your project builds inside a Docker container:

- **Multi-stage builds** — OmniBOR can instrument the build stage. The
  wrapper tools must be available in the build stage container.
- **`COPY --from`** — Artifacts copied between stages lose their build
  provenance. OmniBOR should run in the stage where compilation occurs.
- **Scratch / distroless final images** — These don't affect OmniBOR.
  The SBOM is generated from the build stage, not the runtime image.

#### B.6.4 Quick-reference: what to check before onboarding

| Language | #1 Check | #2 Check | #3 Check | #4 Red Flag |
|----------|----------|----------|----------|------------|
| **C/C++** | Build respects `CC=`/`CXX=`? | No hardcoded compiler paths? | Release flags (`-O2`, no `-g`)? | Uses Bazel, Nix, Yocto, or ccache? |
| **Go** | Can tolerate `-a` (full rebuild)? | `-trimpath` + `-ldflags="-s -w"`? | `go.sum` committed? | Uses Bazel `rules_go` or CGo with vendored C? |
| **Rust** | `--release` flag present? | `Cargo.lock` committed? | `build.rs` compiles C code? | Uses sccache (`RUSTC_WRAPPER` conflict)? |
| **Java** | `--no-daemon` for Gradle? | `-DskipTests` / `-x test`? | Private repos accessible? | Uses GraalVM native-image or Ant? |
| **Python** | Uses venv (or Docker)? | Dependencies pinned? | C extensions present? | Uses conda, uv, or private PyPI? |

---

<a id="b7-build-systems-that-break-all-assumptions"></a>

### B.7 Build Systems That Break All Assumptions

The interception mechanisms in B.1–B.5 assume the build system delegates
to a discoverable toolchain via standard interfaces (`CC=`, `-toolexec`,
`RUSTC_WRAPPER`, strace). A class of build systems **deliberately prevents**
this by design — they are hermetic, managing their own toolchains and
ignoring host environment variables.

#### Why this matters

If a pilot engineering team uses any of these systems, **none of the
sidecar wrapper strategies work**. Discovering this after starting the
pilot would be a critical failure. This section exists to ensure teams
are screened before onboarding.

#### B.7.1 Hermetic Build Systems

These systems download, manage, and invoke their own toolchains. External
`CC=` or `RUSTC_WRAPPER` settings are ignored.

<table>
<tr>
  <th style="min-width:180px">Build System</th>
  <th style="min-width:80px">Languages</th>
  <th>Why It Breaks Wrappers</th>
  <th>Mitigation</th>
</tr>
<tr>
  <td><strong>Bazel</strong> (Google)</td>
  <td>C/C++, Go, Rust, Java, Python</td>
  <td>Bazel resolves compilers via <code>cc_toolchain</code> / <code>rules_go</code> / <code>rules_rust</code> / <code>rules_java</code>. It ignores <code>CC=</code>, does not use <code>go build</code>, does not use <code>cargo</code>, and does not use <code>mvn</code>. Toolchains may be downloaded at build time from a remote cache. There is no <code>-toolexec</code> equivalent in Bazel.</td>
  <td><strong>Option A:</strong> <code>bomtrace3</code> (ptrace) — works because Bazel still calls real compilers via <code>execve</code>, which ptrace intercepts regardless of how the compiler was discovered. Overhead: 20–400% depending on language.<br/><br/><strong>Option B:</strong> Bazel's <code>--action_env</code> can inject <code>CC=</code> into the sandbox environment for C/C++ actions, but this is fragile and not supported for Go/Rust rules.<br/><br/><strong>Option C:</strong> Parse Bazel's build event protocol (BEP) or action graph (<code>bazel aquery</code>) to extract input/output file mappings post-build. This is the cleanest long-term approach but requires a new <code>BazelStrategy</code> class.</td>
</tr>
<tr>
  <td><strong>Buck2</strong> (Meta)</td>
  <td>C/C++, Go, Rust, Java, Python</td>
  <td>Similar to Bazel. Buck2 uses TARGETS files and manages toolchains via <code>toolchain()</code> rules. Ignores <code>CC=</code>.</td>
  <td>Same as Bazel: <code>bomtrace3</code> ptrace is the only universal fallback. Buck2's <code>--build-report</code> can provide action-level input/output data.</td>
</tr>
<tr>
  <td><strong>Pants</strong> (Toolchain)</td>
  <td>Python, Go, Java</td>
  <td>Pants manages its own toolchains and runs builds in a sandbox. Ignores host env vars for compiler resolution.</td>
  <td><code>bomtrace3</code> ptrace, or Pants' built-in dependency inference (<code>pants dependencies ::</code>) for Python/Java.</td>
</tr>
<tr>
  <td><strong>Nix / Guix</strong></td>
  <td>All</td>
  <td>Nix resolves every tool from the Nix store (<code>/nix/store/&lt;hash&gt;-gcc-12/bin/gcc</code>). The build is hermetic — <code>CC=</code> is set by the Nix derivation, not by the user. External env vars are stripped by the build sandbox.</td>
  <td><strong>Option A:</strong> <code>bomtrace3</code> ptrace (works inside Nix builds).<br/><br/><strong>Option B:</strong> Create a Nix overlay that wraps the compiler derivation with OmniBOR's wrapper. This is the Nix-idiomatic approach but requires Nix expertise.<br/><br/><strong>Option C:</strong> Use <code>nix log</code> + <code>nix derivation show</code> to extract the build graph post-facto (dependency info only, no file hashes).</td>
</tr>
<tr>
  <td><strong>Yocto / BitBake</strong></td>
  <td>C/C++ (primarily)</td>
  <td>BitBake recipes set <code>CC</code>/<code>CXX</code>/<code>LD</code>/<code>AR</code> per recipe from the Yocto SDK. These override any external values. The cross-compilation sysroot is managed by Yocto.</td>
  <td><strong>Option A:</strong> <code>bomtrace3</code> ptrace wrapping the entire BitBake build. Very high overhead and produces a massive raw logfile (all recipes, not just the target).<br/><br/><strong>Option B:</strong> Custom <code>bbclass</code> that prepends OmniBOR wrappers to the recipe's toolchain variables. This is the correct approach but requires Yocto expertise. Example: <code>inherit omnibor</code> in the recipe, where <code>omnibor.bbclass</code> wraps <code>${CC}</code> with <code>/opt/omnibor/gcc-wrapper</code>.</td>
</tr>
</table>

#### B.7.2 Build Orchestrators That Spawn Sub-Builds

These systems do not replace the compiler but run builds in contexts
where environment variables may not propagate:

<table>
<tr>
  <th style="min-width:180px">System</th>
  <th>Risk</th>
  <th>Mitigation</th>
</tr>
<tr>
  <td><strong>Docker multi-stage builds</strong></td>
  <td><code>CC=</code> set in the host does not propagate into <code>docker build</code>. Each <code>RUN</code> in the Dockerfile is an independent shell with no inherited env vars unless <code>ARG</code>/<code>ENV</code> is declared.</td>
  <td>Add <code>ARG CC=/opt/omnibor/gcc-wrapper</code> and <code>ENV CC=${CC}</code> to the build stage of the Dockerfile. The OmniBOR tools must be <code>COPY</code>'d into the build stage.</td>
</tr>
<tr>
  <td><strong>CMake <code>ExternalProject_Add</code></strong></td>
  <td>Downloads and builds external dependencies in a sub-process. <code>CC=</code> may not propagate.</td>
  <td>Pass <code>CMAKE_ARGS -DCMAKE_C_COMPILER=${CC}</code> in the <code>ExternalProject_Add</code> call. Requires modifying the project's CMakeLists.txt or using a CMake toolchain file.</td>
</tr>
<tr>
  <td><strong>Conan package manager</strong></td>
  <td>Conan manages its own compiler profiles and may override <code>CC=</code> when building dependencies from source.</td>
  <td>Configure OmniBOR wrapper paths in the Conan profile (<code>[settings]</code> and <code>[env]</code> sections). Or use <code>bomtrace3</code> to wrap the entire <code>conan install --build=missing</code> invocation.</td>
</tr>
<tr>
  <td><strong>Gradle <code>buildSrc</code> / convention plugins</strong></td>
  <td><code>buildSrc</code> compiles Kotlin/Groovy code before the main build. If strace starts after <code>buildSrc</code> compilation, those files are missed.</td>
  <td>Wrap the entire <code>./gradlew</code> invocation (not just the build task). <code>buildSrc</code> compilation occurs during the configuration phase, which strace captures.</td>
</tr>
<tr>
  <td><strong>Makefile with recursive <code>$(MAKE)</code></strong></td>
  <td>Recursive Make propagates <code>CC=</code> by default (GNU Make exports it). However, if a sub-Makefile explicitly sets <code>CC := gcc</code> (override), the wrapper is bypassed for that sub-directory.</td>
  <td>Audit sub-Makefiles for <code>CC :=</code> (simple assignment) vs. <code>CC ?=</code> (conditional) vs. <code>CC +=</code> (append). Only <code>:=</code> overrides the parent's <code>CC=</code>. Also check for <code>unexport CC</code> which prevents propagation.</td>
</tr>
</table>

#### B.7.3 Wrapper Stacking Conflicts

When teams already use compiler wrappers, OmniBOR's wrapper conflicts.
This table summarizes the conflict and resolution for each known wrapper:

| Existing Wrapper | Mechanism | OmniBOR Conflict | Resolution |
|-----------------|-----------|-----------------|------------|
| **ccache** | `CC="ccache gcc"` or symlink | Displaces ccache | OmniBOR wrapper must chain: call ccache, which calls gcc. OmniBOR must be the **outermost** wrapper. |
| **distcc** | `CC="distcc gcc"` | Displaces distcc | Same chaining approach. OmniBOR records inputs locally; distcc distributes compilation to remote hosts. |
| **sccache** | `RUSTC_WRAPPER=sccache` | Only one `RUSTC_WRAPPER` allowed | Use `RUSTC_WORKSPACE_WRAPPER` for OmniBOR + `RUSTC_WRAPPER=sccache` (Cargo supports both). |
| **Coverity** | `cov-build --dir cov make` | `cov-build` wraps the entire build; conflicts with `CC=` | Run Coverity and OmniBOR in separate builds, or use `bomtrace3` ptrace (intercepts below Coverity's level). |
| **scan-build** (Clang) | `scan-build make` | `scan-build` sets `CC=` to its own analyzer wrapper | Same as Coverity — separate builds or ptrace. |
| **LLVM `compile_commands.json`** | `CMAKE_EXPORT_COMPILE_COMMANDS=ON` | No conflict | CMake generates `compile_commands.json` alongside the build — does not interfere with `CC=`. |

#### B.7.4 The Universal Fallback: ptrace (bomtrace3)

When wrapper-based interception fails — hermetic builds, wrapper
conflicts, non-standard toolchains — **bomtrace3 ptrace is the universal
fallback**. It operates at the kernel level, below all build system
abstractions:

```
Application Level:     Bazel → rules_go → go compile
                       ↓ (invisible to wrappers)
Kernel Level:          execve("/path/to/compile", ...) ← bomtrace3 sees this
```

**Trade-off:** ptrace has 20–400% overhead vs. 3–15% for wrappers. But
it **always works** regardless of how the compiler was invoked. The
sidecar architecture must support falling back to bomtrace3 per-project
when wrappers are not viable.

**Config-driven fallback:**

```yaml
# Project that uses Bazel — fall back to ptrace
my-bazel-project:
  language: c-cpp
  build_system: bazel        # Informs OmniBOR that CC= won't work
  interception: ptrace       # Override: use bomtrace3 instead of wrappers
  build_steps:
    - bazel build //...
```

#### B.7.5 Pre-Onboarding Questionnaire

Before onboarding any engineering team, ask these questions to identify
which interception strategy applies:

| # | Question | If "Yes" |
|---|----------|----------|
| 1 | Do you use **Bazel, Buck2, or Pants**? | Wrapper strategies will not work. Use ptrace or build-system-native action graph. |
| 2 | Do you use **Nix or Guix** for builds? | Wrapper strategies will not work without a Nix overlay. Use ptrace. |
| 3 | Do you use **Yocto/BitBake** for embedded builds? | Requires a custom `bbclass`. Use ptrace as interim. |
| 4 | Do you already use **ccache, distcc, or sccache**? | OmniBOR wrapper must support chaining. Test wrapper stacking before pilot. |
| 5 | Does your build use a **toolchain from an internal artifact repo** (Artifactory, Nexus)? | Wrapper must discover compiler on PATH, not assume `/usr/bin/gcc`. Test with the actual toolchain. |
| 6 | Does your Makefile/CMakeLists.txt **hardcode compiler paths**? | Audit for `/usr/bin/gcc`, `set(CMAKE_C_COMPILER ...)`, `$(shell which gcc)`. |
| 7 | Do you **cross-compile** to a different target architecture? | Wrapper's `REAL_CC` must point to the cross-compiler. Test `readelf -d` instead of `ldd` for binary analysis. |
| 8 | Does your Java project use **GraalVM native-image**? | Java strace+javap pipeline does not apply. Requires C/C++ pipeline for the native binary. |
| 9 | Does your Go project have significant **CGo** code? | `-toolexec` only wraps Go tools, not the C compiler. Must also set `CC=` for complete coverage. |
| 10 | Does your Rust project use **`cross`** for cross-compilation? | `RUSTC_WRAPPER` does not propagate into the cross container. Wrapper must be installed inside the cross image. |

---

*Document created: 2026-05-01 08:50 HST*
*Appendix A added: 2026-05-01 09:10 HST — source code audit*
*Appendix B added: 2026-05-01 09:04 HST — build rules impact guide*
*Appendix B revised: 2026-05-01 09:37 HST — adversarial build scenarios, B.7 added*
*Reviewed: 2026-05-01 09:59 HST — devil's advocate fixes: overhead estimates corrected, Rust cache statement corrected, Go overhead baseline clarified, strace 97% contextualized, Maven dep:tree accuracy caveat, Python overhead clarified*

---

<a id="10-appendix-c-reference-document-updates"></a>

## 10. Appendix C: Reference Document Updates

The following reference documents informed this refactoring plan. They
contain the original analysis but are not the implementation authority.
All design and implementation changes are tracked in
[sidecar-implementation-design.md](sidecar-implementation-design.md).

The reference documents should be updated for consistency once the
implementation design is finalized:

- **[sidecar-vs-cleanroom-analysis.md](sidecar-vs-cleanroom-analysis.md)**
  — Update Section 5 wrapper list to include `as-wrapper` and
  `ranlib-wrapper`. Add `RUSTC_WORKSPACE_WRAPPER` as an option for Rust.
  Revise eBPF assessment from "cleanest long-term path" to
  "deprioritized in favor of language-native wrappers."
- **[cross-language-build-timing-improvements.md](cross-language-build-timing-improvements.md)**
  — Update wrapper language recommendations (Go wrapper in Go, Rust
  wrapper in Rust, C/C++ wrapper in C/Go). Correct overhead estimates
  per devil's advocate review.
- **[cross-platform-applicability.md](cross-platform-applicability.md)**
  — Add ARM64 support via wrappers as an explicit platform benefit.
- **[platform-support.md](../architecture/platform-support.md)**
  — Document that wrapper-based sidecar architecture unlocks ARM64
  support for C/C++, Go, and Rust without bomtrace3 porting.
- **[enterprise-integration-guide.md](../guides/enterprise-integration-guide.md)**
  — Update to reflect three deployment models (sidecar, standalone
  default, standalone custom). Add containers.cisco.com as the
  publication target.
