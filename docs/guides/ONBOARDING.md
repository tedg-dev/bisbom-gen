# OmniBOR Analysis — Onboarding Guide

Welcome! This guide will get you from a fresh clone to running OmniBOR build
interception analysis on any C/C++, Rust, Go, or Java GitHub repository,
with Windsurf Cascade AI handling the heavy lifting.

## What This Project Does

This project **instruments C/C++, Rust, Go, and Java builds** using [OmniBOR/Bomsh](https://github.com/omnibor/bomsh)
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
| **Docker 20.10+** | Running the analysis container (any OS — Linux, macOS, or Windows) |
| **Git** | Version control |

> **Important:** The analysis container runs as Linux x86_64. **Sidecar
> mode is the only supported mode** — it does not require `SYS_PTRACE` and
> works in standard Docker and Kubernetes environments. Standalone mode is
> **deprecated** (the initial ptrace-based implementation, retained only
> for a rare ~1% embedded corner case) and is not a deployment option.
> See [Platform Support](../architecture/platform-support.md).

## Step 1: Clone and Open in Windsurf

```bash
git clone https://github.com/tedg-dev/omnibor-analysis.git
cd omnibor-analysis
```

Open this directory in Windsurf IDE.

## Step 2: Configure Cascade

1. Open Windsurf Settings → Cascade → Model
2. Select **Claude Opus 4.6 (Thinking)** — this is strongly recommended. All project
   rules, workflows, and automation in this repository were developed and
   tested using Claude Opus 4.6 (Thinking). Other models may not follow the `.windsurf/`
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
- Run the test suite (1,450+ tests, 97%+ coverage)
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

Choose the guide that matches your situation:

**[AWS Greenfield Setup Guide](aws-setup-guide.md)** — Start from scratch
with Terraform. Creates a new VPC, security group, key pair, EC2 instance,
and Elastic IP. Best if you have no existing AWS infrastructure.

**[AWS Existing Environment Guide](aws-existing-environment-guide.md)** —
Add an OmniBOR build host to an existing AWS account. Covers reusing existing
EC2 instances, launching new instances in existing VPCs, corporate networking
(VPN, bastion, NAT Gateway, proxy), IAM permissions, and Graviton/ARM64
compatibility assessment.

Both guides cover:

- Authenticating via Cisco Duo SSO (SAML → AWS STS)
- SSH configuration and infrastructure profile setup
- Re-authentication (sessions expire every 1 hour)
- Cost management and daily workflow

> **Note:** Cisco Duo SSO sessions expire every **1 hour**. Both guides
> document the re-authentication flow in detail.

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

Pre-configured C/C++ repos: **curl**, **redis**, **ffmpeg**, **nmap**, **openosc**, **node**

Pre-configured Go repos: **fzf**, **lazygit**, **croc**, **dive**, **gdu**, **pocketbase**

Pre-configured Rust repos: **oxipng**, **dura**

Pre-configured Java (Maven) repos: **jsoup**, **checkstyle**, **crawler4j**, **dependency-check**, **logging-log4j2**

Pre-configured Java (Gradle) repos: **spring-boot**, **bc-java**

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
| SPDX SBOM (analyzed) | `output/spdx/{lang}/{repo}/{ts}/<binary>_analyzed.spdx.json` | Static deps compiled into the binary |
| SPDX SBOM (build) | `output/spdx/{lang}/{repo}/{ts}/<binary>_build.spdx.json` | Full dependency graph (static + dynamic + transitive) |
| HTML visualization | `output/spdx/{lang}/{repo}/{ts}/<binary>_*.spdx.html` | Interactive D3.js graph (one per SPDX file) |
| OmniBOR ADG | `output/omnibor/{lang}/{repo}/{ts}/` | Cryptographic build provenance |
| Component metadata | `output/omnibor/{lang}/{repo}/{ts}/metadata/` | dpkg package resolution |

`{lang}` is `c-cpp`, `rust`, `go`, or `java`. `{ts}` is `YYYY-MM-DD_HHMM`.

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
\u251c\u2500\u2500 app/                    # Core application code
\u2502   \u251c\u2500\u2500 pipeline/           # Build orchestration (10 steps + facade + runners)
\u2502   \u251c\u2500\u2500 spdx/               # SPDX generation (parser \u2192 resolver \u2192 emitter)
\u2502   \u251c\u2500\u2500 viz/                # D3.js HTML visualization modules
\u2502   \u251c\u2500\u2500 version_detection/  # 12 vendored version detection strategies
\u2502   \u251c\u2500\u2500 repo_discovery/     # Auto-discover repos from GitHub
\u2502   \u251c\u2500\u2500 analyze.py          # CLI entry point \u2192 pipeline facade
\u2502   \u2514\u2500\u2500 config.yaml         # Repository and tool configuration
\u251c\u2500\u2500 docker/                 # Container environment
\u2502   \u251c\u2500\u2500 Dockerfile          # Ubuntu 22.04 + gcc + Rust + Go + bomtrace
\u2502   \u2514\u2500\u2500 docker-compose.yml  # Container orchestration
\u251c\u2500\u2500 terraform/              # AWS EC2 infrastructure as code
\u251c\u2500\u2500 tests/                  # Unit tests (1,450+ tests, 97%+ coverage)
\u251c\u2500\u2500 docs/                   # Hand-written documentation
\u2502   \u251c\u2500\u2500 sidecar/            # Sidecar + phase isolation (per-language subdirs)
\u2502   \u251c\u2500\u2500 architecture/       # General app architecture and technical design
\u2502   \u251c\u2500\u2500 guides/             # Onboarding, contributing, AWS setup
\u2502   \u251c\u2500\u2500 planning/           # Issue & sub-issue planning docs
\u2502   \u251c\u2500\u2500 testing/            # Golden file regression testing
\u2502   \u251c\u2500\u2500 issues/             # Upstream bug tracking
\u2502   \u2514\u2500\u2500 _archived/          # Historical documents (not current)
\u251c\u2500\u2500 .windsurf/              # Cascade AI configuration
\u2502   \u251c\u2500\u2500 rules/              # Project rules (always loaded)
\u2502   \u2514\u2500\u2500 workflows/          # Slash commands (/add-repo, etc.)
\u251c\u2500\u2500 repos/                  # Cloned target repos (gitignored)
\u2514\u2500\u2500 output/                 # Generated artifacts (gitignored)
```

## Development Workflow

1. All changes go through feature branches (never commit directly to main)
2. Pre-commit gates: all tests pass + per-file 95%+ coverage + overall 97%+
3. Cascade handles branch names, commits, and merges via `/merge-pr`
4. Build logs and runtime metrics are generated under `output/` (gitignored)

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

- [AWS Greenfield Setup Guide](aws-setup-guide.md) — **New AWS environment from scratch (Cisco Duo SSO + Terraform)**
- [AWS Existing Environment Guide](aws-existing-environment-guide.md) — **Add OmniBOR build host to existing AWS infrastructure**
- [Technical Overview](../architecture/technical-overview.md) — High-level system overview
- [Workflow Guide](workflow-guide.md) — Detailed workflow descriptions
- [Golden File Testing](../testing/golden-file-testing.md) — Regression testing framework
- [SPDX FAQ](spdx-faq.md) — Common questions about SPDX output
- [Architecture README](../architecture/README.md) — System diagrams and technical overview
