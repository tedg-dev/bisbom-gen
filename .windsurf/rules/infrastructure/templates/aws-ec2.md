---
description: AWS EC2 instance template for OmniBOR build host
---

# AWS EC2 — Build Host Profile

Copy this file to `../active-profile.md` and fill in your values.

## Host Details

| Field | Value |
|-------|-------|
| **Provider** | AWS EC2 |
| **Instance ID** | `i-<YOUR_INSTANCE_ID>` |
| **SSH alias** | `omnibor-build` |
| **IP** | `<YOUR_ELASTIC_IP or PUBLIC_IP>` |
| **Region** | `<REGION>` (e.g. us-west-2) |
| **Instance Type** | `t3.medium` (recommended) |
| **AMI** | Ubuntu 22.04 x86_64 |
| **Repo path on host** | `/home/ubuntu/omnibor-analysis` |

## Recommended Instance Types

| Instance | vCPU | RAM | Cost/hr | Notes |
|----------|------|-----|---------|-------|
| `t3.small` | 2 | 2 GB | ~$0.021 | Minimum viable |
| `t3.medium` | 2 | 4 GB | ~$0.042 | Recommended for most repos |
| `t3.large` | 2 | 8 GB | ~$0.083 | FFmpeg or large repos |
| `c6i.large` | 2 | 4 GB | ~$0.085 | Compute-optimized, faster builds |

## SSH Config

Add to `~/.ssh/config`:

```
Host omnibor-build
    HostName <YOUR_IP>
    User ubuntu
    IdentityFile ~/.ssh/<YOUR_KEY>.pem
```

## CLI Tool

- **aws** — AWS CLI v2
- Install: `brew install awscli` (macOS) or see https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html
- Configure: `aws configure` (set region, access key, secret key)

### Power Management

```bash
# Check status
aws ec2 describe-instances --instance-ids i-<YOUR_INSTANCE_ID> \
  --query 'Reservations[].Instances[].{ID:InstanceId,State:State.Name,IP:PublicIpAddress}' \
  --output table

# Start instance
aws ec2 start-instances --instance-ids i-<YOUR_INSTANCE_ID>

# Stop instance (preserves EBS, charges for storage only)
aws ec2 stop-instances --instance-ids i-<YOUR_INSTANCE_ID>

# Terminate (destroy — deletes everything)
aws ec2 terminate-instances --instance-ids i-<YOUR_INSTANCE_ID>
```

### Cost

| State | Cost (t3.medium) |
|-------|------|
| Running | ~$0.042/hr (~$30/mo) |
| Stopped (EBS only) | ~$0.003/hr (~$2.40/mo for 30 GB gp3) |
| Terminated | $0 |

**Tip:** Use a Spot Instance for up to 70% savings if you can tolerate interruptions:

```bash
aws ec2 run-instances \
  --instance-market-options '{"MarketType":"spot","SpotOptions":{"SpotInstanceType":"persistent","InstanceInterruptionBehavior":"stop"}}' \
  ...
```

## Creating a New Instance

```bash
# Launch
aws ec2 run-instances \
  --image-id ami-0735c191cf914754d \
  --instance-type t3.medium \
  --key-name <YOUR_KEY_NAME> \
  --security-group-ids <YOUR_SG_ID> \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=omnibor-build}]' \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":30,"VolumeType":"gp3"}}]'

# Allocate Elastic IP (optional, for stable IP across stop/start)
aws ec2 allocate-address --domain vpc
aws ec2 associate-address --instance-id i-<ID> --allocation-id eipalloc-<ID>
```

Then install Docker:

```bash
ssh omnibor-build "curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker ubuntu"
# Log out and back in for group change
```

## Security Group (Minimum)

| Direction | Port | Source | Purpose |
|-----------|------|--------|---------|
| Inbound | 22 | Your IP/32 | SSH |
| Outbound | All | 0.0.0.0/0 | apt, git, Docker pulls |

## Running Analysis

```bash
# Ensure latest code
ssh omnibor-build "cd ~/omnibor-analysis && git pull origin main"

# Run analysis
ssh omnibor-build "cd ~/omnibor-analysis && docker-compose -f docker/docker-compose.yml run --rm omnibor-env python3 /workspace/app/analyze.py --repo <REPO_NAME>"

# Enter container interactively
ssh omnibor-build "cd ~/omnibor-analysis && docker-compose -f docker/docker-compose.yml run --rm omnibor-env bash"

# Rebuild Docker image
ssh omnibor-build "cd ~/omnibor-analysis && docker-compose -f docker/docker-compose.yml build"
```

## Syncing Results

```bash
# Download results to local machine
rsync -avz omnibor-build:~/omnibor-analysis/output/ output/
rsync -avz omnibor-build:~/omnibor-analysis/docs/ docs/

# Upload code to instance
rsync -avz --exclude='.venv' --exclude='output' --exclude='repos' --exclude='.git' \
  ./ omnibor-build:~/omnibor-analysis/
```
