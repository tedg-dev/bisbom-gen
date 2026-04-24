# Sidecar vs Clean-Room Mode — Architecture Discussion

| | |
|---|---|
| **Date** | 2026-04-15 |
| **Participants** | Ted G. (architect), Cascade AI |
| **Triggered by** | Demo rehearsal review of `omnibor-container-portable.drawio` |
| **Status** | Analysis complete, diagram and architecture updates pending |

---

## Table of Contents

1. [The Question](#1-the-question)
2. [The Problem](#2-the-problem)
3. [Current Architecture Analysis](#3-current-architecture-analysis)
4. [The Architectural Gap](#4-the-architectural-gap)
5. [Sidecar Mode via Compiler Wrappers](#5-sidecar-mode-via-compiler-wrappers)
6. [Per-Language Sidecar Feasibility](#6-per-language-sidecar-feasibility)
7. [Conclusions and Next Steps](#7-conclusions-and-next-steps)

---

<a id="1-the-question"></a>

## 1. The Question

**Ted's observation** while reviewing `docs/architecture/omnibor-container-portable.drawio`
during demo rehearsal:

> Looking at the portable container diagram, I see a question that users will
> ask. If "Your Build Machine" and "Your CI/CD Pipeline" are different entities
> than the "Portable" OmniBOR Analysis Container, how do the OmniBOR Build
> Toolchains that are INSIDE the container use the same build toolchains Your
> Build Machine uses? This seems like a glaring problem.

The diagram shows the container with its own "Build Toolchains" box (gcc 11,
Go 1.26, Rust stable, OpenJDK 17/21) and then "Deploy alongside: Your Build
Machine / Your CI/CD Pipeline" — implying they are separate systems. The
natural question from any architect: if the container has gcc 11 but my build
machine uses gcc 13, is the SBOM valid for my production binary?

---

<a id="2-the-problem"></a>

## 2. The Problem

**Ted's follow-up** after Cascade described the current architecture as
"clean-room mode":

> I always thought sidecar mode — container's bomtrace3 intercepts your
> existing build by mounting your build tree and wrapping your existing make,
> with toolchains coming from the host — was the way our entire project has
> been run. Did you make architectural changes that only allow clean-room mode
> and don't always do sidecar mode?

And further:

> I'm disappointed that you would not have questioned this architecture, only
> because to me it is obvious that if our intent is to INTERCEPT a repo build,
> we MUST be building with whatever build toolchain that repo build uses by
> default. NOT impose our own idea of what versions the build toolchain is
> using. We CANNOT claim that we are truly intercepting any and all repo build
> calls if we are not actually using the build environment the repo(s) are
> natively built in.

### The core principle

bomtrace3's value proposition is **transparent interception** — it observes a
build without changing it. If the container substitutes the build toolchain,
it is no longer intercepting. It is rebuilding in a controlled environment and
producing an SBOM for *its own* build, not the repo's actual production
build. The checksums differ, the linked libraries differ, and the binary is a
different binary entirely.

---

<a id="3-current-architecture-analysis"></a>

## 3. Current Architecture Analysis

### What the Dockerfile actually does

`docker/Dockerfile` installs **everything** into a single image:

| Category | What's installed |
|----------|-----------------|
| **C/C++ toolchains** | gcc 11, g++ 11, clang 14, make, cmake, autotools |
| **Go SDK** | Go 1.26.0 at `/usr/local/go/` |
| **Rust toolchain** | stable via rustup at `/root/.cargo/` |
| **Java JDKs** | OpenJDK 17 + 21, Maven 3.6 + 3.9 |
| **OmniBOR tools** | bomtrace3, bomtrace2, bomsh scripts |
| **Analysis pipeline** | Python scripts, Syft, spdx-tools |
| **Library deps** | libssl-dev, zlib1g-dev, libx264-dev, etc. |

### What docker-compose.yml does

```yaml
volumes:
  - ../repos:/workspace/repos      # cloned source code
  - ../output:/workspace/output    # generated artifacts
  - ../app:/workspace/app          # pipeline scripts
  - ../docs:/workspace/docs        # documentation
```

Source repos are cloned **inside** the container into the mounted `repos/`
volume. Builds run using the **container's** toolchains. The SBOM reflects
what the container built, not what any external build machine would produce.

### Classification

This is **standalone mode / clean-room mode**: the container provides a
reproducible reference environment. It is NOT sidecar mode — there is no
mechanism to use the host's native toolchains through the container.

---

<a id="4-the-architectural-gap"></a>

## 4. The Architectural Gap

The diagram says "deploy alongside your build machine" and "bomtrace3 wraps
your existing make/build," but the architecture does not deliver on that
promise. The deployment targets in the diagram describe sidecar mode, but the
container implements clean-room mode.

**For open-source analysis** (the current demo use case), clean-room mode is
acceptable — there is no canonical "native" build environment for a GitHub
project. We provide a reasonable reference environment.

**For production/enterprise adoption**, clean-room mode is insufficient.
Customers need SBOMs that match their actual CI/CD output — same compiler
version, same linked libraries, same binary. The SBOM must describe what
ships to customers, not what our container produces.

---

<a id="5-sidecar-mode-via-compiler-wrappers"></a>

## 5. Sidecar Mode via Compiler Wrappers

**Ted's question:**

> If bomtrace3 is a ptrace-based interceptor, are there any options in the
> performance optimization proposal that would allow us to always run in
> sidecar mode? (We would of course have our own default Build Toolchains
> that we would use, which could be overridden/replaced with "native" build
> system CI/CD build toolchains.)

### Why ptrace forces co-location

bomtrace3 must be the **parent process** of the build. It calls `fork()` +
`PTRACE_TRACEME` + `execve(make)`. This means bomtrace3 and the compiler
must run in the same PID namespace. That is why the container ended up with
all toolchains included — bomtrace3 needs to see the gcc it traces.

### Strategy 6: CC= Compiler Wrapper (from performance proposal)

From `docs/architecture/omnibor-performance-optimization-proposal.md`,
Strategy 6 replaces ptrace entirely:

```bash
# Instead of: bomtrace3 make -j$(nproc)
CC=/opt/bomsh/gcc-wrapper \
CXX=/opt/bomsh/g++-wrapper \
AR=/opt/bomsh/ar-wrapper \
LD=/opt/bomsh/ld-wrapper \
make -j$(nproc)
```

Each wrapper:

1. Records `argv` (the full command line)
2. Invokes the **real compiler**: `exec /usr/bin/gcc "$@"` — whatever is on PATH
3. After the compiler exits: hashes the output file
4. Writes a raw logfile record
5. For `.h` dependencies: reads the `-MD` dependency output (same as bomtrace3)

**The wrapper does not care what gcc version it calls.** It does not need
ptrace. It does not need to be the parent process. It interposes on the
compiler invocation and calls through to whatever the native toolchain is.

### What the container provides in sidecar mode

Only the interception and analysis tools:

- Wrapper scripts (`gcc-wrapper`, `g++-wrapper`, `ar-wrapper`, `ld-wrapper`)
- `bomsh_create_bom.py` (ADG generation)
- Analysis pipeline (Python scripts for SPDX generation)
- Default toolchains as a convenience fallback (overridden in sidecar mode)

### Strategy 7: eBPF (most transparent)

eBPF does not even require `CC=` override. A BPF tracepoint on
`sys_enter_execve` observes ALL process spawns from kernel space. The build
command is completely unmodified. Requires Linux 5.x+ and is higher
complexity, but provides the ultimate transparent sidecar — zero build
modification.

---

<a id="6-per-language-sidecar-feasibility"></a>

## 6. Per-Language Sidecar Feasibility

### C/C++ — CC= wrapper

| Aspect | Assessment |
|--------|-----------|
| **Mechanism** | `CC=/opt/bomsh/gcc-wrapper make -j$(nproc)` |
| **Sidecar ready** | **Yes** — wrapper calls whatever gcc/clang is on the native PATH |
| **Caveat** | Build system must respect `CC=`/`CXX=`/`AR=`/`LD=`. autoconf and cmake do natively. Hard-coded compiler paths (rare) will not work. |

### Go — Hard-coded tool paths, no CC= equivalent

| Aspect | Assessment |
|--------|-----------|
| **Current mechanism** | bomtrace2 traces `openat` syscalls; `bomsh_hook2.py` watches Go's internal tools at hard-coded path `/usr/local/go/pkg/tool/linux_amd64/compile` and `link` |
| **Sidecar problem** | The hook script has **hard-coded paths** to Go's internal compiler tools. Native Go install could be at `/usr/lib/go/`, `/snap/go/`, `/home/user/.goenv/`, etc. |
| **Sidecar ready** | **Partial** — `bomtrace_go.conf` `-w` flag must be updated to match the native Go install path |
| **No CC= equivalent** | Go has no environment variable to override its internal compiler. `go build` invokes `compile` and `link` internally with no override mechanism. |
| **Build cache issue** | `go build -a` is required to bypass Go's build cache so bomtrace2 sees all compilations. This **alters native build behavior** — in a real CI/CD sidecar, `-a` forces a full rebuild every time, adding significant overhead. |
| **Best path** | Strategy 7 (eBPF) — tracepoint on `execve` sees all process spawns regardless of Go install location; no `-a` needed if compile/link tools are detected dynamically. |

### Rust — RUSTC_WRAPPER (native support)

| Aspect | Assessment |
|--------|-----------|
| **Mechanism** | `RUSTC_WRAPPER=/opt/bomsh/rustc-wrapper cargo build --release` |
| **Sidecar ready** | **Yes** — Rust natively supports compiler wrappers via `RUSTC_WRAPPER` env var (this is how `sccache` works). |
| **How it works** | Cargo calls `$RUSTC_WRAPPER rustc <args>` for every compilation unit. The wrapper records args, calls the real rustc, then hashes outputs. |
| **Caveat** | Minimal — rustc/cargo location varies per user (`~/.cargo/bin/`, `~/.rustup/toolchains/`), but `RUSTC_WRAPPER` handles this natively since cargo resolves the real rustc path. |

### Java — strace openat (already sidecar-friendly)

| Aspect | Assessment |
|--------|-----------|
| **Current mechanism** | `strace -f -e trace=openat` wraps `mvn package`. Post-build, `bomsh_create_bom_java.py` scans the workspace to match `.java` → `.class` → `.jar`. |
| **Sidecar ready** | **Yes** — strace wraps the native `mvn`/`gradle` command. Whatever JDK and Maven version is installed natively gets used. strace observes `openat` syscalls without modifying the build. |
| **Caveat 1** | strace requires `SYS_PTRACE` capability. In Kubernetes/container sidecars, this must be granted. Some CI/CD environments (GitHub Actions runners) already have it. |
| **Caveat 2** | Gradle uses a long-running daemon (`--daemon`). `--no-daemon` is needed for clean strace capture, which alters native build behavior. |
| **No CC= needed** | Java does not compile via `CC=`. The `javac` invocation is buried inside Maven/Gradle plugin internals. The strace `openat` approach is the correct one for Java — observe file I/O rather than interposing on the compiler. |

### Summary

| Language | Sidecar Mechanism | Native Override | Ready? | Key Blocker |
|----------|------------------|-----------------|--------|-------------|
| **C/C++** | CC= wrapper | `CC=`, `CXX=`, `AR=`, `LD=` | **Yes** | Hard-coded compiler paths (rare) |
| **Go** | bomtrace2 + conf | None | **Partial** | Hard-coded Go tool paths; `-a` forces full rebuild |
| **Rust** | `RUSTC_WRAPPER` | `RUSTC_WRAPPER` env var | **Yes** | Minimal |
| **Java** | strace `openat` | N/A (wraps native mvn) | **Yes** | SYS_PTRACE required; Gradle needs `--no-daemon` |

---

<a id="7-conclusions-and-next-steps"></a>

## 7. Conclusions and Next Steps

### Architecture classification

| Mode | Description | Current State |
|------|-------------|--------------|
| **Standalone mode** (clean-room) | Container provides all toolchains + interception tools. Builds happen inside the container. SBOM reflects the container's build. | **This is what we have today.** |
| **Sidecar mode** (true interception) | Container provides only interception tools + analysis pipeline. Builds use the native environment's toolchains. SBOM reflects the production build. | **Not yet implemented. Requires Strategy 6 (CC= wrappers) or Strategy 7 (eBPF).** |

### What the diagram should show

The portable container diagram (`omnibor-container-portable.drawio`) should be
updated to clearly distinguish:

1. **OmniBOR Interception Tools** — the unique value (bomtrace3, bomsh, wrappers)
2. **Default Build Toolchains** — convenience defaults, explicitly labeled as
   overridable by native toolchains in sidecar mode
3. **Deployment targets** should describe both modes with honest labels

### Immediate actions

1. **Demo script** — add a verbal answer for when architects ask the
   toolchain question (they will)
2. **Diagram update** — separate "interception tools" from "default
   toolchains" and label the dual-mode architecture
3. **Roadmap** — Strategy 6 (CC= wrappers for C/C++, `RUSTC_WRAPPER` for
   Rust) should be prioritized as the path to true sidecar mode
4. **Go** remains the hardest language — eBPF is the cleanest long-term path

### For the demo

The current clean-room approach is acceptable for analyzing open-source
projects where there is no canonical native build environment. The demo
should acknowledge this:

> "For this demo we're using our analysis container which provides a known,
> reproducible build environment. For production CI/CD integration, the
> architecture supports sidecar mode where our interception tools wrap your
> native build toolchain — we provide compiler wrappers that call through to
> your existing gcc, and the SBOM reflects exactly what your pipeline produces."

---

*Document created: 2026-04-15 09:03 HST*
