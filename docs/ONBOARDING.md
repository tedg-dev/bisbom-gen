# OmniBOR Analysis — Onboarding Guide

Welcome! This guide will get you from a fresh clone to running OmniBOR build
interception analysis on any C/C++ GitHub repository, with Windsurf Cascade AI
handling the heavy lifting.

## What This Project Does

This project **instruments C/C++ and Rust builds** using [OmniBOR/Bomsh](https://github.com/omnibor/bomsh)
to capture every compiler and linker invocation, then generates **SPDX 2.3 SBOMs**
with full dependency breakdown:

- **Vendored static libraries** (STATIC_LINK) — detected from source directory structure
- **Dynamic system libraries** (DYNAMIC_LINK) — resolved via ldd/readelf + dpkg
- **Build tools** (BUILD_TOOL_OF) — gcc/clang version tracking
- **Interactive HTML dependency graphs** — D3.js force-directed visualizations

## Prerequisites

| Requirement | Purpose |
|---|---|
| **Windsurf IDE** | IDE with Cascade AI assistant |
| **Python 3.9+** | Local development, testing, and repo configuration |
| **Docker 20.10+** on a **Linux x86_64** host | Running the analysis container |
| **Git** | Version control |

> **Important:** The analysis container requires native Linux x86_64 with ptrace
> support. It does NOT work on macOS, Windows, ARM64, or under QEMU/Rosetta.
> You can develop and test locally on any OS, but the actual build analysis
> must run on a Linux x86_64 host (local, cloud VM, or remote server).

## Step 1: Clone and Open in Windsurf

```bash
git clone https://github.com/tedg-dev/omnibor-analysis.git
cd omnibor-analysis
```

Open this directory in Windsurf IDE.

## Step 2: Configure Cascade

1. Open Windsurf Settings → Cascade → Model
2. Select **Claude Opus 4.6** — this is strongly recommended. All project
   rules, workflows, and automation in this repository were developed and
   tested using Claude Opus 4.6. Other models may not follow the `.windsurf/`
   rules correctly or produce consistent results.
3. The `.windsurf/` directory contains all rules and workflows that Cascade
   reads automatically — no manual configuration needed

## Step 3: First-Time Setup

In the Cascade chat, type:

```
/first-time-setup
```

This will:
- Read all project rules and workflows
- Create the Python virtual environment
- Install dependencies from `requirements.txt`
- Run the test suite (427+ tests, 99% coverage)
- Check Docker availability
- Report the environment status

## Step 4: Set Up Your Linux Build Host

### Option A: Local Linux x86_64

If you're already on Linux x86_64:

```bash
docker-compose -f docker/docker-compose.yml build
```

This takes 10-20 minutes on first build (compiles bomtrace3 from source).

### Option B: AWS EC2 (Recommended for Cisco Engineers)

Follow the comprehensive setup guide:

**[docs/aws-setup-guide.md](docs/aws-setup-guide.md)**

This covers Cisco Duo SSO authentication, Terraform provisioning, and
everything needed to go from zero to running builds. The guide handles:

- Installing duo-sso, AWS CLI, and Terraform
- Authenticating via Cisco Duo SSO (SAML → AWS STS)
- Provisioning an EC2 instance with Terraform (IaC)
- SSH configuration and infrastructure profile setup
- Re-authentication (sessions expire every 1 hour)
- Cost management and daily workflow

> **Note:** Cisco Duo SSO sessions expire every **1 hour**. The guide
> documents the re-authentication flow in detail.

### Option B2: Other Cloud VM (DigitalOcean, etc.)

1. Create an x86_64 Linux VM (Ubuntu 22.04 recommended, 2+ GB RAM)
2. Install Docker: `curl -fsSL https://get.docker.com | sh`
3. Clone the repo on the VM
4. Build the image: `docker-compose -f docker/docker-compose.yml build`
5. Set up SSH access from your local machine

### Option C: WSL2 on Windows

1. Install WSL2 with Ubuntu 22.04
2. Install Docker Desktop with WSL2 backend
3. Clone and build inside WSL2

## Step 5: Analyze a Repository

### Use a pre-configured repo

Tell Cascade:

```
Run analysis on curl
```

Or use the workflow directly:

```
/run-analysis
```

Pre-configured C/C++ repos: **curl**, **redis**, **ffmpeg**, **nmap**

Pre-configured Rust repos: **oxipng**, **dura**

Go repos (experimental, TBD): **lazygit**, **pocketbase**

### Add a new repo from GitHub

Tell Cascade:

```
Add openssl for analysis
```

Or use the workflow:

```
/add-repo
```

This auto-discovers the repo's build system, configure flags, output binaries,
and required apt packages from GitHub. You review and approve before it writes
to `config.yaml`.

## Step 6: View Results

After analysis completes, you'll find:

| Output | Location | Description |
|---|---|---|
| SPDX SBOM (per binary) | `output/spdx/{lang}/{repo}/{ts}/<binary>_adg.spdx.json` | Full dependency breakdown |
| HTML visualization | `output/spdx/{lang}/{repo}/{ts}/<binary>_adg.spdx.html` | Interactive D3.js graph |
| OmniBOR ADG | `output/omnibor/{lang}/{repo}/{ts}/` | Cryptographic build provenance |
| Component metadata | `output/omnibor/{lang}/{repo}/{ts}/metadata/` | dpkg package resolution |

`{lang}` is `c-cpp`, `rust`, or `go`. `{ts}` is `YYYY-MM-DD_HHMM`.

Open the `.spdx.html` files in a browser to see interactive dependency graphs
with color-coded nodes (purple=root, teal=vendored, red=dynamic, yellow=build tool).

## Available Cascade Commands

| Command | What it does |
|---|---|
| `/setup-environment` | Verify environment on every startup |
| `/first-time-setup` | Complete first-time setup (one-time) |
| `/add-repo` | Add a new GitHub repo for analysis |
| `/run-analysis` | Run build interception + SBOM generation |
| `/docker-build` | Build or rebuild the Docker container |
| `/merge-pr` | Merge a feature branch (after approval) |

## Project Structure

```
omnibor-analysis/
├── app/                    # Orchestration scripts and modular packages
│   ├── pipeline/           # Analysis pipeline (clone, build, instrument, generate SBOMs)
│   ├── spdx/               # Per-binary SPDX 2.3 generation from ADG data
│   ├── repo_discovery/     # Auto-discover and configure repos from GitHub
│   └── templates/          # Report templates
├── docker/                 # Container environment (Ubuntu 22.04 + gcc + Rust + Go + bomtrace)
├── terraform/              # AWS EC2 infrastructure as code
├── tests/                  # Unit tests (427+ tests, 99% coverage)
├── docs/                   # Documentation and analysis reports
│   └── summary/            # Architecture and deep-dive docs
├── .windsurf/              # Cascade AI configuration (rules + workflows)
├── repos/                  # Cloned target repos (gitignored)
└── output/                 # Generated artifacts (gitignored)
```

> See [`app/README.md`](../app/README.md) for detailed module documentation.

## Development Workflow

1. All changes go through feature branches (never commit directly to main)
2. Pre-commit gates: all tests pass + per-file 95%+ coverage + overall 97%+
3. Cascade handles branch names, commits, and merges via `/merge-pr`
4. Every commit includes a markdown doc in `docs/summary/` describing changes

## Troubleshooting

| Problem | Solution |
|---|---|
| Tests fail | `pip install -r requirements.txt` in the venv |
| Docker build fails | Check Docker is installed and x86_64: `uname -m` should show `x86_64` |
| bomtrace3 "Exec format error" | You're on ARM64 — need an x86_64 host |
| "SYS_PTRACE" error | Docker must have `--cap-add=SYS_PTRACE` (set in docker-compose.yml) |
| SBOM has no vendored libs | Add `vendored_dirs` to config.yaml (see nmap example) |
| Analysis takes too long | FFmpeg is ~24 min; curl/redis/nmap are 3-5 min |

## Further Reading

- `docs/aws-setup-guide.md` — **Greenfield AWS EC2 setup (Cisco Duo SSO + Terraform)**
- `docs/aws-ec2-migration-recommendation.md` — Instance sizing and cost comparison
- `docs/summary/spdx-generation-deep-dive.md` — Full technical pipeline documentation
- `docs/summary/workflow-guide.md` — Detailed workflow descriptions
- `docs/summary/nmap-target-vendored-dirs.md` — Vendored directory detection explained
