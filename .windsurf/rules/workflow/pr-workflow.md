---
description: Rules for pull request and branch workflow
---

# PR-First Workflow

- **Never** commit directly to `main` (sole exception: initial repo bootstrap via `/github-init` workflow).
- Always work on a feature branch and merge via PR.
- Cascade chooses branch names (user has delegated this).
- Use conventional prefixes: `fix/`, `feat/`, `chore/`, `docs/`, `test/`

# Branch Work Requires Explicit User Approval to Merge

- **DO NOT create a PR or merge to main/master unless the user explicitly asks**
- When working on a feature branch, keep changes on that branch until user approves
- The user may want to review, test, or discard the branch work
- Only proceed with PR creation and merge when the user gives explicit instruction

# Naming Conventions

- Cascade is authorized to choose branch names without asking
- Use descriptive, conventional branch names:
  - `fix/descriptive-issue`
  - `feat/new-feature`
  - `chore/maintenance-task`
  - `docs/update-documentation`
  - `version-bump/X.Y.Z` (for version bumps only)
