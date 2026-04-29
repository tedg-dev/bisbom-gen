# AWS EC2 Setup Guide — Existing Environment

**Purpose:** Step-by-step instructions for developers who already have an AWS
account and infrastructure (VPCs, subnets, security groups, IAM roles) and want
to add an OmniBOR analysis build host to their existing environment.

**Audience:** Developers and platform engineers with an established AWS presence
who need to integrate an OmniBOR build host alongside existing workloads.

**Complementary guide:** If you are starting from scratch with no AWS
infrastructure, see the [Greenfield AWS Setup Guide](aws-setup-guide.md) which
uses Terraform to provision everything from zero.

> **Time estimate:** ~15 minutes if your environment already meets the
> requirements; ~30 minutes if you need to launch a new EC2 instance.

---

## Table of Contents

- [Hard Requirements](#hard-requirements)
- [Step 1: Assess Your Existing Environment](#step-1-assess-your-existing-environment)
- [Step 2: Determine Your Scenario](#step-2-determine-your-scenario)
- [Scenario A: Reuse an Existing EC2 Instance](#scenario-a-reuse-an-existing-ec2-instance)
- [Scenario B: Launch a New EC2 in an Existing VPC](#scenario-b-launch-a-new-ec2-in-an-existing-vpc)
- [Scenario C: Use an Existing Non-AWS Linux Server](#scenario-c-use-an-existing-non-aws-linux-server)
- [Step 3: Install Docker and Build the Container](#step-3-install-docker-and-build-the-container)
- [Step 4: Validate the Environment](#step-4-validate-the-environment)
- [Step 5: Configure Your Infrastructure Profile](#step-5-configure-your-infrastructure-profile)
- [Step 6: Run a Test Analysis](#step-6-run-a-test-analysis)
- [Networking Requirements](#networking-requirements)
- [Corporate and Enterprise Considerations](#corporate-and-enterprise-considerations)
- [IAM Permissions Reference](#iam-permissions-reference)
- [Instance Sizing Guide](#instance-sizing-guide)
- [Daily Workflow](#daily-workflow)
- [Troubleshooting](#troubleshooting)
- [Decision Flowchart](#decision-flowchart)

---

<a id="hard-requirements"></a>

## Hard Requirements

OmniBOR build interception uses `bomtrace3`, a ptrace-based tool that reads
x86_64 CPU registers directly via `<sys/reg.h>`. This creates **non-negotiable
platform constraints** that cannot be worked around with configuration changes.

| Requirement | Why | Non-Compliant Alternative |
|---|---|---|
| **x86_64 (AMD64) architecture** | `bomtrace3` uses x86_64 register offsets (`ORIG_RAX`, `RDI`, `RSI`) via `PTRACE_PEEKUSER` | ARM64 / Graviton instances (`t4g`, `c7g`, `m7g`, `r7g`) **will not work** |
| **Linux kernel** | `ptrace` syscall interception requires a Linux kernel | macOS, Windows without Docker **will not work** |
| **Docker 20.10+** | Container runtime with `SYS_PTRACE` capability and `seccomp:unconfined` | Podman may work but is untested |
| **glibc-based Linux** | `bomtrace3` and bomsh scripts assume glibc | Alpine Linux (musl) **will not work** |
| **Ubuntu 22.04 LTS** | Tested and verified base image; Dockerfile is built on `ubuntu:22.04` | Other glibc distros (Debian 11+, RHEL 8+, Amazon Linux 2023) likely work but are untested |
| **50 GB disk** (recommended) | Docker image (~8 GB) + cloned repos + build artifacts | 30 GB minimum for single-repo analysis |
| **4 GB RAM** (minimum) | Docker build + compilation workloads | 2 GB will OOM on large repos (FFmpeg, Node.js) |
| **Outbound internet access** | Cloning repos, pulling Docker images, downloading build dependencies | Air-gapped environments require pre-staged images and repos |

> **Critical:** AWS Graviton instances (ARM64) are **architecturally
> incompatible** with `bomtrace3`. This is not a configuration issue — it
> requires code changes to the upstream `omnibor/bomsh` project. See
> [Platform Support](../architecture/platform-support.md) for details.

---

<a id="step-1-assess-your-existing-environment"></a>

## Step 1: Assess Your Existing Environment

Run through this checklist to determine what you already have and what you need.

### 1a. Instance inventory

Check for existing EC2 instances that might be suitable:

```bash
aws ec2 describe-instances \
  --query 'Reservations[].Instances[].{ID:InstanceId,Type:InstanceType,Arch:Architecture,State:State.Name,Name:Tags[?Key==`Name`].Value|[0]}' \
  --output table --no-cli-pager
```

Look for:
- **Architecture** must be `x86_64` (not `arm64`)
- **Instance type** must be an x86_64 family (`t3`, `t2`, `m6i`, `c6i`, `r6i`, etc.)
- **State** should be `running` or `stopped`

### 1b. VPC and subnet inventory

```bash
aws ec2 describe-vpcs \
  --query 'Vpcs[].{ID:VpcId,CIDR:CidrBlock,Name:Tags[?Key==`Name`].Value|[0],Default:IsDefault}' \
  --output table --no-cli-pager
```

```bash
aws ec2 describe-subnets \
  --query 'Subnets[].{ID:SubnetId,VPC:VpcId,AZ:AvailabilityZone,CIDR:CidrBlock,Public:MapPublicIpOnLaunch}' \
  --output table --no-cli-pager
```

### 1c. Security group inventory

```bash
aws ec2 describe-security-groups \
  --query 'SecurityGroups[].{ID:GroupId,Name:GroupName,VPC:VpcId}' \
  --output table --no-cli-pager
```

### 1d. SSH key pairs

```bash
aws ec2 describe-key-pairs \
  --query 'KeyPairs[].{Name:KeyName,Type:KeyType,ID:KeyPairId}' \
  --output table --no-cli-pager
```

### 1e. Record your findings

| Item | Your Value | Status |
|---|---|---|
| AWS region | | |
| Existing x86_64 EC2 available? | Yes / No | |
| VPC ID | | |
| Subnet ID (public or with NAT) | | |
| Security group allowing SSH inbound | | |
| SSH key pair name | | |
| Outbound internet available? | Yes / No | |
| Docker installed on existing instance? | Yes / No / N/A | |

---

<a id="step-2-determine-your-scenario"></a>

## Step 2: Determine Your Scenario

Based on your assessment, follow the appropriate scenario:

| Scenario | You have... | Action |
|---|---|---|
| **[A: Reuse Existing EC2](#scenario-a-reuse-an-existing-ec2-instance)** | An x86_64 EC2 instance with Docker or the ability to install it | Install Docker (if needed), clone repo, build image |
| **[B: New EC2 in Existing VPC](#scenario-b-launch-a-new-ec2-in-an-existing-vpc)** | An AWS account with VPCs/subnets but no suitable instance | Launch a new x86_64 EC2 using your existing networking |
| **[C: Non-AWS Linux Server](#scenario-c-use-an-existing-non-aws-linux-server)** | An on-prem or other-cloud Linux x86_64 server | Install Docker, clone repo, build image |

> **Graviton/ARM64 instances:** If all your existing instances are ARM64,
> you **must** launch a new x86_64 instance (Scenario B). There is no
> workaround for the architecture requirement.

---

<a id="scenario-a-reuse-an-existing-ec2-instance"></a>

## Scenario A: Reuse an Existing EC2 Instance

Use this scenario when you have an x86_64 EC2 instance that you can dedicate
(or share) for OmniBOR analysis.

### Prerequisites checklist

- [ ] Instance architecture is `x86_64` (verify: `uname -m` shows `x86_64`)
- [ ] Instance has at least 4 GB RAM and 30 GB free disk
- [ ] You have SSH access to the instance
- [ ] Instance has outbound internet access (for Docker pulls, git clones)
- [ ] Operating system is Ubuntu 18.04+, Debian 10+, Amazon Linux 2023, or RHEL 8+

### A1. Verify the instance

SSH into your instance and verify the architecture and OS:

```bash
# Must show x86_64
uname -m

# Check OS — Ubuntu 22.04 is ideal
cat /etc/os-release

# Check available disk
df -h /

# Check available RAM
free -h
```

### A2. Verify or install Docker

```bash
# Check if Docker is installed
docker --version

# If not installed — Ubuntu/Debian:
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for group change to take effect
```

For Amazon Linux 2023:

```bash
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

### A3. Install docker-compose

```bash
# Check if docker-compose is available
docker compose version || docker-compose --version

# If not installed — install standalone docker-compose v2:
COMPOSE_VERSION="v2.29.2"
sudo curl -fsSL \
  "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

### A4. Clone and build

```bash
# Clone the repository
git clone https://github.com/tedg-dev/omnibor-analysis.git ~/omnibor-analysis

# Build the Docker image (~15-20 minutes on first build)
cd ~/omnibor-analysis
docker-compose -f docker/docker-compose.yml build
```

> **Private repo?** If git clone fails, push the code from your local machine
> via rsync:
>
> ```bash
> rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '.venv' \
>   --exclude 'output/' --exclude 'repos/' \
>   -e ssh ./ your-ssh-alias:~/omnibor-analysis/
> ```

### A5. Proceed to [Step 3](#step-3-install-docker-and-build-the-container)

Skip to Step 3 to verify Docker configuration, then continue to Step 4 for
validation.

---

<a id="scenario-b-launch-a-new-ec2-in-an-existing-vpc"></a>

## Scenario B: Launch a New EC2 in an Existing VPC

Use this scenario when you have an AWS account with existing networking
infrastructure but need a new EC2 instance for OmniBOR analysis.

### B1. Choose your approach

| Approach | Best for | Effort |
|---|---|---|
| **AWS CLI** (documented below) | One-off instance, minimal tooling | 5 minutes |
| **Terraform** (see [greenfield guide](aws-setup-guide.md)) | Repeatable IaC, team standardization | 15 minutes |
| **AWS Console** | Developers who prefer GUI | 10 minutes |
| **CloudFormation / CDK** | Teams with existing CF/CDK stacks | Varies |

### B2. Identify your existing resources

You need these values from Step 1. Fill them in:

| Resource | Your Value |
|---|---|
| VPC ID | `vpc-` |
| Subnet ID | `subnet-` |
| Security Group ID | `sg-` |
| Key Pair Name | |
| AWS Region | |

### B3. Verify or create a security group

Your security group needs at minimum:

| Direction | Port | Source | Purpose |
|---|---|---|---|
| **Inbound** | 22 | Your IP (`x.x.x.x/32`) or VPN CIDR | SSH access |
| **Outbound** | 443 | `0.0.0.0/0` | HTTPS — Docker Hub, GitHub, package repos |
| **Outbound** | 80 | `0.0.0.0/0` | HTTP — some apt/Maven repos |

If your existing security group already allows SSH inbound and all outbound,
it is sufficient. Otherwise, create a dedicated one:

```bash
# Create a security group in your existing VPC
SG_ID=$(aws ec2 create-security-group \
  --group-name omnibor-build-sg \
  --description "OmniBOR build host — SSH inbound" \
  --vpc-id vpc-YOUR_VPC_ID \
  --query 'GroupId' --output text --no-cli-pager)

# Allow SSH from your IP
MY_IP=$(curl -s https://checkip.amazonaws.com)
aws ec2 authorize-security-group-ingress \
  --group-id "$SG_ID" \
  --protocol tcp --port 22 \
  --cidr "${MY_IP}/32" --no-cli-pager

# Allow all outbound (default for new SGs, but verify)
echo "Security Group created: $SG_ID"
```

### B4. Find the latest Ubuntu 22.04 x86_64 AMI

```bash
AMI_ID=$(aws ec2 describe-images \
  --owners 099720109477 \
  --filters \
    "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" \
    "Name=architecture,Values=x86_64" \
    "Name=state,Values=available" \
  --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' \
  --output text --no-cli-pager)

echo "Latest Ubuntu 22.04 x86_64 AMI: $AMI_ID"
```

### B5. Launch the instance

```bash
INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type c6i.xlarge \
  --key-name YOUR_KEY_NAME \
  --subnet-id subnet-YOUR_SUBNET_ID \
  --security-group-ids sg-YOUR_SG_ID \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":50,"VolumeType":"gp3","Iops":3000}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=omnibor-build}]' \
  --query 'Instances[0].InstanceId' --output text --no-cli-pager)

echo "Instance launched: $INSTANCE_ID"
```

> **Instance type:** Must be an x86_64 family. See
> [Instance Sizing Guide](#instance-sizing-guide) for recommendations.
> Do **not** use `t4g`, `c7g`, `m7g`, or any Graviton type.

### B6. (Optional) Assign an Elastic IP

If your subnet does not auto-assign public IPs, or you want a stable IP:

```bash
# Allocate
EIP_ALLOC=$(aws ec2 allocate-address \
  --domain vpc \
  --query 'AllocationId' --output text --no-cli-pager)

# Associate
aws ec2 associate-address \
  --instance-id "$INSTANCE_ID" \
  --allocation-id "$EIP_ALLOC" --no-cli-pager

# Get the IP
aws ec2 describe-addresses \
  --allocation-ids "$EIP_ALLOC" \
  --query 'Addresses[0].PublicIp' --output text --no-cli-pager
```

### B7. Wait for the instance to be ready

```bash
aws ec2 wait instance-status-ok --instance-ids "$INSTANCE_ID"
echo "Instance is ready"
```

### B8. Get the IP address and configure SSH

```bash
# Get the public IP (or private IP if using VPN/bastion)
IP=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text --no-cli-pager)

echo "Instance IP: $IP"
```

Add to `~/.ssh/config`:

```
Host omnibor-build
    HostName <IP_FROM_ABOVE>
    User ubuntu
    IdentityFile ~/.ssh/<YOUR_KEY>.pem
```

Test the connection:

```bash
ssh omnibor-build "uname -m && cat /etc/os-release | head -2"
```

### B9. Bootstrap the instance

SSH in and install Docker + docker-compose:

```bash
ssh omnibor-build "sudo apt-get update -y && sudo apt-get upgrade -y"
ssh omnibor-build "curl -fsSL https://get.docker.com | sh"
ssh omnibor-build "sudo usermod -aG docker ubuntu"
```

Install docker-compose:

```bash
ssh omnibor-build 'COMPOSE_VERSION="v2.29.2" && \
  sudo curl -fsSL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
  -o /usr/local/bin/docker-compose && \
  sudo chmod +x /usr/local/bin/docker-compose'
```

Install additional tools:

```bash
ssh omnibor-build "sudo apt-get install -y git rsync"
```

> **Note:** Log out and back in (or start a new SSH session) after adding
> the user to the `docker` group.

### B10. Clone the repo and build the Docker image

```bash
ssh omnibor-build "git clone https://github.com/tedg-dev/omnibor-analysis.git ~/omnibor-analysis"
```

If the repo is private, push via rsync from your local machine:

```bash
rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '.venv' \
  --exclude 'output/' --exclude 'repos/' \
  --exclude 'terraform/.terraform/' --exclude 'terraform/terraform.tfstate*' \
  -e ssh ./ omnibor-build:~/omnibor-analysis/
```

Build the Docker image (~15-20 minutes):

```bash
ssh omnibor-build "cd ~/omnibor-analysis && docker-compose -f docker/docker-compose.yml build"
```

---

<a id="scenario-c-use-an-existing-non-aws-linux-server"></a>

## Scenario C: Use an Existing Non-AWS Linux Server

Use this scenario for on-premises servers, other cloud providers (GCP, Azure,
DigitalOcean), or any bare-metal Linux machine.

### Prerequisites

- [ ] Linux x86_64 operating system (`uname -m` shows `x86_64`)
- [ ] Root or sudo access (for Docker installation)
- [ ] 4 GB RAM minimum, 30 GB free disk minimum
- [ ] Outbound internet access (HTTPS to GitHub, Docker Hub, package repos)
- [ ] SSH access from your development machine

### C1. Verify the system

```bash
# Architecture — must be x86_64
uname -m

# OS release
cat /etc/os-release

# Disk space
df -h /

# RAM
free -h
```

### C2. Install Docker

```bash
# Universal Docker install script (Ubuntu, Debian, CentOS, Fedora, RHEL)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in
```

### C3. Install docker-compose

```bash
COMPOSE_VERSION="v2.29.2"
sudo curl -fsSL \
  "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

### C4. Clone, build, validate

```bash
git clone https://github.com/tedg-dev/omnibor-analysis.git ~/omnibor-analysis
cd ~/omnibor-analysis
docker-compose -f docker/docker-compose.yml build
```

Then proceed to [Step 4: Validate](#step-4-validate-the-environment).

---

<a id="step-3-install-docker-and-build-the-container"></a>

## Step 3: Install Docker and Build the Container

If Docker is already installed and verified, skip to Step 4.

### Docker configuration requirements

The `docker-compose.yml` specifies these container requirements:

```yaml
platform: linux/amd64        # Forces x86_64 container
cap_add:
  - SYS_PTRACE               # Required for bomtrace3 ptrace interception
security_opt:
  - seccomp:unconfined        # Required for ptrace to function
```

These settings are non-negotiable. If your Docker installation or
orchestration platform restricts `SYS_PTRACE` or enforces seccomp profiles,
OmniBOR analysis **will not work**.

### Docker on managed platforms

| Platform | `SYS_PTRACE` | `seccomp:unconfined` | Works? |
|---|---|---|---|
| Docker Engine (direct install) | Supported | Supported | **Yes** |
| Docker Desktop (macOS/Windows) | Supported | Supported | **Yes** |
| Amazon ECS / Fargate | Configurable | Configurable | Possible (not tested) |
| Amazon EKS (Kubernetes) | Via `securityContext` | Via `securityContext` | Possible (not tested) |
| AWS App Runner | Not supported | Not supported | **No** |
| AWS Lambda | Not supported | Not supported | **No** |

> **Recommendation:** For reliability and simplicity, run Docker Engine
> directly on an EC2 instance or bare-metal Linux server. Container
> orchestration platforms add configuration complexity for
> ptrace-dependent workloads.

### Build the Docker image

```bash
# From the omnibor-analysis repository root on the build host
docker-compose -f docker/docker-compose.yml build
```

Build time: ~15 minutes on a 4-vCPU instance (compiles `bomtrace2` and
`bomtrace3` from source). Subsequent rebuilds are faster due to Docker layer
caching.

---

<a id="step-4-validate-the-environment"></a>

## Step 4: Validate the Environment

Run these checks to confirm your environment is fully operational.

### 4a. Architecture check

```bash
uname -m
# Expected: x86_64
```

### 4b. Docker check

```bash
docker --version
# Expected: Docker version 20.10+ or newer

docker-compose --version
# Expected: Docker Compose version v2.x.x
```

### 4c. bomtrace3 check

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env bomtrace3 --version
# Expected: strace -- version 6.11 (or similar)
```

### 4d. Container capabilities check

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  sh -c 'cat /proc/self/status | grep CapEff'
# Should show capabilities including SYS_PTRACE (bit 19)
```

### 4e. Outbound connectivity check

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  sh -c 'curl -s https://github.com > /dev/null && echo "GitHub OK" && \
         curl -s https://registry-1.docker.io > /dev/null && echo "Docker Hub OK"'
```

### 4f. Quick functional test

```bash
# Run a fast analysis (redis takes ~2 minutes)
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo redis
```

If all checks pass, your environment is ready.

---

<a id="step-5-configure-your-infrastructure-profile"></a>

## Step 5: Configure Your Infrastructure Profile

The infrastructure profile tells Cascade (the AI assistant) how to interact
with your build host.

### For remote hosts (EC2, other cloud, on-prem server)

```bash
cp .windsurf/rules/infrastructure/templates/aws-ec2.md \
   .windsurf/rules/infrastructure/active-profile.md
```

Edit `active-profile.md` with your actual values:

| Field | Example |
|---|---|
| Instance ID | `i-0abc123def456789` |
| SSH alias | `omnibor-build` |
| IP | `10.0.1.50` or `54.215.15.253` |
| Region | `us-west-2` |
| Instance Type | `c6i.xlarge` |
| Repo path on host | `/home/ubuntu/omnibor-analysis` |

### For local Docker hosts

```bash
cp .windsurf/rules/infrastructure/templates/local-linux.md \
   .windsurf/rules/infrastructure/active-profile.md
```

> **Note:** `active-profile.md` is gitignored — your infrastructure details
> stay local and are never committed to the repository.

---

<a id="step-6-run-a-test-analysis"></a>

## Step 6: Run a Test Analysis

### From Cascade (recommended)

In the Windsurf IDE Cascade chat:

```
/run-analysis
```

Choose `redis` for a quick ~2 minute test.

### Manually via SSH

```bash
ssh omnibor-build "cd ~/omnibor-analysis && \
  docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo redis"
```

### Sync results to local machine

```bash
rsync -avz omnibor-build:~/omnibor-analysis/output/ output/
```

Results will be in `output/spdx/c-cpp/redis/<timestamp>/`.

---

<a id="networking-requirements"></a>

## Networking Requirements

The build host needs outbound HTTPS access to several external services.
No inbound connections are required beyond SSH for management.

### Outbound destinations

| Destination | Port | Protocol | Purpose |
|---|---|---|---|
| `github.com` | 443 | HTTPS | Git clone target repositories |
| `registry-1.docker.io` | 443 | HTTPS | Docker base image pulls |
| `production.cloudflare.docker.com` | 443 | HTTPS | Docker image layers |
| `archive.ubuntu.com` | 80/443 | HTTP/S | apt package installation |
| `security.ubuntu.com` | 80/443 | HTTP/S | apt security updates |
| `dlcdn.apache.org` | 443 | HTTPS | Maven binary download |
| `repo1.maven.org` | 443 | HTTPS | Maven Central (Java deps) |
| `go.dev`, `proxy.golang.org` | 443 | HTTPS | Go module downloads |
| `crates.io`, `static.crates.io` | 443 | HTTPS | Rust crate downloads |
| `pypi.org` | 443 | HTTPS | Python package downloads |
| `sh.rustup.rs` | 443 | HTTPS | Rust toolchain installer |

### Private subnet with NAT Gateway

If your instance is in a private subnet (no public IP), it can still work
as long as:

1. A **NAT Gateway** or **NAT Instance** provides outbound internet access
2. Route tables for the subnet include a route to the NAT Gateway
3. SSH access is through a **bastion host** or **AWS Systems Manager Session Manager**

```
┌─────────────────┐     ┌─────────────┐     ┌──────────┐
│  Your Laptop    │────▶│  Bastion /   │────▶│ omnibor  │
│  (SSH client)   │     │  SSM         │     │ build    │
└─────────────────┘     └─────────────┘     └──────────┘
                                                  │
                                           ┌──────▼──────┐
                                           │ NAT Gateway  │
                                           │ (outbound)   │
                                           └──────────────┘
```

Update your `~/.ssh/config` for bastion access:

```
Host omnibor-build
    HostName 10.0.1.50
    User ubuntu
    IdentityFile ~/.ssh/your-key.pem
    ProxyJump bastion-host
```

### VPN-based access

If you connect to your AWS VPC via VPN (AWS Client VPN, Cisco AnyConnect,
WireGuard, etc.):

- Use the instance's **private IP** in `~/.ssh/config`, not a public IP
- No Elastic IP or public subnet is required
- Ensure the VPN's routing allows traffic to the instance's subnet
- Verify the security group allows SSH from the VPN CIDR

---

<a id="corporate-and-enterprise-considerations"></a>

## Corporate and Enterprise Considerations

### Shared AWS accounts

If your AWS account is shared across teams:

- **Tag your resources:** Add `Project=omnibor-analysis` and `Owner=<your-name>` tags to all resources
- **Use a dedicated security group:** Do not modify shared security groups
- **Naming convention:** Prefix resources with `omnibor-` for easy identification
- **Cost allocation:** Use AWS Cost Explorer tags to track spending

### AWS Organizations and Service Control Policies (SCPs)

Some organizations restrict:

| Restriction | Impact | Workaround |
|---|---|---|
| Instance types limited | May not allow `c6i.xlarge` | Use any allowed x86_64 type (t3, m6i, etc.) |
| Regions restricted | Must use an approved region | Launch in any approved region |
| Public IP disabled | Cannot assign public IPs | Use private subnet + NAT + bastion/VPN |
| AMI restricted | Cannot use community AMIs | Request Ubuntu 22.04 AMI approval, or use a pre-approved base AMI with Docker installed |
| `SYS_PTRACE` blocked at OS level | Docker `--cap-add=SYS_PTRACE` fails | **Blocker** — request exception from security team |

### Proxy servers

If your environment routes traffic through an HTTP/HTTPS proxy:

```bash
# Set proxy for Docker daemon (on the build host)
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo cat > /etc/systemd/system/docker.service.d/http-proxy.conf << 'EOF'
[Service]
Environment="HTTP_PROXY=http://proxy.example.com:8080"
Environment="HTTPS_PROXY=http://proxy.example.com:8080"
Environment="NO_PROXY=localhost,127.0.0.1,169.254.169.254"
EOF
sudo systemctl daemon-reload
sudo systemctl restart docker
```

> **Note:** The `169.254.169.254` exclusion is required for the EC2 instance
> metadata service.

### AWS Systems Manager (SSM) Session Manager

If your organization mandates SSM instead of direct SSH:

1. Ensure the instance has the SSM agent installed (included in Ubuntu 22.04 AMIs by default)
2. Attach an IAM instance profile with `AmazonSSMManagedInstanceCore` policy
3. Connect via:

```bash
aws ssm start-session --target i-YOUR_INSTANCE_ID
```

4. For file transfer, use SSM port forwarding + SCP, or S3 as an intermediary

---

<a id="iam-permissions-reference"></a>

## IAM Permissions Reference

### Minimum permissions to launch a new EC2

If you need to create a new instance in an existing VPC, your IAM
role/user needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EC2LaunchAndManage",
      "Effect": "Allow",
      "Action": [
        "ec2:RunInstances",
        "ec2:DescribeInstances",
        "ec2:DescribeImages",
        "ec2:DescribeSubnets",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeKeyPairs",
        "ec2:DescribeVpcs",
        "ec2:StartInstances",
        "ec2:StopInstances",
        "ec2:CreateTags"
      ],
      "Resource": "*"
    },
    {
      "Sid": "EC2OptionalElasticIP",
      "Effect": "Allow",
      "Action": [
        "ec2:AllocateAddress",
        "ec2:AssociateAddress",
        "ec2:DescribeAddresses",
        "ec2:ReleaseAddress",
        "ec2:DisassociateAddress"
      ],
      "Resource": "*"
    },
    {
      "Sid": "EC2OptionalSecurityGroup",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateSecurityGroup",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:AuthorizeSecurityGroupEgress"
      ],
      "Resource": "*"
    }
  ]
}
```

### If using an existing instance only

You only need:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:StartInstances",
        "ec2:StopInstances"
      ],
      "Resource": "*"
    }
  ]
}
```

### Instance profile (attached to the EC2 instance itself)

The EC2 instance does **not** need an IAM instance profile for OmniBOR
analysis. All work happens locally on the instance (Docker, git, builds).

An instance profile is only needed if you want:

- **SSM Session Manager** access → `AmazonSSMManagedInstanceCore`
- **S3 access** for artifact storage → custom S3 policy
- **ECR access** for private Docker images → `AmazonEC2ContainerRegistryReadOnly`

---

<a id="instance-sizing-guide"></a>

## Instance Sizing Guide

### Recommended x86_64 instance types

| Instance | vCPU | RAM | Cost/hr (us-west-2) | Best for |
|---|---|---|---|---|
| `t3.medium` | 2 | 4 GB | ~$0.042 | Small repos (curl, redis, jsoup) |
| `t3.large` | 2 | 8 GB | ~$0.083 | Most repos, comfortable headroom |
| `c6i.xlarge` | 4 | 8 GB | ~$0.170 | **Recommended** — fast builds |
| `c6i.2xlarge` | 8 | 16 GB | ~$0.340 | Large repos (Node.js, FFmpeg) |
| `c6i.4xlarge` | 16 | 32 GB | ~$0.680 | Node.js full build (~25 min) |

### Do NOT use these instance families

| Family | Architecture | Reason |
|---|---|---|
| `t4g`, `m7g`, `c7g`, `r7g` | ARM64 (Graviton) | `bomtrace3` requires x86_64 |
| `a1` | ARM64 (Graviton 1) | Same — `bomtrace3` requires x86_64 |
| `t2` | x86_64 | Works, but t3 is newer and cheaper |

### Storage

| Size | Use case |
|---|---|
| 30 GB gp3 | Minimum — single repo analysis |
| 50 GB gp3 | **Recommended** — multiple repos, Docker image cache |
| 100 GB gp3 | Heavy use — Node.js (large build), all repos simultaneously |

> **gp3 baseline:** 3000 IOPS and 125 MB/s throughput are included at no
> extra cost. This is sufficient for all OmniBOR workloads.

### Build time estimates

| Repository | Language | t3.medium | c6i.xlarge |
|---|---|---|---|
| curl | C | ~1 min | ~30 sec |
| redis | C | ~2 min | ~1 min |
| FFmpeg | C | ~24 min | ~8 min |
| Node.js | C++ | ~99 min | ~25 min |
| oxipng | Rust | ~2 min | ~1 min |
| lazygit | Go | ~2 min | ~1 min |
| checkstyle | Java | ~1 min | ~30 sec |

---

<a id="daily-workflow"></a>

## Daily Workflow

### Start of day

```bash
# 1. Start the instance (if stopped)
aws ec2 start-instances --instance-ids i-YOUR_ID --no-cli-pager

# 2. Wait for it
aws ec2 wait instance-running --instance-ids i-YOUR_ID

# 3. Sync latest code
rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '.venv' \
  --exclude 'output/' --exclude 'repos/' \
  -e ssh ./ omnibor-build:~/omnibor-analysis/

# 4. Run analysis, iterate, etc.
```

### End of day

```bash
# 1. Sync results
rsync -avz omnibor-build:~/omnibor-analysis/output/ output/

# 2. Stop the instance (saves money!)
aws ec2 stop-instances --instance-ids i-YOUR_ID --no-cli-pager
```

### Cost tip

Stopping the instance reduces costs to just the EBS storage charge
(~$4/month for 50 GB gp3). The Elastic IP is free while the instance is
running but costs ~$3.60/month while stopped.

---

<a id="troubleshooting"></a>

## Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| `bomtrace3: Exec format error` | ARM64 instance | Must use x86_64 instance type |
| `docker: Error response... OCI runtime` with ptrace | `SYS_PTRACE` not granted | Verify `docker-compose.yml` has `cap_add: SYS_PTRACE` and `seccomp:unconfined` |
| Docker build fails at `bomtrace3` compile | Not enough RAM | Use instance with ≥4 GB RAM |
| `git clone` fails on EC2 | Private repo, no credentials | Use rsync from local machine |
| SSH timeout from corporate network | Firewall blocks port 22 | Use VPN, bastion host, or SSM Session Manager |
| SSH timeout (public subnet) | Security group missing SSH rule | Add inbound TCP/22 from your IP |
| `docker: permission denied` | User not in docker group | Run `sudo usermod -aG docker $USER`, then log out/in |
| Out of disk space | EBS volume too small | Resize: `aws ec2 modify-volume --size 100 --volume-id vol-XXX` then `sudo growpart` + `sudo resize2fs` |
| Analysis runs but SPDX is empty | Clean build needed | Run with `make distclean` or `cargo clean` before analysis |
| Graviton instance already provisioned | Need x86_64, have ARM64 | Launch a new x86_64 instance (Scenario B); cannot convert |

### Verifying architecture when unsure

If you are unsure whether an instance is x86_64 or ARM64:

```bash
# From the AWS CLI
aws ec2 describe-instances --instance-ids i-YOUR_ID \
  --query 'Reservations[0].Instances[0].Architecture' \
  --output text --no-cli-pager
# Must show: x86_64

# From inside the instance
uname -m
# Must show: x86_64
```

---

<a id="decision-flowchart"></a>

## Decision Flowchart

Use this to quickly determine the right path:

```text
Do you have an existing x86_64 Linux server (any provider)?
├── YES → Does it have Docker installed?
│   ├── YES → Does Docker allow SYS_PTRACE + seccomp:unconfined?
│   │   ├── YES → Scenario A: Clone repo, build image, validate
│   │   └── NO  → Can you change Docker config?
│   │       ├── YES → Enable capabilities, then Scenario A
│   │       └── NO  → Scenario B: Launch a new dedicated EC2
│   └── NO  → Can you install Docker?
│       ├── YES → Install Docker, then Scenario A
│       └── NO  → Scenario B: Launch a new dedicated EC2
├── NO  → Do you have an existing AWS account with a VPC?
│   ├── YES → Scenario B: Launch new x86_64 EC2 in your VPC
│   └── NO  → Use the Greenfield Guide (aws-setup-guide.md)
```

---

## Related Documentation

- [Greenfield AWS Setup Guide](aws-setup-guide.md) — Terraform-based provisioning from scratch
- [Platform Support](../architecture/platform-support.md) — Architecture constraints and ARM64 roadmap
- [Onboarding Guide](ONBOARDING.md) — General project onboarding
- [Contributing Guide](CONTRIBUTING.md) — Branch workflow and code style
- [Infrastructure Profiles]( ../../.windsurf/rules/infrastructure/README.md) — Cascade AI configuration for your build host
