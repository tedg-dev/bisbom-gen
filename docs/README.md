# Documentation

## Start Here

| Document | Who | Purpose |
|----------|-----|---------|
| [ONBOARDING.md](guides/ONBOARDING.md) | New contributors | First-day setup, environment, workflows |
| [CONTRIBUTING.md](guides/CONTRIBUTING.md) | All contributors | Branch workflow, PR process, code style |
| [Architecture README](architecture/README.md) | All contributors | System diagrams and technical overview |

## Directory Guide

| Directory | Contents |
|-----------|----------|
| **[guides/](guides/)** | Setup, onboarding, contributing, AWS infrastructure |
| **[architecture/](architecture/)** | System design diagrams (draw.io + PNG), pipeline overview, app architecture |
| **[features/](features/)** | Feature documentation: Go support, SPDX comparison, vendored detection, etc. |
| **[issues/](issues/)** | Upstream bomsh/bomtrace bug reports and workarounds |
| **[deep-dive/](deep-dive/)** | Research, performance analysis, enterprise integration, optimization proposals |

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
