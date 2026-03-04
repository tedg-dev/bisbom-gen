# Terraform — OmniBOR AWS EC2 Build Host

Infrastructure as Code for provisioning the OmniBOR build analysis EC2 instance.

## What It Creates

| Resource | Description |
|----------|-------------|
| EC2 Instance | Ubuntu 22.04 x86_64, c6i.xlarge (default) |
| EBS Volume | 50 GB gp3 (3000 IOPS) |
| Elastic IP | Static IP that persists across stop/start |
| Security Group | SSH (port 22) from your current IP only |
| Key Pair | Your ed25519 public key |

## Prerequisites

1. **AWS CLI v2**: `brew install awscli`
2. **Terraform**: `brew install terraform`
3. **duo-sso**: See `.windsurf/rules/infrastructure/templates/aws-ec2.md` for install + auth

## Authentication

Cisco users authenticate via duo-sso (SAML → STS). **Sessions expire every 1 hour.**

```bash
# Browserless mode (recommended)
# 1. Go to https://go2.cisco.com/aws → complete SSO + Duo MFA
# 2. Click SAML bookmarklet → downloads saml.txt
# 3. Run:
duo-sso -saml $(cat ~/Downloads/saml.txt) -profile ted-admin -set-aws-region us-west-1
sed -i '' 's/^\[default\]/[ted-admin]/' ~/.aws/credentials   # macOS

# Verify
aws sts get-caller-identity --profile ted-admin --no-cli-pager
```

## Quick Start

```bash
cd terraform/

# One-time init
terraform init

# Review what will be created
terraform plan -out=tfplan

# Apply
terraform apply tfplan

# When done — tear down everything
terraform destroy
```

## Customization

Copy the example vars file and edit:

```bash
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values
```

## Cost

| State | c6i.xlarge | t3.medium |
|-------|-----------|-----------|
| Running | ~$0.170/hr | ~$0.042/hr |
| Stopped (EBS only) | ~$4/mo | ~$4/mo |
| Elastic IP (while stopped) | ~$3.60/mo | ~$3.60/mo |
| Destroyed | $0 | $0 |

**Tip:** At 4 hours/day × 20 days/month, c6i.xlarge costs ~$14/mo on-demand.

## Files

| File | Description |
|------|-------------|
| `main.tf` | Provider, EC2 instance, security group, Elastic IP |
| `variables.tf` | Configurable variables with defaults |
| `outputs.tf` | Post-apply output (IP, SSH config, power commands) |
| `user-data.sh` | Bootstrap script (Docker, repo clone, image build) |
| `terraform.tfvars.example` | Example overrides (copy to terraform.tfvars) |
| `terraform.tfvars` | Your overrides (gitignored) |
