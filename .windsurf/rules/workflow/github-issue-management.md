---
description: GitHub issue management conventions (account, parent/sub-issue status pairing, Walk assignment, planning-doc sync, new-work sub-issues, epic assignment)
---

# GitHub Issue Management

Conventions for managing the gambit issue tracker and the Corona project
board. These are mandatory and complement `../github-sync.md` (which
covers keeping issue *content* accurate) and `pr-workflow.md` (PRs).

---

## 1. Account and Location

**GitHub Issues access is ALWAYS available — it is NOT intermittent.**
NEVER claim issue access is unavailable or limited, and NEVER defer
creating an issue to the planning crosswalk as a substitute. The
crosswalk mirrors the live board; it is never a stand-in for it.

- **Issues** live under `CiscoSecurityServices/gambit` on github.com
  (migrated from the former `tedg-cisco` org).
- **All issue operations** (view, edit, status, labels, project board)
  MUST use the `gh` account `tedg_cisco`. The default active account
  `tedg-dev` CANNOT resolve the gambit repo. Before any `gh issue` or
  `gh api .../gambit/...` call, run:

  ```bash
  gh auth switch --user tedg_cisco
  ```

- **PRs** live in `tedg-dev/omnibor-analysis` and use the `tedg-dev`
  account. Always reference PRs cross-repo as
  `tedg-dev/omnibor-analysis#<n>` — never a bare `#<n>`.
- **Project board:** Corona, project number `255`, node id
  `PVT_kwDOEFp5Ds4Bb7Wk`.
- **Status field** id `PVTSSF_lADOEFp5Ds4Bb7WkzhWoAck`, single-select
  options:

  | Status | Option id |
  |--------|-----------|
  | Proposed | `eda0e242` |
  | Ready | `aa3a0c5a` |
  | In Development | `91c2dd1e` |
  | Blocked | `e3d7f4ba` |
  | In Review | `e524005e` |
  | Ready to Demo | `808db7d3` |
  | Done | `98236657` |

  Status ordering (least → most advanced): Proposed → Ready →
  In Development → In Review → Ready to Demo → Done (Blocked is
  orthogonal). "In Progress" is not a board status — it means
  **In Development**.

- **Epic** is the single-select field, id
  `PVTSSF_lADOEFp5Ds4Bb7WkzhWoAdU`; the option `Build-Instrumented SBOM`
  has id `e3a04db3` (note the option name is singular "SBOM"). See §5
  for the mandatory epic-assignment rule. Assign with the status command
  form below, substituting the Epic field id and option id.

- **Walk** is the sprint/iteration field, id
  `PVTIF_lADOEFp5Ds4Bb7WkzhWoNhw` (type iteration). The **current Walk**
  is the iteration whose date range includes today. List iterations
  with:

  ```bash
  gh api graphql -f query='query{node(id:"PVTIF_lADOEFp5Ds4Bb7WkzhWoNhw"){... on ProjectV2IterationField{configuration{iterations{id title startDate duration}}}}}'
  ```

  The first entry in `configuration.iterations` is the current/active
  Walk (completed Walks live under `completedIterations`). Assign an
  item to a Walk with:

  ```bash
  gh project item-edit --project-id PVT_kwDOEFp5Ds4Bb7Wk \
    --id <PVTI_item_id> \
    --field-id PVTIF_lADOEFp5Ds4Bb7WkzhWoNhw \
    --iteration-id <iteration_id>
  ```

  Set status with:

  ```bash
  gh project item-edit --project-id PVT_kwDOEFp5Ds4Bb7Wk \
    --id <PVTI_item_id> \
    --field-id PVTSSF_lADOEFp5Ds4Bb7WkzhWoAck \
    --single-select-option-id <option_id>
  ```

  The per-issue `PVTI_...` item id comes from
  `gh project item-list 255 --owner CiscoSecurityServices --format json`
  filtered by `.content.number`.

---

## 2. Parent / Sub-Issue Status Pairing (MANDATORY)

Parent issues MUST always be kept in sync with their sub-issues'
statuses. There is NO convention of leaving a parent behind while its
children advance, and NO convention of letting a parent run ahead of
them. The parent's status is **derived** from the aggregate of its
sub-issue statuses.

**Governing principle: a parent's status equals the LEAST-ADVANCED
status among all its sub-issues.** A parent may only reach a given
stage once EVERY sub-issue has reached at least that stage. It never
advances ahead of its least-advanced child. (Floor: before any child
starts, a parent may be `Proposed`; as soon as ANY child is `Ready` or
`In Development`, the parent is at least `Ready`.) Concretely:

- **At least one sub-issue is `Ready`/`In Development` but any sub-issue
  is still below `In Development`** (`Proposed`/`Ready`) → parent is
  `Ready`.
- **EVERY sub-issue is `In Development` or beyond** (none below
  `In Development`) → parent is `In Development`.
