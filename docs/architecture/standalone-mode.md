# Standalone Mode (Deprecated)

> **Deprecated — not a deployment option.** Standalone mode was the initial
> ptrace-based implementation and the earliest bisbom-gen testing.
> **Sidecar is the only supported
> mode.** Standalone must **not** be used or offered as an option; the sole
> remaining possibility is a rare (~1%) embedded-systems corner case. This
> page is retained as historical/technical reference for that corner case
> only.

Standalone mode uses ptrace-based build interception via
`bomtrace3` (C/C++) and `bomtrace2` (Go/Rust) to trace every
compiler and linker invocation during a build. It produces thorough
provenance data but requires Linux `SYS_PTRACE` capability, which
enterprise Kubernetes/OpenShift environments typically prohibit.

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

## Status: Deprecated — use Sidecar

Sidecar is the only supported mode for every scenario — enterprise CI/CD,
the golden-file baseline, phase isolation, and RHEL/Alpine/hardened
kernels. Standalone is **not** recommended for any of these. Its only
conceivable remaining use is a rare (~1%) embedded-systems corner case
where sidecar interception is genuinely unavailable; even there it is a
last resort, not a supported deployment.

---

For the sidecar architecture, see
[Sidecar Phase Isolation Infrastructure](../sidecar/infrastructure.md).
