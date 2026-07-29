---
description: DigitalOcean droplet template for Bisbom build host
---

# DigitalOcean Droplet — Build Host Profile

Copy this file to `../active-profile.md` and fill in your values.

## Host Details

| Field | Value |
|-------|-------|
| **Provider** | DigitalOcean |
| **Droplet Name** | `<YOUR_DROPLET_NAME>` |
| **SSH alias** | `bisbom-build` |
| **IP** | `<YOUR_DROPLET_IP>` |
| **Droplet ID** | `<YOUR_DROPLET_ID>` |
| **Region** | `<REGION>` (e.g. SFO3, NYC1) |
| **Size** | `s-1vcpu-2gb` (minimum) or `s-2vcpu-4gb` (recommended) |
| **OS** | Ubuntu 22.04 x86_64 |
| **Repo path on host** | `/root/bisbom-gen` |

## SSH Config

Add to `~/.ssh/config`:

```
Host bisbom-build
    HostName <YOUR_DROPLET_IP>
    User root
    IdentityFile ~/.ssh/<YOUR_KEY>
```

## CLI Tool

- **doctl** — DigitalOcean CLI
- Install: `brew install doctl` (macOS) or `snap install doctl` (Linux)
- Authenticate: `doctl auth init`

### Power Management

```bash
# Check status
doctl compute droplet list --format ID,Name,Status,PublicIPv4

# Power on
doctl compute droplet-action power-on <YOUR_DROPLET_ID> --wait

# Power off (preserves disk, still charges for storage)
doctl compute droplet-action power-off <YOUR_DROPLET_ID> --wait
```

### Cost

| State | Cost (s-1vcpu-2gb) |
|-------|------|
| Running | ~$0.018/hr (~$12/mo) |
| Stopped (disk preserved) | ~$0.007/hr (~$5/mo) |
| Destroyed | $0 |

## Creating a New Droplet

```bash
doctl compute droplet create bisbom-build \
  --image ubuntu-22-04-x64 \
  --size s-2vcpu-4gb \
  --region sfo3 \
  --ssh-keys <YOUR_SSH_KEY_FINGERPRINT> \
  --wait
```

Then install Docker:

```bash
ssh bisbom-build "curl -fsSL https://get.docker.com | sh"
```

## Running Analysis

```bash
# Ensure latest code
ssh bisbom-build "cd /root/bisbom-gen && git pull origin main"

# Run analysis
ssh bisbom-build "cd /root/bisbom-gen && docker-compose -f docker/docker-compose.yml run --rm bisbom-env python3 /workspace/app/analyze.py --repo <REPO_NAME>"

# Enter container interactively
ssh bisbom-build "cd /root/bisbom-gen && docker-compose -f docker/docker-compose.yml run --rm bisbom-env bash"

# Rebuild Docker image
ssh bisbom-build "cd /root/bisbom-gen && docker-compose -f docker/docker-compose.yml build"
```

## Syncing Results

```bash
# Download results to local machine
rsync -avz bisbom-build:/root/bisbom-gen/output/ output/
rsync -avz bisbom-build:/root/bisbom-gen/docs/ docs/

# Upload code to droplet
rsync -avz --exclude='.venv' --exclude='output' --exclude='repos' --exclude='.git' \
  ./ bisbom-build:/root/bisbom-gen/
```
