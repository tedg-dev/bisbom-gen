# AWS EC2 Setup Guide — Greenfield Install

**Purpose:** Step-by-step instructions for a Cisco engineer to go from a fresh
`omnibor-analysis` clone to a fully provisioned AWS EC2 build host running
OmniBOR analysis.

**Audience:** Cisco employees using Duo SSO for AWS authentication.

> **Time estimate:** ~30 minutes for first-time setup (excluding Duo enrollment).

## Table of Contents

- [Prerequisites](#prerequisites)
- [Step 1: Install CLI Tools](#step-1-install-cli-tools)
- [Step 2: Install and Configure duo-sso](#step-2-install-and-configure-duo-sso)
- [Step 3: Authenticate to AWS](#step-3-authenticate-to-aws)
- [Step 4: Provision EC2 with Terraform](#step-4-provision-ec2-with-terraform)
- [Step 5: Configure Infrastructure Profile](#step-5-configure-infrastructure-profile)
- [Step 6: Verify the Build Host](#step-6-verify-the-build-host)
- [Daily Workflow](#daily-workflow)
- [Re-Authentication](#re-authentication)
- [Cost Management](#cost-management)
- [Troubleshooting](#troubleshooting)
- [Tearing Down](#tearing-down)

---

## Prerequisites

| Requirement | How to get it |
|---|---|
| **Cisco CEC account** | Your standard Cisco login |
| **Duo MFA enrolled** | Enroll at https://disco.cisco.com |
| **AWS account with Duo SSO** | Request via your team's cloud access process |
| **macOS or Linux workstation** | For running CLI tools |
| **Homebrew** (macOS) | https://brew.sh |
| **Git** | `brew install git` or `apt install git` |

> **Important:** You must be enrolled in Duo MFA before proceeding.
> The Duo SSO URL and AWS account/role details come from your team's AWS setup.

## Step 1: Install CLI Tools

### macOS (Homebrew)

```bash
# AWS CLI v2
brew install awscli

# Terraform
brew install terraform

# duo-sso (Cisco internal Homebrew tap — requires VPN or on-network)
brew tap ats-operations/homebrew-tap https://wwwin-github.cisco.com/ATS-operations/homebrew-tap
brew install ats-operations/tap/duo-sso
```

### Verify installations

```bash
aws --version          # aws-cli/2.x.x ...
terraform --version    # Terraform v1.x.x
duo-sso --version      # duo-sso v3.x.x
```

### Optional: Nix (alternative for duo-sso)

If Homebrew tap doesn't work (e.g., off-network), install Nix and use:

```bash
# Install Nix
sh <(curl -L https://nixos.org/nix/install) --daemon

# Run duo-sso via Nix (always gets latest version)
nix run "git+https://wwwin-github.cisco.com/ATS-operations/duo-sso.git" --
```

## Step 2: Install and Configure duo-sso

### 2a. Create duo-sso config

Create `~/.config/duo-sso/config.json`:

```bash
mkdir -p ~/.config/duo-sso
```

```json
{
  "url": "<YOUR_DUO_SSO_URL>",
  "partner_spid": "https://signin.aws.amazon.com/saml",
  "aws_urn": "https://signin.aws.amazon.com/saml",
  "session_duration_seconds": 3600,
  "profiles": {
    "<YOUR_PROFILE_NAME>": {
      "aws_account_id": "<YOUR_AWS_ACCOUNT_ID>",
      "aws_role_name": "<YOUR_ROLE_NAME>",
      "session_duration_seconds": 3600
    }
  }
}
```

> **Important:** Both `session_duration_seconds` values must be `3600` (1 hour).
> The duo-sso README shows a default of `28800` (8 hours), but AWS administrators
> typically enforce a maximum of 1 hour. Using `28800` causes the error:
> *"The requested DurationSeconds exceeds the MaxSessionDuration"*

Replace the placeholders with values from your team:

| Placeholder | Example | Where to find it |
|---|---|---|
| `<YOUR_DUO_SSO_URL>` | `https://sso-XXXXXXXX.sso.duosecurity.com/saml2/sp/XXXX/sso` | Your team's Duo SSO configuration |
| `<YOUR_PROFILE_NAME>` | `ted-admin` | Choose any name you like |
| `<YOUR_AWS_ACCOUNT_ID>` | `697220083013` | AWS console → top-right → account ID |
| `<YOUR_ROLE_NAME>` | `admin` | The IAM role your Duo SSO maps to |

### 2b. Create AWS CLI config

Create `~/.aws/config` with **region only** — no `role_arn` or `source_profile`:

```ini
[profile <YOUR_PROFILE_NAME>]
region=us-west-1
```

> **⚠ Critical:** Do NOT add `role_arn` or `source_profile` to `~/.aws/config`.
> duo-sso already assumes the role and writes STS credentials directly to
> `~/.aws/credentials`. Adding those fields causes an "Infinite loop in
> credential configuration" error.

## Step 3: Authenticate to AWS

duo-sso supports two authentication modes. **Sessions expire every 1 hour**
(enforced by Cisco policy).

### Option A: Interactive Browser Mode (requires Chrome/Chromium)

```bash
duo-sso -profile <YOUR_PROFILE_NAME> -set-aws-region us-west-1
```

This opens Chrome with the Duo SSO login page. Complete MFA and it
writes credentials automatically.

### Option B: Browserless Mode (recommended if Chrome is not your default)

1. **Create a SAML bookmarklet** in your browser. Create a new bookmark with
   this JavaScript as the URL:

   ```
   javascript:void(function(){if(window.location.hostname!=='signin.aws.amazon.com'){alert('This bookmarklet can only be used on https://signin.aws.amazon.com/saml');return;}const saml=document.querySelector('input[name=SAMLResponse]');if(!saml){alert('SAML Response not found!');return;}if(!saml.value||saml.value.length<100){alert('SAML Response is empty or too short! Complete authentication first.');return;}const blob=new Blob([saml.value],{type:'text/plain'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='saml.txt';document.body.appendChild(a);a.click();document.body.removeChild(a);URL.revokeObjectURL(url);console.log('SAML downloaded:',a.download);})()
   ```

2. **Authenticate:**

   - Go to `https://go2.cisco.com/aws` in your browser
   - Complete Cisco SSO + Duo MFA
   - On the AWS SAML page, click the bookmarklet → downloads `saml.txt`

3. **Exchange SAML for AWS credentials:**

   ```bash
   duo-sso -saml $(cat ~/Downloads/saml.txt) -profile <YOUR_PROFILE_NAME> -set-aws-region us-west-1
   ```

### Fix the credential profile name

duo-sso writes credentials under `[default]` instead of your profile name.
Fix this after every authentication:

```bash
# macOS
sed -i '' 's/^\[default\]/[<YOUR_PROFILE_NAME>]/' ~/.aws/credentials

# Linux
sed -i 's/^\[default\]/[<YOUR_PROFILE_NAME>]/' ~/.aws/credentials
```

### Verify

```bash
aws sts get-caller-identity --profile <YOUR_PROFILE_NAME> --no-cli-pager
```

Expected output:

```json
{
    "UserId": "AROAXXXXXXXXXXXXXXXXX:you@cisco.com",
    "Account": "<YOUR_AWS_ACCOUNT_ID>",
    "Arn": "arn:aws:sts::<YOUR_AWS_ACCOUNT_ID>:assumed-role/<YOUR_ROLE_NAME>/you@cisco.com"
}
```

## Step 4: Provision EC2 with Terraform

The `terraform/` directory contains Infrastructure as Code for the build host.

### 4a. Review and customize (optional)

```bash
cd terraform/
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars if you want to change instance type, region, etc.
```

Defaults (no `terraform.tfvars` needed if these work for you):

| Variable | Default | Notes |
|---|---|---|
| `aws_profile` | `ted-admin` | Must match your duo-sso profile |
| `aws_region` | `us-west-1` | Must match your `~/.aws/config` |
| `instance_type` | `c6i.xlarge` | 4 vCPU, 8 GB — see sizing below |
| `ebs_volume_size_gb` | `50` | gp3 with 3000 IOPS |
| `ssh_public_key_path` | `~/.ssh/id_ed25519.pub` | Your SSH public key |

If your profile name is different from `ted-admin`, you **must** create
`terraform.tfvars`:

```hcl
aws_profile = "your-profile-name"
```

### Instance Type Selection

| Instance | vCPU | RAM | Cost/hr | Best for |
|---|---|---|---|---|
| `t3.medium` | 2 | 4 GB | ~$0.042 | Budget, small repos (curl, redis) |
| `t3.large` | 2 | 8 GB | ~$0.083 | Comfortable for most repos |
| `c6i.xlarge` | 4 | 8 GB | ~$0.170 | Recommended — fast builds (ffmpeg in ~5 min) |

> **Constraint:** Must be x86_64 instance type (t3, c6i, m6i, etc.).
> Do NOT use Graviton/ARM instances (t4g, c7g, m7g) — bomtrace3 requires x86_64.

### 4b. Initialize and apply

```bash
# Ensure your AWS session is valid (re-auth if needed — see Step 3)
aws sts get-caller-identity --profile <YOUR_PROFILE_NAME> --no-cli-pager

# One-time initialization
terraform init

# Preview what will be created
terraform plan -out=tfplan

# Create the infrastructure
terraform apply tfplan
```

Terraform will output:

- **Elastic IP** — your stable public IP
- **Instance ID** — for power management commands
- **SSH config entry** — copy this to `~/.ssh/config`
- **Power management commands** — start/stop/check status

**Save the output!** You'll need the instance ID and IP for the next steps.

### 4c. What Terraform creates

| Resource | Purpose |
|---|---|
| EC2 Instance | Ubuntu 22.04 x86_64 build host |
| 50 GB gp3 EBS | Root volume (3000 IOPS baseline) |
| Elastic IP | Static IP that persists across stop/start |
| Security Group | SSH (port 22 + 443) from your current IP only |
| Key Pair | Your ed25519 public key |

### 4d. VPN and SSH access

> **Important:** Cisco VPN blocks outbound SSH (port 22) to AWS IPs and
> intercepts port 443. **Work off-VPN for SSH access.**
>
> VPN is NOT required for any part of this workflow — AWS CLI, Terraform,
> and SSH all work off-VPN. You only needed VPN for the one-time `duo-sso`
> brew tap install.

The security group auto-detects your public IP during `terraform plan/apply`.
If your IP changes (switching networks, VPN on/off), just re-run:

```bash
terraform plan -out=tfplan && terraform apply tfplan
```

sshd listens on both port 22 (standard) and port 443 (fallback). Use
whichever works on your network.

### 4e. Bootstrap (automatic)

The instance runs `user-data.sh` on first boot which:

1. Configures sshd on ports 22 and 443
2. Updates system packages
3. Installs Docker and docker-compose
4. Attempts to clone the omnibor-analysis repository
5. Builds the Docker analysis image (~10-20 minutes)

> **Note:** If the repo is private, the automatic clone will fail.
> Use `rsync` to push the repo from your local machine instead:
>
> ```bash
> rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '.venv' \
>   --exclude 'output/' --exclude 'terraform/.terraform/' \
>   --exclude 'terraform/terraform.tfstate*' --exclude 'terraform/terraform.tfvars' \
>   -e ssh ./ omnibor-build:~/omnibor-analysis/
> ```
>
> Then build the Docker image manually:
>
> ```bash
> ssh omnibor-build "cd ~/omnibor-analysis && docker-compose -f docker/docker-compose.yml build"
> ```

Check bootstrap progress:

```bash
ssh omnibor-build "tail -f /var/log/cloud-init-output.log"
```

## Step 5: Configure Infrastructure Profile

### 5a. Add SSH config

Add the SSH config entry from Terraform output to `~/.ssh/config`:

```
Host omnibor-build
    HostName <ELASTIC_IP from terraform output>
    User ubuntu
    IdentityFile ~/.ssh/id_ed25519
```

Test SSH:

```bash
ssh omnibor-build "uname -m && docker --version"
# Should show: x86_64 and Docker version
```

### 5b. Set up the infrastructure profile

Copy the AWS template and fill in your values:

```bash
cp .windsurf/rules/infrastructure/templates/aws-ec2.md \
   .windsurf/rules/infrastructure/active-profile.md
```

Edit `active-profile.md` with the Terraform output values (instance ID,
Elastic IP, etc.). This file is gitignored — your specific details stay local.

## Step 6: Verify the Build Host

### Check Docker and bomtrace3

```bash
ssh omnibor-build "docker-compose -f ~/omnibor-analysis/docker/docker-compose.yml \
  run --rm omnibor-env bomtrace3 --version"
```

### Run a test analysis

```bash
# From your local machine, tell Cascade:
/run-analysis
# Choose "redis" for a quick ~2 min test
```

Or manually:

```bash
ssh omnibor-build "cd ~/omnibor-analysis && \
  docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo redis"
```

### Sync results back

```bash
rsync -avz omnibor-build:~/omnibor-analysis/output/ output/
rsync -avz omnibor-build:~/omnibor-analysis/docs/ docs/
```

---

## Daily Workflow

```bash
# 1. Authenticate (every hour — set a timer!)
duo-sso -saml $(cat ~/Downloads/saml.txt) -profile <YOUR_PROFILE_NAME> -set-aws-region us-west-1
sed -i '' 's/^\[default\]/[<YOUR_PROFILE_NAME>]/' ~/.aws/credentials

# 2. Start the instance
aws ec2 start-instances --profile <YOUR_PROFILE_NAME> --instance-ids <INSTANCE_ID> --no-cli-pager

# 3. Wait for it to be running
aws ec2 wait instance-running --profile <YOUR_PROFILE_NAME> --instance-ids <INSTANCE_ID>

# 4. Do your work (SSH, run analysis, etc.)

# 5. Stop the instance when done (saves money!)
aws ec2 stop-instances --profile <YOUR_PROFILE_NAME> --instance-ids <INSTANCE_ID> --no-cli-pager
```

## Re-Authentication

Cisco Duo SSO sessions last **1 hour**. When credentials expire, you'll see:

```
An error occurred (ExpiredToken) when calling the DescribeInstances operation
```

or:

```
An error occurred (InvalidClientTokenId) when calling the GetCallerIdentity operation
```

To fix: re-run [Step 3](#step-3-authenticate-to-aws) (takes ~30 seconds).

**Tip:** Set a recurring 55-minute timer when you start working. Re-auth
before it expires to avoid interrupting long-running Terraform operations.

> **Terraform note:** `terraform apply` typically completes in under 2 minutes.
> If you need to run `terraform destroy` + `terraform apply`, do both in the
> same session. A single re-auth gives you a full hour.

## Cost Management

### Pay-per-use model

| Usage Pattern | c6i.xlarge/mo | t3.medium/mo |
|---|---|---|
| 4 hours/day × 20 days | ~$14 | ~$3.40 |
| 8 hours/day × 20 days | ~$27 | ~$6.70 |
| Always running | ~$124 | ~$30 |
| Stopped (EBS + EIP) | ~$7.60 | ~$7.60 |

### Cost-saving tips

1. **Always stop the instance when done** — this is the biggest savings
2. **Release the Elastic IP** if not using the instance for weeks
   (`terraform destroy` handles this)
3. **Use t3.medium** if you mostly analyze small repos (curl, redis)
4. **Use c6i.xlarge** only when building large repos (ffmpeg, nmap)
5. Consider changing instance type between sessions:
   ```bash
   # Stop first, then change type, then start
   aws ec2 stop-instances --profile <YOUR_PROFILE_NAME> --instance-ids <ID> --no-cli-pager
   aws ec2 modify-instance-attribute --profile <YOUR_PROFILE_NAME> --instance-ids <ID> --instance-type '{"Value":"t3.medium"}' --no-cli-pager
   aws ec2 start-instances --profile <YOUR_PROFILE_NAME> --instance-ids <ID> --no-cli-pager
   ```

## Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| "Infinite loop in credential configuration" | `~/.aws/config` has `role_arn` + `source_profile` | Remove both — keep only `region` |
| `ExpiredToken` errors | Duo SSO session expired (1 hour) | Re-authenticate (Step 3) |
| `duo-sso: command not found` | Homebrew tap not installed | Must be on Cisco VPN/network for internal tap |
| `terraform init` fails | AWS provider can't authenticate | Check `aws sts get-caller-identity` works first |
| SSH "Operation timed out" on port 22 | Cisco VPN blocks port 22 to AWS | Disconnect VPN — SSH works off-VPN. Or use port 443: `ssh -p 443 omnibor-build` |
| SSH "Connection reset" on port 443 | Cisco VPN proxy intercepts port 443 | Disconnect VPN — this is the VPN web proxy rejecting non-TLS traffic |
| SSH "Connection refused" | Instance not running or wrong IP | Check instance state; Elastic IP doesn't change |
| SSH "Permission denied" | Wrong key or wrong user | User is `ubuntu` (not `root`), key is `id_ed25519` |
| Git clone fails on EC2 | Private repo, no credentials on instance | Use `rsync` from local machine (see Step 4e) |
| `bomtrace3: Exec format error` | ARM64 instance | Must use x86_64 instance type (t3, c6i, m6i) |
| Docker build fails on instance | Cloud-init still running | Wait for bootstrap: `tail -f /var/log/cloud-init-output.log` |
| Security group blocks SSH | IP changed since `terraform apply` | Run `terraform apply` again to update SG with new IP |

## Tearing Down

To completely remove all AWS resources:

```bash
cd terraform/
terraform destroy
```

This removes the EC2 instance, EBS volume, Elastic IP, security group, and
key pair. **All data on the instance will be lost** — sync results first!

```bash
# Sync before destroying
rsync -avz omnibor-build:~/omnibor-analysis/output/ output/
rsync -avz omnibor-build:~/omnibor-analysis/docs/ docs/

# Then destroy
terraform destroy
```
