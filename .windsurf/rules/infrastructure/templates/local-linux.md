---
description: Local Linux / WSL2 / bare metal template for OmniBOR build host
---

# Local Linux — Build Host Profile

Copy this file to `../active-profile.md` and fill in your values.
Use this template if Docker runs directly on your local machine (native Linux,
WSL2 on Windows, or a local VM).

## Host Details

| Field | Value |
|-------|-------|
| **Provider** | Local |
| **SSH alias** | _(none — runs locally)_ |
| **OS** | Ubuntu 22.04 x86_64 |
| **Repo path** | `<YOUR_CLONE_PATH>` (e.g. `/home/user/omnibor-analysis`) |

## Prerequisites

- Linux x86_64 (native or WSL2 — NOT ARM64, NOT Rosetta)
- Docker 20.10+ with docker-compose
- At least 2 GB free RAM, 10 GB free disk

### Verify Architecture

```bash
uname -m
# Must show: x86_64
```

### Install Docker (if not installed)

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for group change
```

## Power Management

No cloud provider CLI needed. Docker runs locally.

```bash
# Docker is managed via systemd
sudo systemctl start docker
sudo systemctl stop docker
```

### Cost

| State | Cost |
|-------|------|
| All states | $0 (local hardware) |

## Running Analysis

```bash
# Run analysis (from repo root)
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo <REPO_NAME>

# Enter container interactively
docker-compose -f docker/docker-compose.yml run --rm omnibor-env bash

# Rebuild Docker image
docker-compose -f docker/docker-compose.yml build
```

## Syncing Results

No sync needed — output is written directly to your local `output/` and `docs/`
directories via Docker volume mounts.

## WSL2 Notes

If using WSL2 on Windows:

- Install Docker Desktop with WSL2 backend, OR install Docker Engine inside WSL2
- Clone the repo inside WSL2 filesystem (not `/mnt/c/`) for performance
- Access HTML visualizations from Windows browser at `\\wsl$\Ubuntu\path\to\output\`
