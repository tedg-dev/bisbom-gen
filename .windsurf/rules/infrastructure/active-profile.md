---
description: Active infrastructure profile — kak's on-prem Linux host
---

# Active Build Host — On-Prem Linux (corona210)

## Host Details

| Field | Value |
|-------|-------|
| **Provider** | Local (SSH-accessible on-prem) |
| **Hostname** | `corona210.cisco.com` |
| **SSH alias** | `omnibor-build` |
| **User** | `kak` |
| **OS** | CentOS 7 x86_64 |
| **Docker** | v24.0.5 + Compose v2.20.2 |
| **Repo path on host** | `/home/kak/omnibor-analysis` |

## SSH Config

```
Host omnibor-build
    HostName corona210.cisco.com
    User kak
```

## Power Management

Always-on host — no start/stop needed.

## Running Analysis

```bash
ssh omnibor-build "cd ~/omnibor-analysis && docker compose -f docker/docker-compose.yml run --rm omnibor-env python3 /workspace/app/analyze.py --repo <REPO_NAME>"
```

## Syncing Results

```bash
rsync -avz omnibor-build:~/omnibor-analysis/output/ output/
rsync -avz omnibor-build:~/omnibor-analysis/docs/ docs/
```

## Cost

| State | Cost |
|-------|------|
| Running | $0 (on-prem) |
