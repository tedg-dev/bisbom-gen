# Windsurf Configuration for omnibor-analysis

This document describes all `.windsurf/` rules and workflows configured for this workspace.

> **AI Model:** This project was developed and tested using **Claude Opus 4.6 (Thinking)** in Windsurf Cascade.
> It is strongly recommended for onboarding and development. Other models may not follow
> the `.windsurf/` rules correctly.

## Rules (auto-loaded every Cascade session)

Rules in `.windsurf/rules/` are automatically injected into every Cascade conversation when this folder is opened in Windsurf.

### Project-Specific Rules

| File | Purpose |
|------|---------|
| `project-context.md` | Architecture overview, target repos, technologies, file naming conventions, key constraints |
| `docker-rules.md` | Container requirements (SYS_PTRACE, seccomp), volume mounts, Dockerfile maintenance guidance |
| `omnibor-rules.md` | OmniBOR/Bomsh terminology, workflow sequence, key paths inside the container |

### General Rules

| File | Purpose |
|------|---------|
| `credentials.md` | No hardcoded secrets; use env vars for API keys and GitHub tokens |
| `secrets-in-chat.md` | Never display tokens, API keys, or passwords in Cascade chat output |
| `command-execution.md` | No `cd` commands (use Cwd), sequential git ops, always use `python3` |
| `code-quality.md` | Run tests before PRs, fix pre-existing lint/test failures, meta-rule for recording new rules |
| `reasoning.md` | Always explain reasoning before making changes; break complex problems into steps |
| `user-interaction.md` | Don't prompt unless there is a real choice to make; proceed autonomously on routine ops |
| `pr-workflow.md` | PR-first workflow, conventional branch naming, no direct commits to main |
| `markdown-formatting.md` | List and code block formatting conventions |

## Workflows (invoked via `/slash-command`)

Workflows in `.windsurf/workflows/` are invoked on demand via slash commands or when Cascade determines one is relevant.

### `/setup-environment`

**File:** `setup-environment.md`

Startup checklist — run when opening the workspace:

1. Verify Docker is running
2. Check if the omnibor-analysis Docker image exists
3. Verify key project files (config.yaml, analyze.py, spdx_from_adg.py, Dockerfile)
4. Check which repos are cloned
5. Check for existing output artifacts
6. Check for existing docs/reports

### `/docker-build`

**File:** `docker-build.md`

Build or rebuild the Docker container:

1. `docker-compose -f docker/docker-compose.yml build`
2. Verify bomtrace3 is available inside the container
3. Enter the container interactively

First build takes 10-20 minutes (compiles bomtrace2/bomtrace3 from patched strace source).

### `/run-analysis`

**File:** `run-analysis.md`

Run OmniBOR build interception analysis on a target repository:

1. List available repos from config.yaml
2. Run full analysis: clone, bomtrace3 instrumented build, ADG, SPDX, docs
3. Re-run without cloning (repo already exists)

Output locations:
- ADG: `output/omnibor/{lang}/{repo}/{ts}/`
- SPDX: `output/spdx/{lang}/{repo}/{ts}/<binary>_adg.spdx.json`
- HTML: `output/spdx/{lang}/{repo}/{ts}/<binary>_adg.spdx.html`
- Build log: `output/build-logs/{lang}/{repo}/{ts}/build.md`
- Runtime metrics: `output/runtime/{lang}/{repo}/{ts}/runtime.md`

`{lang}` is `c-cpp`, `rust`, or `go`. `{ts}` is `YYYY-MM-DD_HHMM`.

### `/add-repo`

**File:** `add-repo.md`

Add a new target repository (C/C++, Rust, or Go):

1. Add repo entry to `app/config.yaml` (URL, branch, language, build steps, output binaries)
2. Add build dependencies to `docker/Dockerfile` (C/C++ only — Rust and Go deps are fetched at build time)
3. Rebuild Docker image if Dockerfile changed
4. Run analysis (output directories are created automatically)

---

*Last updated: 2026-03-09*
