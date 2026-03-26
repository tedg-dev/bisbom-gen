---
description: Rules for Docker container usage in this project
---

# Docker Rules

## Platform Requirements

- **Bomtrace3 requires native Linux x86_64** — it uses ptrace via `<sys/reg.h>`
- It does NOT work on: macOS, Windows, ARM64/Graviton, Alpine (musl), or under QEMU/Rosetta
- The container must have `SYS_PTRACE` capability and `seccomp:unconfined` security option
- Supported hosts: any x86_64 Linux with Docker 20.10+ (bare metal, VM, or cloud instance)
- Supported base images: Ubuntu 18.04–22.04, Debian 10–11

## Running the Container

Enter the container interactively:

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env bash
```

Run analysis directly:

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo <REPO_NAME>
```

Rebuild the image (after Dockerfile changes):

```bash
docker-compose -f docker/docker-compose.yml build
```

## Remote Host Usage

If running on a remote Linux host, your SSH alias, IP, repo path, and sync
commands are defined in your **infrastructure profile**:

```
.windsurf/rules/infrastructure/active-profile.md
```

See `.windsurf/rules/infrastructure/README.md` for how to set up a profile.
Templates are provided for DigitalOcean, AWS EC2, and local Linux.

General pattern for remote execution:

```bash
ssh <SSH_ALIAS> "cd <REPO_PATH> && docker-compose -f docker/docker-compose.yml run --rm omnibor-env python3 /workspace/app/analyze.py --repo <REPO_NAME>"
```

General pattern for syncing results:

```bash
rsync -avz <SSH_ALIAS>:<REPO_PATH>/output/ output/
rsync -avz <SSH_ALIAS>:<REPO_PATH>/docs/ docs/
```

## Volume Mounts

The following directories are mounted into the container (defined in docker-compose.yml):

| Host Path | Container Path | Purpose |
|-----------|---------------|---------|
| `repos/` | `/workspace/repos` | Cloned source repositories |
| `output/` | `/workspace/output` | Generated ADG, SPDX, binary scan artifacts |
| `app/` | `/workspace/app` | Orchestration scripts and config |
| `docs/` | `/workspace/docs` | Timestamped markdown reports |
| `scripts/` | `/workspace/scripts` | Helper scripts |
| `tests/` | `/workspace/tests` | Test suite |

## Dockerfile Maintenance

- When adding a new target repo, add its build dependencies to the Dockerfile
- Bomtrace2 and bomtrace3 are compiled from source (patched strace) during image build
- The bomsh scripts and binaries are at `/opt/bomsh/` inside the container
- Syft is installed at `/usr/local/bin/syft`
- After changing the Dockerfile, rebuild the image before running analysis
