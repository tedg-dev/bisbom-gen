---
description: Provision a new EC2 build host from scratch using Terraform
---

# EC2 Provision (Greenfield)

Provision a new AWS EC2 build host for OmniBOR analysis. Run this once
per developer when setting up for the first time.

**Prerequisites:** The user must have already completed:

- AWS CLI, Terraform, and duo-sso installed (see platform instructions below)
- duo-sso configured and authenticated (`aws sts get-caller-identity` works)

## 0. Detect platform and verify prerequisites

Determine the user's platform and verify all required tools are installed:

```bash
uname -s && uname -m
```

### macOS (Homebrew)

```bash
brew --version && aws --version && terraform --version
```

### Linux (apt-based)

```bash
aws --version && terraform --version
```

### Windows (WSL2)

```bash
wsl --version 2>/dev/null || echo "Not in WSL"
aws --version && terraform --version
```

If any tool is missing, guide the user to install it:

| Tool | macOS | Linux (apt) | Windows (WSL2) |
|------|-------|-------------|----------------|
| AWS CLI v2 | `brew install awscli` | `curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip && unzip awscliv2.zip && sudo ./aws/install` | Same as Linux (inside WSL) |
| Terraform | `brew install terraform` | `sudo apt-get install -y gnupg software-properties-common && wget -O- https://apt.releases.hashicorp.com/gpg \| sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg && echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" \| sudo tee /etc/apt/sources.list.d/hashicorp.list && sudo apt update && sudo apt install terraform` | Same as Linux (inside WSL) |
| duo-sso | `brew tap ats-operations/homebrew-tap https://wwwin-github.cisco.com/ATS-operations/homebrew-tap && brew install ats-operations/tap/duo-sso` | `nix run "git+https://wwwin-github.cisco.com/ATS-operations/duo-sso.git" --` | Same as Linux (inside WSL) |
| Docker | Docker Desktop for Mac | `curl -fsSL https://get.docker.com \| sh` | Docker Desktop for Windows with WSL2 backend |

## 1. Verify AWS authentication

// turbo
```bash
aws sts get-caller-identity --no-cli-pager
```

If this fails, the user needs to authenticate with duo-sso first.
Guide them through the process in `docs/guides/aws-setup-guide.md`.

## 2. Generate SSH key (if needed)

Check for an existing key:

// turbo
```bash
ls -la ~/.ssh/id_ed25519.pub 2>/dev/null || echo "No SSH key found"
```

If no key exists:

```bash
ssh-keygen -t ed25519 -C "omnibor-build" -f ~/.ssh/id_ed25519 -N ""
```

## 3. Create terraform.tfvars

// turbo
```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
```

Then edit `terraform/terraform.tfvars` — the user **must** set `aws_profile`
to their duo-sso profile name. All other values have sensible defaults.

Ask the user for their AWS profile name if you don't know it.

## 4. Initialize Terraform

```bash
terraform -chdir=terraform init
```

## 5. Plan and apply

```bash
terraform -chdir=terraform plan -out=tfplan
```

Review the plan with the user. It should create:

- 1 EC2 instance (x86_64)
- 1 Elastic IP
- 1 Security Group (SSH from current IP)
- 1 Key Pair

After user approval:

```bash
terraform -chdir=terraform apply tfplan
```

## 6. Save Terraform output

// turbo
```bash
terraform -chdir=terraform output -json
```

Extract the Elastic IP, Instance ID, and SSH config from the output.

## 7. Configure SSH

Add SSH config entry. Determine the correct SSH key path for the platform:

### macOS / Linux

Add to `~/.ssh/config`:

```
Host omnibor-build
    HostName <ELASTIC_IP>
    User ubuntu
    IdentityFile ~/.ssh/id_ed25519
    StrictHostKeyChecking accept-new
```

### Windows (WSL2)

Add to `~/.ssh/config` inside WSL (NOT the Windows `C:\Users\...\.ssh\config`):

```
Host omnibor-build
    HostName <ELASTIC_IP>
    User ubuntu
    IdentityFile ~/.ssh/id_ed25519
    StrictHostKeyChecking accept-new
```

Test connectivity:

```bash
ssh -o ConnectTimeout=10 omnibor-build "echo SSH OK && uname -m"
```

If port 22 is blocked (Cisco VPN), try port 443:

```bash
ssh -p 443 -o ConnectTimeout=10 omnibor-build "echo SSH OK"
```

If port 443 works, update `~/.ssh/config` to add `Port 443`.

## 8. Create active infrastructure profile

```bash
cp .windsurf/rules/infrastructure/templates/aws-ec2.md \
   .windsurf/rules/infrastructure/active-profile.md
```

Edit `active-profile.md` with the Terraform output values:

- Instance ID
- Elastic IP
- AWS Profile name
- SSH alias
- Instance type

This file is gitignored — personal details stay local.

## 9. Wait for bootstrap and verify

The EC2 instance runs `user-data.sh` on first boot (~10-20 minutes).
Check progress:

```bash
ssh omnibor-build "tail -20 /var/log/cloud-init-output.log"
```

If bootstrap is complete, verify Docker and bomtrace:

```bash
ssh omnibor-build "docker --version && docker-compose --version"
```

If the repo clone failed during bootstrap (private repo), push code manually:

```bash
rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '.venv' \
  --exclude 'output/' --exclude 'repos/' \
  --exclude 'terraform/.terraform/' --exclude 'terraform/terraform.tfstate*' \
  -e ssh ./ omnibor-build:~/omnibor-analysis/
```

Then build the Docker image:

```bash
ssh omnibor-build "cd ~/omnibor-analysis && \
  docker-compose -f docker/docker-compose.yml build"
```

## 10. Run a test analysis

```bash
ssh omnibor-build "cd ~/omnibor-analysis && \
  docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --list"
```

## 11. Report completion

Confirm to the user:

- EC2 instance ID, type, and Elastic IP
- SSH connectivity verified
- Docker image built
- Container tools available (bomtrace2, bomtrace3, syft, go)
- Active profile created at `.windsurf/rules/infrastructure/active-profile.md`
- Ready for `/run-analysis`
