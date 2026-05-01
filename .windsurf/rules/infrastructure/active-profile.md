---
description: Active infrastructure profile — tedg's AWS EC2 instance
---

# Active Build Host — AWS EC2

## Host Details

| Field | Value |
|-------|-------|
| **Provider** | AWS EC2 |
| **Instance Name** | `omnibor-build` |
| **SSH alias** | `omnibor-build` |
| **IP** | `54.215.15.253` (Elastic IP) |
| **Instance ID** | `i-02ef4bf118d6bae90` |
| **Region** | `us-west-1` |
| **Instance Type** | `c6i.xlarge` (4 vCPU, 8 GB RAM) |
| **OS** | Ubuntu 22.04 x86_64 |
| **AMI** | `ami-02ff48e800d3550ab` |
| **EBS** | 50 GB gp3 (3000 IOPS) |
| **Security Group** | `sg-068fd31b70796c6c3` |
| **AWS Profile** | `ted-admin` |
| **Repo path on host** | `/home/ubuntu/omnibor-analysis` |

## SSH Config

```
Host omnibor-build
    HostName 54.215.15.253
    User ubuntu
    IdentityFile ~/.ssh/id_ed25519
    StrictHostKeyChecking accept-new
    Port 443
```

> **Note:** Cisco VPN blocks port 22 to AWS IPs. SSH runs on port 443 instead.
> Port 22 also works when off-VPN.

## Power Management

Requires valid AWS session (`duo-sso` re-auth every 1 hour).

```bash
# Check status
aws ec2 describe-instances --profile ted-admin --instance-ids i-02ef4bf118d6bae90 --query 'Reservations[].Instances[].{State:State.Name,IP:PublicIpAddress}' --output table --no-cli-pager

# Power on
aws ec2 start-instances --profile ted-admin --instance-ids i-02ef4bf118d6bae90 --no-cli-pager

# Power off
aws ec2 stop-instances --profile ted-admin --instance-ids i-02ef4bf118d6bae90 --no-cli-pager
```

## Running Analysis

```bash
ssh omnibor-build "cd /home/ubuntu/omnibor-analysis && git pull origin main"
ssh omnibor-build "cd /home/ubuntu/omnibor-analysis && docker-compose -f docker/docker-compose.yml run --rm omnibor-env python3 /workspace/app/analyze.py --repo <REPO_NAME>"
```

## Syncing Results

```bash
# Download results to local machine (all generated artifacts are under output/)
rsync -avz omnibor-build:/home/ubuntu/omnibor-analysis/output/ output/
```

## Cost

| State | Cost |
|-------|------|
| Running (c6i.xlarge) | ~$0.170/hr |
| Stopped (EBS only) | ~$0.003/hr (~$4/mo for 50GB gp3) |
| Elastic IP (while stopped) | ~$0.005/hr (~$3.60/mo) |
| Destroyed | $0 |

## Previous Host (DigitalOcean — kept for reference)

| Field | Value |
|-------|-------|
| **Droplet Name** | `omnibor-build-ubuntu-s-1vcpu-2gb-sfo3-01` |
| **IP** | `137.184.178.186` |
| **Droplet ID** | `551297940` |
| **Power off** | `doctl compute droplet-action power-off 551297940 --wait` |
