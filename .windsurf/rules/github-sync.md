# GitHub Issue/Milestone Sync Rule

Any architectural or design change made during implementation MUST be
reflected in GitHub Issues and/or Milestones immediately.

## CRITICAL: Planning is verified against gambit, never assumed

Before making, stating, or acting on ANY planning claim (a plan, status,
gate, dependency, Walk, or whether an issue exists), Cascade MUST check the
live `CiscoSecurityServices/gambit` issues and the Corona board (`#255`)
via `gh` (authenticated as `tedg_cisco`). The files under `docs/planning/`
— including `README.md` and `github-issues-crosswalk.md` — are **mirrors,
not the source of truth**, and may be stale. **NEVER GUESS** and never
substitute the planning docs for a live gambit query.

**gambit is authoritative.** Whenever planning and gambit diverge, sync
them in the same turn:

- **Plan in `docs/planning/` but not in gambit** → create the gambit
  issue/sub-issue (parent link, current Walk, `Build-Instrumented SBOM`
  epic), then record it in `github-issues-crosswalk.md`.
- **Gambit issue not in the planning docs** → add/update the row in
  `README.md`, the matching per-language planning doc, and the crosswalk.
- **Status, scope, or acceptance criteria differ** → update the mirror to
  match gambit (gambit wins).

Query pattern (read-only, safe):

```bash
gh auth switch --user tedg_cisco
gh project item-list 255 --owner CiscoSecurityServices --format json -L 1500 \
  -q '.items[]|select(.content.number>=11000 and .content.number<=11013)|"\(.content.number) [\(.status)] \(.content.title)"'
```

See also `workflow/github-issue-management.md` for field ids, status
pairing, Walk assignment, and epic assignment.

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