- **EVERY sub-issue is `In Review` or beyond** → parent is `In Review`.
- **EVERY sub-issue is `Ready to Demo` or beyond** → parent is
  `Ready to Demo`.
- **EVERY sub-issue is `Done`** → parent is `Done`.

The higher tiers are just as binding as the lower ones: a parent does
NOT move to `In Review` until ALL of its sub-issues are at `In Review`
or beyond — even if every child but one is already there. The single
least-advanced child dictates the parent's status.

**Walk assignment on transition to In Development.** Whenever ANY issue
or sub-issue reaches `In Development` — whether moved up from `Ready` or
created directly at `In Development` (see §4) — it MUST be assigned to
the **current Walk** (the active iteration of the `Walk` field) in the
same turn. This applies to parents too: when the parent-pairing rule
above moves a parent to `In Development`, assign that parent to the
current Walk as well. Use the Walk assignment command in §1.

**Whenever you change a sub-issue's status, re-evaluate and update the
parent in the same turn.** Verify the true sub-issue set from GitHub —
not a planning doc — via:

```bash
gh api graphql -f query='query{repository(owner:"CiscoSecurityServices",name:"gambit"){issue(number:<PARENT>){subIssues(first:50){nodes{number title state}}}}}'
```

Combine that with the board statuses from `gh project item-list` to
compute the correct parent status.

---

## 3. Planning Documents Must Stay Current (MANDATORY)

Every document under `docs/planning/` — especially
`docs/planning/github-issues-crosswalk.md` and
`docs/planning/README.md` — MUST be kept up to date whenever issues,
sub-issues, PRs, or statuses change. The crosswalk is the single source
that maps each Main issue and sub-issue to its implementing PR(s) and
GitHub number.

When any of the following happen, update the relevant planning doc(s)
in the same turn (and same PR when code is involved):

- A new issue or sub-issue is created → add it to the crosswalk and the
  README index with its number, parent, status, and design-doc link.
- A PR merges → move the row to the PR crosswalk with `Merged`.
- A status changes → reflect it.
- Scope, parent link, or acceptance criteria change → reflect it.

Refresh the doc's `Last updated` date on every edit. A stale planning
doc (e.g. a sub-issue missing from the crosswalk) is a rule violation.

---

## 4. New Work From Bugs or Pivots Needs a Sub-Issue First (MANDATORY)

Any NEW or ADDITIONAL work discovered mid-stream — a bug, a required
refactor, a design pivot, or scope not covered by the current
sub-issue — MUST get its own GitHub sub-issue created and moved to
`In Development` **before** implementation work begins.

- The new sub-issue MUST be linked to the correct parent Main issue.
- The new sub-issue MUST also be assigned to the `Build-Instrumented
  SBOM` epic (§5) — the epic assignment is orthogonal to the parent
  link; both always hold.
- Do NOT fold unrelated new work into an existing sub-issue's scope.
- After creating and setting the sub-issue to `In Development`, assign
  it to the current Walk (§2), set its epic (§5), apply the
  parent-pairing rule in §2, and update the planning docs per §3.

This guarantees every unit of work is tracked and visible on the board
before code is written, not retroactively.

---

## 5. Every Issue Belongs to the Build-Instrumented SBOM Epic (MANDATORY)

EVERY issue and sub-issue in this workstream — whether created by us or
inherited — MUST have its board **Epic** field set to `Build-Instrumented
SBOM`. This is independent of, and in addition to, the parent/sub-issue
link: a sub-issue is attached to its Main issue AND carries the epic.

Set the epic with:

```bash
gh project item-edit --project-id PVT_kwDOEFp5Ds4Bb7Wk \
  --id <PVTI_item_id> \
  --field-id PVTSSF_lADOEFp5Ds4Bb7WkzhWoAdU \
  --single-select-option-id e3a04db3
```

When creating any new issue, set the epic in the same turn as creating
it. There is NO exception — do not leave the Epic field empty.

---

## 6. Every New Issue Gets Priority and Assignee (MANDATORY)

In the SAME turn as creating any issue or sub-issue — alongside Status,
Walk (§2), and Epic (§5) — ALWAYS set two more fields:

- **Priority** = `Med` (option id `b4c7e1fe`) unless the user specifies
  otherwise. The Priority field id is `PVTSSF_lADOEFp5Ds4Bb7WkzhWoAdY`
  (options: High `2aae35bc`, Med `b4c7e1fe`, Low `12ea92e6`). Set it with
  the same `gh project item-edit` form shown for Status/Epic in §1.
- **Assignee** = the user, `tedg_cisco`:

  ```bash
  gh issue edit <n> --repo CiscoSecurityServices/gambit --add-assignee tedg_cisco
  ```

**Verify the status stuck.** After setting Status (e.g. `In Development`),
re-query and confirm it actually took — board status edits have silently
no-op'd before, leaving a freshly created issue with no status. Never
assume the edit succeeded; confirm via GraphQL or `gh project item-list`.
