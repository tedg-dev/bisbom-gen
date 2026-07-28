---
description: Run OmniBOR build interception analysis on a target repository
---

# Run Analysis

Instrument a C/C++ build with bomtrace3 or build a Go project with
`go build`, then generate SPDX SBOMs with dependency visualization.

## Prerequisites

- Docker image must be built (run `/docker-build` workflow first)
- Target repo must be defined in `app/config.yaml` (run `/add-repo` to add new ones)
- Must be running on a Linux x86_64 host (local or remote)
- Infrastructure profile must be set up (see `.windsurf/rules/infrastructure/active-profile.md`)

## 0. Read infrastructure profile

Before running analysis, read the active profile to get SSH alias, repo path, and
sync commands for the user's build host:

```bash
cat .windsurf/rules/infrastructure/active-profile.md
```

Use the **SSH alias** and **Repo path on host** from the profile in all commands below.
If **Provider** is `Local`, skip SSH prefixes and run Docker commands directly.

## 1. Run full analysis

**Local Docker host (Provider: Local):**

```bash
docker-compose -f docker/docker-compose.yml run --rm bisbom-env \
  python3 /workspace/app/analyze.py --repo <REPO_NAME>
```

**Remote host (Provider: DigitalOcean, AWS, etc.):**

The remote repo is kept in sync via **rsync** (it is NOT a git
clone), so sync the code first, then run.  Use the SSH alias and
repo path from the active profile:

```bash
rsync -avz --exclude=.git --exclude=.venv --exclude=repos --exclude=output ./ <SSH_ALIAS>:<REPO_PATH>/
ssh <SSH_ALIAS> "cd <REPO_PATH> && docker compose -f docker/docker-compose.yml run --rm --remove-orphans bisbom-env python3 /workspace/app/analyze.py --repo <REPO_NAME>"
```

## 1b. Java sidecar mode (dep:tree, no SYS_PTRACE)

Java repos are analyzed with the `bisbom-sidecar` service in
**sidecar mode** — dependency capture via `mvn`/`gradle`
`dependency:tree`, which does not require `SYS_PTRACE`:

```bash
docker compose -f docker/docker-compose.yml run --rm --remove-orphans bisbom-sidecar \
  python3 /workspace/app/analyze.py --repo <REPO_NAME> --mode sidecar
```

## 2. Re-run without cloning (repo already exists)

```bash
docker compose -f docker/docker-compose.yml run --rm --remove-orphans bisbom-env \
  python3 /workspace/app/analyze.py --repo <REPO_NAME> --skip-clone
```

## 3. Generate only a Syft manifest SBOM (no build)

```bash
docker-compose -f docker/docker-compose.yml run --rm bisbom-env \
  python3 /workspace/app/analyze.py --repo <REPO_NAME> --syft-only
```

## 4. List available repos

```bash
docker-compose -f docker/docker-compose.yml run --rm bisbom-env \
  python3 /workspace/app/analyze.py --list
```

## 5. Sync results locally (REQUIRED for remote hosts)

**After every successful remote analysis, always sync results back.**
See `.windsurf/rules/workflow/sync-results.md` for the full rule.

```bash
rsync -avz <SSH_ALIAS>:<REPO_PATH>/output/ output/
```

Never report analysis as complete until the sync succeeds.
All generated artifacts (SBOMs, build-logs, runtime metrics) are under `output/`.

## What happens during analysis

### C/C++ repos (8 steps)
1. **Clone** — shallow clone of the target repo
2. **Syft baseline** — manifest-based SPDX SBOM for comparison
3. **Validate deps** — checks `apt_deps` are installed in the container
4. **Instrumented build** — `bomtrace3 make` intercepts compiler/linker calls
5a. **SPDX generation (bomsh)** — `bomsh_sbom.py` creates SPDX SBOM from ADG data
5b. **Metadata collection** — `collect_metadata.py` resolves system files to dpkg packages; `collect_dynamic_libs.py` identifies dynamic libs per binary
5c. **ADG SPDX generation** — per-binary SPDX with vendored detection, version extraction, dynamic lib resolution + HTML visualization
6. **SPDX validation** — JSON Schema + semantic validation of all generated SBOMs
7. **Binary collection** — copies `output_binaries` to `output/binaries/<lang>/<repo>/`
8. **Docs** — timestamped build log and runtime metrics

### Go repos (bomtrace2 instrumented build)
1. **Clone** — shallow clone of the target repo
2. **Syft SBOM** — manifest-based baseline (go.mod/go.sum)
4. **Instrumented build** — `bomtrace2 -c bomtrace_go.conf go build -a` (watches compile, link + openat)
5a. **OmniBOR SPDX** — generated from ADG via bomsh_sbom.py
5b. **Metadata collection** — component metadata
5c. **ADG SPDX** — per-binary SPDX + HTML visualization
6. **SPDX validation** — JSON Schema + semantic validation
7. **Binary collection** — copies output binaries
8. **Docs** — timestamped build log and runtime metrics

## Output locations

All output uses a consistent `{category}/{lang}/{repo}/{ts}/` folder structure.
The `<lang>` comes from the repo's `language` field in config.yaml (e.g. `c-cpp`, `go`).
The `<ts>` timestamp is generated once per run and shared across all output types.

| Artifact | Path |
|----------|------|
| OmniBOR ADG | `output/omnibor/<lang>/<repo>/<ts>/` |
| Component metadata | `output/omnibor/<lang>/<repo>/<ts>/metadata/component_metadata.json` |
| Dynamic libs (per binary) | `output/omnibor/<lang>/<repo>/<ts>/metadata/<binary>/dynamic_libs.json` |
| SPDX SBOM (OmniBOR) | `output/spdx/<lang>/<repo>/<ts>/<repo>_omnibor.spdx.json` |
| SPDX SBOM (ADG, per binary) | `output/spdx/<lang>/<repo>/<ts>/<binary>_adg.spdx.json` |
| Visualization (per binary) | `output/spdx/<lang>/<repo>/<ts>/<binary>_adg.spdx.html` |
| SPDX SBOM (Syft) | `output/spdx/<lang>/<repo>/<ts>/<repo>_syft.spdx.json` |
| Output binaries | `output/binaries/<lang>/<repo>/<ts>/` |
| Build log | `output/build-logs/<lang>/<repo>/<ts>/build.md` |
| Runtime metrics | `output/runtime/<lang>/<repo>/<ts>/runtime.md` |
