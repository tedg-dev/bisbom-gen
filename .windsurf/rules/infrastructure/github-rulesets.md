---
description: GitHub Repository Rulesets configuration for branch protection
trigger: always_on
priority: critical
---

# GitHub Repository Rulesets

Branch protection on `tedg-dev/bisbom-gen` is enforced via **GitHub
Repository Rulesets** (not legacy branch protection rules). Rulesets provide
granular per-rule bypass actors, replacing the all-or-nothing
`enforce_admins` toggle.

---

## Ruleset A: Core Protection

| Field | Value |
|-------|-------|
| **Name** | Core Protection |
| **ID** | 16035780 |
| **Target** | `refs/heads/main` |
| **Enforcement** | Active |
| **Bypass actors** | None — applies to everyone |

### Rules

| Rule | Parameters | Effect |
|------|-----------|--------|
| `pull_request` | `required_approving_review_count: 0`, `required_review_thread_resolution: true` | Everyone must use a PR (no direct push to `main`) |
| `non_fast_forward` | — | Force pushes are server-side rejected |
| `deletion` | — | `main` branch cannot be deleted |
| `required_linear_history` | — | Only squash/rebase merges (linear history) |

**Key point:** This ruleset has **no bypass actors**. The repo owner cannot
push directly to `main`. A pull request is always required.

---

## Legacy Branch Protection: Code Review

The code review requirement uses **legacy branch protection** (not a
second ruleset) because GitHub Ruleset bypass actors do not work via the
`gh` CLI or REST/GraphQL API — they only work through the GitHub web UI
merge button. Legacy branch protection with `enforce_admins: false` allows
the repo owner to merge via CLI using `gh pr merge --admin`.

| Setting | Value | Effect |
|---------|-------|--------|
| `required_approving_review_count` | 1 | Contributors need 1 approval |
| `dismiss_stale_reviews` | true | New pushes invalidate previous approvals |
| `require_last_push_approval` | false | Not used (conflicts with CLI admin merge) |
| `enforce_admins` | **false** | Owner can bypass review via `--admin` flag |

**Why `enforce_admins: false` is safe:** Ruleset A (no bypass actors)
still prevents direct pushes to `main`. The admin bypass only applies to
the review requirement in legacy branch protection, not to the PR
requirement in the ruleset.

### Merging as owner (CLI)

```bash
gh pr merge <number> --squash --delete-branch --admin
```

The `--admin` flag bypasses the legacy branch protection review
requirement. Ruleset A's PR requirement is still enforced — the owner
cannot push directly to `main`.

### Merging as contributor

Contributors cannot use `--admin`. They must get 1 approving review
before the PR is mergeable.

---

## Repository Settings

| Setting | Value |
|---------|-------|
| `allow_merge_commit` | true |
| `allow_squash_merge` | true |
| `allow_rebase_merge` | true |
| `delete_branch_on_merge` | true |

Merged feature branches are automatically deleted by GitHub.

---

## Net Effect

| Actor | Must use PR | Must get review | Can force push | Can delete `main` |
|-------|-------------|-----------------|----------------|-------------------|
| **tedg-dev (owner)** | Yes | No (`--admin`) | No | No |
| **Contributors** | Yes | Yes (1 approval) | No | No |
| **Cascade AI** | Yes (per project rules) | Yes (per project rules) | No | No |

---

## Why This Hybrid Approach

Pure rulesets would be ideal, but GitHub has a limitation: **Ruleset bypass
actors do not work via the CLI/API** — only through the web UI merge
button. This means `gh pr merge` cannot trigger a bypass actor exemption.

The hybrid approach uses:

- **Ruleset A** (no bypass) → enforces PR requirement for everyone
- **Legacy branch protection** (`enforce_admins: false`) → enforces
  review for contributors, allows owner to bypass via `--admin`

The ruleset prevents direct pushes (which `enforce_admins: false` would
normally allow), so the net effect is correct: owner must use PRs but
can skip reviews.

---

## Managing Rulesets

### View current rulesets

```bash
gh api repos/tedg-dev/bisbom-gen/rulesets --jq '.[] | {id, name, enforcement}'
```

### View ruleset details

```bash
gh api repos/tedg-dev/bisbom-gen/rulesets/<ID> --jq '.'
```

### View legacy branch protection

```bash
gh api repos/tedg-dev/bisbom-gen/branches/main/protection --jq '{enforce_admins: .enforce_admins.enabled, reviews: .required_pull_request_reviews}'
```

### Disable a ruleset (emergency only)

```bash
gh api repos/tedg-dev/bisbom-gen/rulesets/<ID> -X PUT --input <json> # set enforcement: disabled
```

### Add a CI status check (future)

When CI workflows exist, add a `required_status_checks` rule to Ruleset A:

```json
{
  "type": "required_status_checks",
  "parameters": {
    "required_status_checks": [
      {"context": "test", "integration_id": null},
      {"context": "lint", "integration_id": null}
    ],
    "strict_required_status_checks_policy": true
  }
}
```

---

## History

| Date | Change | Reason |
|------|--------|--------|
| 2026-05-06 | Created Ruleset A + legacy branch protection | Hybrid approach: ruleset enforces PR requirement, legacy BP handles review with admin bypass for CLI merges |
