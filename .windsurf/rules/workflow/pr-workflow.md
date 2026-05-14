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

# GitHub Branch Enforcement

Branch protection uses a **hybrid approach**: Ruleset A enforces the PR
requirement for everyone, and legacy branch protection handles code review
with admin bypass for CLI merges. See `infrastructure/github-rulesets.md`
for full details and rationale.

## Ruleset A: Core Protection (no bypass — applies to everyone)

| Rule | Effect |
|------|--------|
| **Require PR** | No direct pushes to `main` — everyone must use a PR |
| **Block force push** | `git push --force` is rejected server-side |
| **Block deletion** | `main` cannot be deleted |
| **Linear history** | Only squash/rebase merges (clean linear history) |
| **Resolve conversations** | All review threads must be resolved before merge |

**No bypass actors.** The repo owner is subject to all rules above.

## Legacy Branch Protection: Code Review

| Rule | Effect |
|------|--------|
| **1 approving review** | Contributors must get at least one code review |
| **Dismiss stale reviews** | New pushes invalidate previous approvals |
| **`enforce_admins: false`** | Owner can bypass review via `--admin` flag |

The owner merges via `gh pr merge <number> --squash --delete-branch --admin`.
Contributors must get 1 approving review before the PR is mergeable.

## What This Means in Practice

- **Repo owner (tedg-dev)**: must create a PR, can merge without review
- **Contributors**: must create a PR AND get 1 approval before merging
- **Nobody**: can push directly to `main`, force-push, or delete `main`
- **Cascade**: must always use feature branches and PRs (per project rules)
