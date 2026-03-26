---
description: Rules for code quality, testing, and fixing failures
---

# Testing Before PR

- Run tests before creating PRs when code changes are involved
- Coverage must meet the project's configured threshold

# Fix Pre-Existing Failures

- **All pre-existing lint failures must be corrected** — do not leave or ignore them
- **All pre-existing test failures must be corrected** — failing tests block CI
- When encountering failures, fix the root cause rather than disabling or skipping
- If a fix is non-trivial, create a dedicated PR to address it before other work

# Secrets

- Never commit credential files (e.g., `keys.json`, `.env` with secrets)
- Prefer fine-grained PATs where possible

# Meta-Rule: Record New Rules

- **Any time a new rule or process requirement is introduced** (CI, release, branching, coverage, security, etc.), it must be stored in the appropriate `.windsurf/rules/` or `.windsurf/workflows/` file in the same PR
- This applies to rules requested by the user AND rules that Cascade/AI determines are necessary to remember for future invocations
- New rules must be persisted so they survive across Cascade sessions
