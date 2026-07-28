---
description: Complete first-time setup for a new contributor cloning this repo
---

# First-Time Setup

Run this workflow when you've just cloned the omnibor-analysis repository into
a fresh Windsurf IDE installation and want to get everything working.

## 0. Read all project rules and workflows

**This step is mandatory before any other work.**

Read every rule and workflow file to load project conventions:

```bash
for f in .windsurf/rules/*.md; do echo "=== $f ==="; cat "$f"; echo; done
for f in .windsurf/workflows/*.md; do echo "=== $f ==="; cat "$f"; echo; done
```

After reading, confirm to the user which rules and workflows were loaded.

## 1. Detect platform

Determine the user's operating system and architecture:

// turbo
```bash
uname -s && uname -m
```

This affects which tools to install and whether a remote build host is needed.

| Platform | Architecture | Local Docker builds? | Notes |
|----------|-------------|---------------------|-------|
| macOS x86_64 | Intel Mac | Yes (with Docker Desktop) | Native x86 — fastest |
| macOS arm64 | Apple Silicon | Yes (QEMU, slow ~30 min) | EC2 recommended for speed |
| Linux x86_64 | Native | Yes | Ideal local dev |
| Linux arm64 | ARM server | **No** — bomtrace3 is x86-only | EC2 **required** |
| Windows (WSL2) | x86_64 | Yes (Docker Desktop + WSL2) | Run all commands inside WSL |

## 2. Install Python and create virtual environment

### macOS

```bash
brew install python3
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-dev.txt
```

### Linux (Ubuntu/Debian)

```bash
sudo apt-get install -y python3 python3-venv python3-pip
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-dev.txt
```

### Windows (WSL2)

All commands run inside WSL (Ubuntu). Open a WSL terminal:

```bash
sudo apt-get install -y python3 python3-venv python3-pip
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-dev.txt
```

Verify:

// turbo
```bash
.venv/bin/python3 --version && .venv/bin/pip check 2>&1 | tail -3
```

## 3. Run the test suite to verify everything is healthy

// turbo
```bash
.venv/bin/python3 -m pytest tests/ -x -q --cov=app --cov=docker/patches --cov-report=term-missing 2>&1 | tail -15
```

All tests should pass with 97%+ overall coverage.

## 4. Set up build environment

The analysis pipeline runs inside a Docker container on a **Linux x86_64** host.
Choose the path that matches your platform:

### Path A: Local Docker (Linux x86_64 or macOS with Docker Desktop)

Verify Docker is available:

```bash
docker --version && docker-compose --version
```

Build the image:

```bash
docker-compose -f docker/docker-compose.yml build
```

> **macOS Apple Silicon note:** Docker Desktop uses QEMU emulation for x86_64.
> The first build takes ~30 minutes. If this is too slow, use Path B instead.

### Path B: AWS EC2 (recommended for Apple Silicon, ARM Linux, or fast builds)

Provision a remote x86_64 build host. Run:

```
/ec2-provision
```

This workflow will:

1. Verify AWS CLI, Terraform, and duo-sso are installed (with platform-specific install instructions)
2. Walk through Terraform init/plan/apply
3. Configure SSH access
4. Create the infrastructure profile
5. Build the Docker image on EC2

See `docs/guides/aws-setup-guide.md` for the full manual reference.

### Path C: Other remote Linux x86_64 host

If you have SSH access to any Linux x86_64 server with Docker:

```bash
rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '.venv' \
  --exclude 'output/' --exclude 'repos/' \
  -e ssh ./ <YOUR_HOST>:~/omnibor-analysis/
ssh <YOUR_HOST> "cd ~/omnibor-analysis && docker-compose -f docker/docker-compose.yml build"
```

## 5. Verify container tools

For local Docker:

```bash
docker-compose -f docker/docker-compose.yml run --rm bisbom-env \
  bash -c 'which bomtrace2 && which bomtrace3 && syft version && go version'
```

For EC2, use `/ec2-start` which includes verification.

## 6. List available target repositories

Local:

```bash
docker-compose -f docker/docker-compose.yml run --rm bisbom-env \
  python3 /workspace/app/analyze.py --list
```

EC2:

```bash
ssh omnibor-build "cd ~/omnibor-analysis && \
  docker-compose -f docker/docker-compose.yml run --rm bisbom-env \
  python3 /workspace/app/analyze.py --list"
```

## 7. Ready to analyze!

You're now ready to:

- **Add a new repo:** Tell Cascade "add [repo name] for analysis" or use `/add-repo`
- **Run analysis:** Tell Cascade "run analysis on [repo]" or use `/run-analysis`
- **Compare SBOMs:** Tell Cascade "compare SBOMs for [repo]" or use `/run-comparison`

For EC2 sessions, always start with `/ec2-start` to start the instance and sync code.

## Troubleshooting

| Problem | Platform | Solution |
|---------|----------|----------|
| `python3 -m venv` fails | All | Install Python 3.9+ (`brew install python3` on macOS, `apt install python3` on Linux) |
| `docker-compose` not found | All | Install Docker Desktop (macOS/Windows) or `curl -fsSL https://get.docker.com \| sh` (Linux) |
| bomtrace3 "Exec format error" | ARM64 | bomtrace3 is x86-only — use EC2 (`/ec2-provision`) or any x86_64 Linux host |
| Tests fail on import | All | Run `.venv/bin/pip install -r requirements-dev.txt` |
| SYS_PTRACE error | Linux | Docker must run with `--cap-add=SYS_PTRACE` (set in docker-compose.yml) |
| `brew` not found | macOS | Install Homebrew: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"` |
| WSL not installed | Windows | `wsl --install` in PowerShell (admin), then restart |
| Docker Desktop not running | macOS/Win | Start Docker Desktop from Applications/Start Menu |
