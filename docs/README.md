# Documentation

## Start Here

| Document | Who | Purpose |
|----------|-----|---------|
| [ONBOARDING.md](guides/ONBOARDING.md) | New contributors | First-day setup, environment, workflows |
| [CONTRIBUTING.md](guides/CONTRIBUTING.md) | All contributors | Branch workflow, PR process, code style |
| [Architecture README](architecture/README.md) | All contributors | System diagrams and technical overview |
| [SPDX Output FAQ](guides/spdx-faq.md) | All contributors | Why SPDX output looks the way it does — relationship types, versions, two-file approach |

## Directory Guide

| Directory | Contents |
|-----------|----------|
| **[sidecar/](sidecar/)** | All sidecar + phase isolation docs, diagrams, and per-language design. General docs at root; language-specific in `java/`, `c-cpp/`, `go/`, `rust/`, `python/`. Peer/user-facing docs sit at each language root; deep-detail design/decision docs live in that language's `reference/` subfolder |
| **[reference/](reference/)** | Project-wide, language-agnostic reference material (schemas, contracts) — e.g. the [`build_profile` schema](reference/build-profile-schema.md) |
| **[architecture/](architecture/)** | General app architecture, technical overview, standalone mode, platform support |
| **[guides/](guides/)** | Setup, onboarding, contributing, AWS infrastructure, workflow guide |
| **[planning/](planning/)** | Issue & sub-issue planning. Living index at [planning/README.md](planning/README.md); per-language sub-issues in `java/`, `c-cpp/`, etc. |
| **[testing/](testing/)** | Golden file regression testing, test strategy, multi-distro testing |
| **[issues/](issues/)** | Upstream bomsh/bomtrace bug reports and workarounds |
| **[_archived/](_archived/)** | Historical documents preserved for reference (not current) |

## Generated Artifacts (not in docs/)

Build logs and SBOM output are generated per-run and live under
`output/` (gitignored):

| Path | Contents |
|------|----------|
| `output/build-logs/{lang}/{repo}/{ts}/` | Build environment logs |
| `output/spdx/{lang}/{repo}/{ts}/` | SPDX SBOMs + HTML visualizations |
| `output/omnibor/{lang}/{repo}/{ts}/` | ADG documents (build provenance) |
| `output/binaries/{lang}/{repo}/{ts}/` | Compiled output binaries |

**Path convention:** `{lang}` is `c-cpp`, `rust`, `go`, or `java`.
`{ts}` is `YYYY-MM-DD_HHMM`.
