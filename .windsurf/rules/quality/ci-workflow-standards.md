---
description: CI/CD pipeline design and GitHub Actions standards
trigger: always_on
priority: high
---

# CI/CD Workflow Standards

All GitHub Actions workflows MUST follow these practices.

## Required Elements

- **concurrency group**: Every workflow must have a `concurrency` block that
  cancels in-progress runs on the same branch
- **permissions**: Scope permissions to the minimum required (e.g.,
  `contents: read`). Never use `permissions: write-all`
- **paths-ignore**: Workflows that build/test code should use `paths-ignore`
  to skip docs-only changes (`.md`, `.png`, `.drawio`, `docs/`)
- **pinned actions**: Pin third-party actions to full SHA, not mutable tags
  (e.g., `actions/checkout@<sha>` not `actions/checkout@v4`)

## Pipeline Design

- **Fail fast**: lint/check jobs run first; test jobs `needs: lint` so
  they don't waste compute on broken code
- **Matrix strategy**: test across supported versions (Python 3.11+3.13,
  Go 1.21+1.22, etc.) when applicable
- **Cache aggressively**: cache dependency directories keyed on lockfile
  hashes to reduce CI time
- **Artifact uploads**: upload test reports, coverage, and build artifacts
  for debugging failed runs

## Branch Protection

- Require passing CI checks before merge
- Require at least one approval on PRs
- Use squash merges for feature branches to keep main history linear
- Delete branches after merge

## Release Automation

- Tag releases with semantic versions (`v1.2.3`)
- Generate changelogs from conventional commit messages
- Automate artifact publishing in CI (not locally)

## Language-Specific CI Notes

See `lang/*.md` for language-specific CI configuration (toolchain pinning,
cache paths, lint commands). The general principles above apply to all
languages.
