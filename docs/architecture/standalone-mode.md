# Standalone Mode

Standalone mode uses ptrace-based build interception via
`bomtrace3` (C/C++) and `bomtrace2` (Go/Rust) to trace every
compiler and linker invocation during a build. It produces the most
thorough provenance data but requires Linux `SYS_PTRACE` capability.

**Sidecar mode is the baseline for enterprise deployment.** Standalone
mode is retained for two purposes:

1. **Golden file generation** — standalone produces the ground-truth
   SPDX used as regression baselines for all modes and OSes
2. **Isolated build environments** — engineering teams whose build
   systems are black-box or lack internet/intranet access

---

## How It Works

1. The target project is cloned into the Docker container
2. The build command is wrapped with `bomtrace3` (or `bomtrace2`),
   which attaches via `ptrace` to every child process
3. `bomsh_hook.c` intercepts `execve()` syscalls and records every
   input→output file relationship with SHA-256 gitoid hashes
4. `bomsh_create_bom.py` converts the raw logfile into an Artifact
   Dependency Graph (ADG) treedb
5. The SPDX generation pipeline reads the treedb and produces
   per-binary SPDX 2.3 documents

## Per-Language Tracers

| Language | Tracer | Mechanism |
|----------|--------|-----------|
| C/C++ | `bomtrace3` | Patched strace v6.11; intercepts `execve()` for gcc/g++/ld |
| Go | `bomtrace2` + `bomtrace_go.conf` | ptrace wrapper; `openat` syscall tracing |
| Rust | `bomtrace2` | ptrace wrapper around `cargo build --release` |
| Java | strace + `bomsh_create_bom_java.py` | strace `openat` tracing + JAR inspection via `javap` |

## Container Requirements

| Requirement | Value |
|-------------|-------|
| Docker capability | `--cap-add SYS_PTRACE` |
| Security option | `--security-opt seccomp:unconfined` |
| Architecture | `linux/amd64` (x86_64 only — ptrace register decoding) |
| Docker image target | `omnibor-env:standalone` |

## Running Standalone Mode

```bash
docker compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo <repo> --skip-clone
```

The container runs both Phase 1 (build interception) and Phase 2
(SPDX generation) in a single invocation. There is no phase split
for standalone mode.

## Limitations

- **x86_64 only** — `bomtrace3` uses architecture-specific ptrace
  register structures (`<sys/reg.h>`)
- **Not compatible with QEMU emulation** — fails on Apple Silicon
  Docker Desktop (see [QEMU issue](../issues/bomtrace3-qemu-apple-silicon.md))
- **Requires privileged container** — `SYS_PTRACE` + `seccomp:unconfined`
  are often prohibited in enterprise Kubernetes/OpenShift environments
- **Build overhead** — 15–60% build time increase depending on project
  size and file count

## When to Use Standalone vs. Sidecar

| Criterion | Standalone | Sidecar |
|-----------|-----------|---------|
| Enterprise CI/CD | No (`SYS_PTRACE` blocked) | **Yes** |
| Golden file baseline | **Yes** (authoritative) | No |
| Phase isolation (separate hosts) | No | **Yes** |
| Black-box builds without internet | **Yes** | No |
| RHEL / Alpine / hardened kernels | Limited | **Yes** |

---

For the sidecar architecture, see
[Sidecar Phase Isolation Infrastructure](../features/phase-isolation/sidecar-phase-isolation-infrastructure.md).
