# GitHub Issue/Milestone Sync Rule

Any architectural or design change made during implementation MUST be
reflected in GitHub Issues and/or Milestones immediately.

## When to Update GitHub

- **New pattern established** (e.g., BUILD_TOOL_OF emission) → create
  issues for applying it to other languages/tracks
- **Design decision changed** (e.g., removing a heuristic) → update
  affected issues' descriptions and acceptance criteria
- **Upstream dependency resolved** → remove `upstream-dep` label,
  update issue body
- **Acceptance criteria evolved** (e.g., golden file comparison added)
  → update issue checklists
- **Scope expanded** (e.g., multi-module support) → add to issue or
  create new sub-issue
- **Blocker removed** → update dependent issues immediately

## What to Update

- Issue descriptions (acceptance criteria, design references)
- Milestone descriptions (if scope changed)
- Labels (add/remove `upstream-dep`, `blocker`)
- Create NEW issues when a pattern established in one language needs
  replication in others
- Close issues when work is done — never leave stale open issues

## NEVER

- Make an architectural change without checking if it affects open issues
- Complete a milestone's work without verifying all issues are current
- Leave `upstream-dep` or `blocker` labels on resolved dependencies
- Assume issue descriptions are still accurate — verify before starting
