---
description: Merge a feature branch into main (execute after user approves the PR)
---

# Merge PR Workflow

Once the user explicitly approves merging a PR, execute **all** of the
following steps in sequence without pausing for confirmation between them.

## Prerequisites

- The user has explicitly approved the merge
- A PR exists on GitHub (required by Ruleset A — no direct push to main)
- All pre-commit gates have passed (tests, lint, coverage)

## Steps (execute all in one go)

// turbo
1. Merge via GitHub PR (squash merge, admin bypass for review requirement):
```bash
gh pr merge <PR_NUMBER> --squash --delete-branch --admin
```

The `--admin` flag bypasses the code review requirement (legacy branch
protection with `enforce_admins: false`). Ruleset A still enforces the
PR requirement — this does NOT allow direct pushes to main.

The `--delete-branch` flag removes the remote branch. GitHub's
`delete_branch_on_merge: true` setting also handles this automatically.

// turbo
2. Verify local main is up to date:
```bash
git pull origin main
```

// turbo
3. Verify merge:
```bash
git log --oneline -3
```

## Important

- **NEVER** merge without a PR — Ruleset A rejects direct pushes to main
- **NEVER** use `git merge` locally and push — this bypasses the PR requirement
- **NEVER** use `git push --force` — Ruleset A rejects force pushes
- If `gh pr merge` fails, check: is there a PR? Are tests passing?
- The `--admin` flag is ONLY for the repo owner (tedg-dev). Contributors
  must get 1 approving review before their PR is mergeable.

## Reference

See `.windsurf/rules/infrastructure/github-rulesets.md` for the full
branch protection configuration and rationale.
