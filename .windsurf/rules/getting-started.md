---
description: First-time setup instructions for new contributors using Windsurf Cascade
---

# Getting Started with OmniBOR Analysis

This rule provides context for Cascade AI when a new contributor opens this project
for the first time in Windsurf IDE.

## First Session Checklist

When a new user opens this project, Cascade should:

1. **Read all rules** in `.windsurf/rules/` to load project conventions
2. **Read all workflows** in `.windsurf/workflows/` to understand available commands
3. **Run `/setup-environment`** to verify the local development environment
4. **Explain the project** — this is an OmniBOR build interception pipeline that
   generates SPDX 2.3 SBOMs from instrumented C/C++ builds
5. **Offer to run `/add-repo`** if the user wants to analyze a new GitHub repository

## Recommended Cascade Model

For best results with this codebase, use **Claude Opus 4** or newer. The pipeline
involves complex multi-step analysis with SPDX generation, vendored dependency
detection, and D3.js visualization — larger models handle this better.

To set the model in Windsurf:
- Open Settings → Cascade → Model
- Select Claude Opus 4 (or latest available)

## What This Project Does

1. Takes any C/C++ GitHub repository
2. Instruments the build with bomtrace3 (ptrace-based interception)
3. Captures every compiler/linker invocation
4. Generates SPDX 2.3 SBOMs with:
   - Vendored static libraries (STATIC_LINK)
   - Dynamic system libraries (DYNAMIC_LINK)
   - Build tools (BUILD_TOOL_OF)
   - Automatic version detection for vendored libs
5. Produces interactive D3.js HTML dependency graphs
6. Optionally compares against proprietary binary scanner SBOMs

## Quick Start for New Users

Tell Cascade:
- "Add [repo name] for analysis" → runs `/add-repo` workflow
- "Run analysis on [repo]" → runs `/run-analysis` workflow
- "Compare SBOMs for [repo]" → runs `/run-comparison` workflow
- "Build the Docker container" → runs `/docker-build` workflow

## Infrastructure Options

The Docker container requires **Linux x86_64** with ptrace support. Options:

| Option | Pros | Cons |
|--------|------|------|
| **AWS EC2** (recommended for Cisco) | Terraform IaC, fast builds | Duo SSO re-auth every 1 hour |
| **Local Linux x86_64** | Fastest, no network | Must have Docker installed |
| **DigitalOcean Droplet** | Simple, cheap | Slower than EC2 compute-optimized |
| **WSL2 on Windows** | Free, local | Requires Windows + WSL2 + Docker |

### Cisco Engineers: AWS EC2 with Duo SSO

For Cisco employees, the recommended path is AWS EC2 with Terraform:

- Full setup guide: `docs/guides/aws-setup-guide.md`
- Terraform IaC: `terraform/` directory
- Authentication: Cisco Duo SSO → SAML → AWS STS (1-hour sessions)
- CLI tools needed: `aws`, `terraform`, `duo-sso`
- Infrastructure profile template: `.windsurf/rules/infrastructure/templates/aws-ec2.md`

The project is designed to work with any Linux x86_64 host — Docker handles the environment.
