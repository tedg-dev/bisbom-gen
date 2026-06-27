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
| **[guides/](guides/)** | Setup, onboarding, contributing, AWS infrastructure, workflow guide |
| **[architecture/](architecture/)** | System design diagrams (draw.io + PNG), pipeline overview, app architecture |
| **[features/](features/)** | Feature documentation: phase isolation, analyzed vs. build SBOMs, vendored detection |
| **[deep-dive/](deep-dive/)** | Engineering deep-dives. Generic, cross-language sidecar + phase-isolation design stays at the top level; per-language design detail lives in `java/`, `c-cpp/`, `go/`, `rust/`, `python/` subfolders |
| **[planning/](planning/)** | Issue & sub-issue planning. Living index at [planning/README.md](planning/README.md); generic umbrella docs at the top level; per-language sub-issues in `java/`, `c-cpp/`, etc. |
| **[testing/](testing/)** | Golden file regression testing, test strategy, multi-distro testing |
| **[issues/](issues/)** | Upstream bomsh/bomtrace bug reports and workarounds |
| **[_archived/](_archived/)** | Historical documents preserved for reference (not current) |

## Generated Artifacts (not in docs/)

Build logs and analysis output are generated per-run and live under
`output/` (gitignored):

| Path | Contents |
|------|----------|
| `output/build-logs/{lang}/{repo}/{ts}/` | Build environment logs |
| `output/spdx/{lang}/{repo}/{ts}/` | SPDX SBOMs + HTML visualizations |
| `output/omnibor/{lang}/{repo}/{ts}/` | OmniBOR ADG documents |
| `output/binaries/{lang}/{repo}/{ts}/` | Compiled output binaries |

**Path convention:** `{lang}` is `c-cpp`, `rust`, `go`, or `java`.
`{ts}` is `YYYY-MM-DD_HHMM`.
