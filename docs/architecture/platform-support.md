# Platform Support

<a id="overview"></a>

## Overview

**Sidecar mode is the only supported execution mode** — no `SYS_PTRACE`
required, runs on any Docker host. The deprecated **standalone mode**
(initial ptrace-based implementation, retained only for a rare ~1% embedded
corner case) requires `SYS_PTRACE` and targets Linux x86_64; it is
documented here for that corner case only, not as a deployment option.

<a id="host-requirements"></a>

## Execution Modes

| Mode | Container Image | `SYS_PTRACE` | Mechanism | Primary Use |
|------|----------------|:------------:|-----------|-------------|
| **Sidecar** (only supported mode) | `omnibor-env:sidecar` | No | Language-specific strategies (dep:tree, `-toolexec`, `RUSTC_WRAPPER`, `LD_PRELOAD`) | Enterprise CI/CD |
| **Standalone** (deprecated) | `omnibor-env:standalone` | Yes | `bomtrace3`/`bomtrace2` ptrace-based tracing | ~1% embedded corner case only |

## Host Requirements

### Sidecar Mode (recommended)

| | |
|---|---|
| **Supported host OS** | Linux, macOS, Windows (via Docker Desktop) |
| **Container runtime** | Docker 20.10+ (standard capabilities — no `SYS_PTRACE` needed) |
| **Container architecture** | `linux/amd64` (x86_64) |
| **Distro images** | Ubuntu 22.04, RHEL 9 (Rocky Linux), Alpine 3.19 |

Sidecar mode works in standard Docker and Kubernetes environments without
privileged capabilities.

### Standalone Mode (deprecated)

| | |
|---|---|
| **Supported host OS** | Linux, macOS, Windows (via Docker Desktop) |
| **Container runtime** | Docker 20.10+ with `SYS_PTRACE` capability and `seccomp:unconfined` |
| **Container architecture** | `linux/amd64` (x86_64) |

- **Linux x86_64 hosts** — native execution, best performance
- **macOS / Windows hosts** — Docker Desktop runs a Linux VM transparently; the container works as on native Linux
- **Apple Silicon (ARM64) hosts** — Docker Desktop can run x86_64 containers via Rosetta 2 / QEMU emulation, but ptrace-based interception under emulation is **unreliable** (see [Architecture Constraint](#architecture-constraint))

<a id="architecture-constraint"></a>

## Architecture Constraint: x86_64

`bomtrace3` intercepts builds using the Linux `ptrace` syscall with **x86_64-specific register access**:

- Uses `<sys/reg.h>` with register offsets (`ORIG_RAX`, `RDI`, `RSI`, etc.)
- Reads syscall arguments directly from x86_64 CPU registers via `PTRACE_PEEKUSER`
- This register layout is hardcoded and does not exist on ARM64

This means:

- A simple container rebuild for `linux/arm64` is **not sufficient**
- Supporting ARM64 (e.g., AWS Graviton, Apple Silicon native) requires **code changes to bomtrace3** to use ARM64 register structures (`struct user_pt_regs` instead of `<sys/reg.h>`)
- Running the x86_64 container under QEMU/Rosetta emulation may produce **incorrect ptrace results** because the emulation layer does not faithfully translate low-level register access

<a id="what-works"></a>

## What Works Today

| Host | Architecture | Docker | Status |
|------|-------------|--------|--------|
| Ubuntu 22.04 | x86_64 | Native | **Fully supported** (production) |
| Ubuntu 18.04–24.04 | x86_64 | Native | Supported |
| Debian 10–12 | x86_64 | Native | Supported |
| Any Linux | x86_64 | Docker 20.10+ | Supported |
| macOS (Intel) | x86_64 | Docker Desktop | Supported |
| macOS (Apple Silicon) | ARM64 | Docker Desktop + Rosetta | **Not recommended** — ptrace unreliable under emulation |
| Windows 10/11 | x86_64 | Docker Desktop (WSL2) | Expected to work (not tested in production) |

<a id="what-does-not-work"></a>

## What Does Not Work

| Platform | Standalone | Sidecar | Reason |
|----------|:----------:|:-------:|--------|
| macOS native (no Docker) | No | No | Linux kernel required |
| Windows native (no Docker) | No | No | Linux kernel required |
| ARM64 / Graviton (native) | No | No | `bomtrace3` register access is x86_64-only; sidecar not yet ported |
| Alpine Linux (musl) | No | **Yes** | Standalone: bomtrace3 assumes glibc. Sidecar: works via `apk` resolver |

<a id="future-arm64"></a>

## Future: ARM64 Support

Enabling native ARM64 standalone container support requires:

1. **Port `bomtrace3` register access** — replace `<sys/reg.h>` x86_64 offsets with `struct user_pt_regs` and ARM64 register names
2. **Update syscall number mapping** — ARM64 uses different syscall numbers than x86_64
3. **Test ptrace behavior** — ARM64 ptrace has subtle differences in syscall entry/exit handling
4. **Multi-arch Docker build** — add `linux/arm64` platform to `docker buildx`

This is a **code-level change to `bomtrace3`** in its upstream source, not a configuration or build change in bisbom-gen.

<a id="diagram-language"></a>

## Diagram and Documentation Language

When referencing platform support in diagrams and documentation:

- **Diagrams**: Use "deploy on any Docker host (x86_64)" rather than "deploy on any Linux x86_64 host" — the host OS is not restricted to Linux
- **Requirements sections**: State "Docker runtime on x86_64 architecture" as the requirement
- **Footnotes**: When space permits, note "ARM64 support requires bomtrace3 porting"
