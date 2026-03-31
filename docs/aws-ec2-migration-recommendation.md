# AWS EC2 Migration Recommendation

**Date:** February 20, 2026
**Purpose:** Replace DigitalOcean droplet with AWS EC2 for faster OmniBOR build analysis

## Current DigitalOcean Droplet

| Spec | Value |
|---|---|
| **Instance** | s-1vcpu-2gb (Droplet) |
| **Name** | omnibor-build-ubuntu-s-1vcpu-2gb-sfo3-01 |
| **vCPUs** | 1 (shared, "DO-Regular") |
| **RAM** | 2 GB (1.9 GiB usable) |
| **Disk** | 50 GB SSD |
| **Region** | SFO3 (San Francisco) |
| **OS** | Ubuntu 22.04 LTS x64 |
| **Disk used** | 7.6 GB / 49 GB (16%) |
| **Swap** | None |
| **Monthly cost** | ~$12/mo |

### Pain Points

- **1 vCPU** — FFmpeg build with bomtrace3 at `-j1` takes 30+ minutes; cannot parallelize
- **2 GB RAM** — tight for large builds; no swap configured
- **Shared CPU** — noisy-neighbor throttling on shared infrastructure

## Terminology Mapping

| DigitalOcean | AWS |
|---|---|
| Droplet | EC2 Instance |
| Region (sfo3) | Region (us-west-2) + Availability Zone |
| Snapshot | AMI (Amazon Machine Image) |
| Floating IP | Elastic IP |
| Volume | EBS Volume |

## Recommended AWS EC2 Instances

### Option 1: t3.large (Budget)

| Spec | Value |
|---|---|
| **vCPUs** | 2 (burstable) |
| **RAM** | 8 GB |
| **Disk** | 50 GB gp3 EBS |
| **CPU type** | Intel Xeon (burstable with CPU credits) |
| **On-demand** | ~$60/mo |
| **Spot pricing** | ~$18-20/mo |
| **Build speedup** | ~2-3x vs current |

### Option 2: c6i.xlarge (Recommended — Performance)

| Spec | Value |
|---|---|
| **vCPUs** | 4 (dedicated, not shared) |
| **RAM** | 8 GB |
| **Disk** | 50 GB gp3 EBS (3000 IOPS baseline) |
| **CPU type** | Intel Xeon 3rd gen Ice Lake (dedicated) |
| **On-demand** | ~$124/mo |
| **Spot pricing** | ~$37-50/mo |
| **1-year reserved** | ~$50-60/mo |
| **Build speedup** | ~6-8x vs current |

## Side-by-Side Comparison

| Spec | Current DO | t3.large | c6i.xlarge |
|---|---|---|---|
| vCPUs | 1 (shared) | 2 (burstable) | 4 (dedicated) |
| RAM | 2 GB | 8 GB | 8 GB |
| Disk | 50 GB SSD | 50 GB gp3 | 50 GB gp3 |
| CPU quality | Shared | Burstable | Dedicated |
| `make -jN` | `-j1` only | `-j2` | `-j4` |
| FFmpeg build | ~30+ min | ~12-15 min | ~5 min |
| Redis build | ~2 min | ~1 min | ~30 sec |
| On-demand $/mo | $12 | $60 | $124 |
| Spot $/mo | N/A | $18-20 | $37-50 |
| Pay-per-use (4h/day, 20 days) | $12 (flat) | ~$5 | ~$14 |

## Recommendation

**c6i.xlarge** with stop/start usage pattern:

- 4 dedicated vCPUs allows `make -j4` with bomtrace3
- 8 GB RAM provides comfortable headroom for Docker + large builds
- At ~$0.17/hr on-demand, running 4 hours/day x 20 days = **~$14/mo** — comparable to the current DO droplet but 6-8x faster
- Spot instances bring this down further to ~$0.05-0.07/hr
- If Cisco has Reserved Instances or Savings Plans, cost drops to $50-60/mo flat

**Region:** us-west-2 (Oregon) — closest AWS region to current SFO3

## Linux OS Requirements

OmniBOR build interception relies on **bomtrace3**, a patched version of strace.
This imposes hard constraints on the host and container operating system.

### Architecture: x86_64 Only

- bomtrace3 includes `<sys/reg.h>`, a header that **only exists on x86** Linux.
- The compiled binary is `ELF 64-bit LSB pie executable, x86-64, for GNU/Linux 3.2.0`.
- **ARM64/aarch64 is not supported.** On Apple Silicon Macs, Docker Desktop uses QEMU
  emulation to run the x86_64 container (functional but ~2x slower).
- The EC2 instance **must** be an x86_64 instance type (c6i, t3, m6i, etc.),
  **not** a Graviton/ARM instance (c7g, t4g, m7g, etc.).

### Container Base Image

| Requirement | Value |
|---|---|
| **Current image** | `ubuntu:22.04` (Jammy Jellyfish) |
| **Tested distros** | Ubuntu 18.04, 20.04, 21.04, 22.04; Debian 10, 11 |
| **Bomsh upstream default** | Debian 11 (Bullseye) |
| **Minimum glibc** | 2.17+ (GNU/Linux 3.2.0 ABI target) |
| **Minimum kernel** | 3.2.0 (any modern distro satisfies this) |

Ubuntu 22.04 LTS is recommended because:
- Long-term support until April 2027 (ESM until 2032)
- Matches our current DigitalOcean droplet and Dockerfile
- Ships glibc 2.35, GCC 11.4, and strace 5.16 — all well above minimums
- `dpkg` metadata resolution in `collect_metadata.py` and `collect_dynamic_libs.py`
  depends on Debian/Ubuntu package management (dpkg, dpkg-query)

### Host OS (Outside Docker)

The EC2 host runs Docker and does not need to match the container OS. However:
- **Recommended:** Ubuntu 22.04 LTS AMI (`ami-0aff18ec83b712f05` in us-west-2)
- Any Linux with Docker Engine 20.10+ and `--security-opt seccomp:unconfined`
  plus `SYS_PTRACE` capability will work (required for strace inside the container)
- The `docker-compose.yml` enforces `platform: linux/amd64` to prevent
  accidental ARM builds

### What Does NOT Work

| Platform | Issue |
|---|---|
| **macOS native** | No strace, no `<sys/reg.h>` — bomtrace3 cannot build or run |
| **Windows native** | Same — strace is Linux-only |
| **ARM64 EC2 (Graviton)** | `<sys/reg.h>` missing, bomtrace3 fails to compile |
| **Alpine Linux container** | musl libc lacks full `<sys/reg.h>` support; untested |

## Migration Steps

1. Launch **Ubuntu 22.04 LTS x86_64** AMI on c6i.xlarge in us-west-2
2. Attach 50 GB gp3 EBS volume
3. Allocate an Elastic IP (persists across stop/start)
4. Install Docker, clone omnibor-analysis repo, build Docker image
5. Update local `~/.ssh/config` to point `omnibor-build` at the new Elastic IP
6. Run test analysis (redis) to verify
7. Decommission DigitalOcean droplet
