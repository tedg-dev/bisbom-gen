---
description: Golden file / baseline policy — immutable baselines, user decides ALL updates
trigger: always_on
priority: critical
---

# Golden File / Baseline Policy

Golden SPDX files are **immutable baselines**. They exist solely to detect
changes caused by our code. They are NOT tracking upstream repos.

## Absolute Rule: Cascade NEVER Updates Golden Files

No code change, upstream change, bomsh update, or any other reason
justifies Cascade updating a golden file. The user makes ALL update
decisions — no exceptions.

## When Diffs Are Found

1. **Report EVERY difference** — no matter how small (counts, names,
   versions, types, structural changes)
2. Report exact paths to both golden and proposed files
3. Report ALL diffs: package counts, versions, relationships,
   added/removed packages
4. **STOP and wait for user review**
5. The **user decides** whether to update — not Cascade

## What Is NOT a Valid Reason to Suggest Updating Golden Files

- Upstream repo released a new version
- Upstream added/removed dependencies
- bomsh/bomtrace upstream changed behavior
- Our SPDX emission code changed
- Re-running on a new date or new container
- Docker image rebuild
- **Any other reason — there are NO exceptions**

## Pinned Repos Requirement

All repos in `config.yaml` MUST use pinned release tags (or commit
SHAs for repos without tags). Golden files are generated from pinned
versions and must remain stable. The `--skip-clone` flag must not
bypass the pinned version.

## Treedb Contamination Prevention

bomtrace3 treedb persists in `/tmp/` between builds. When running
multiple repos sequentially, clean treedb between each run:

```bash
rm -f /tmp/bomsh_hook_raw_logfile* /tmp/bomsh_createbom* /tmp/treedb_*
# PRESERVE /tmp/bomsh_hook2.py — required by bomtrace3
```

Failure to clean between runs causes cross-repo package leakage
in SPDX output (e.g., Rust crates appearing in C builds).

## Violations

- Updating golden files without explicit user approval = **critical failure**
- Suggesting golden file updates as routine = **critical failure**
- Dismissing diffs for any reason = **critical failure**
- Running multiple repos without treedb cleanup = **critical failure**

## Applicability

This policy applies to:

- SPDX SBOM golden files (`tests/golden/spdx/{lang}/{repo}/`)
- API response snapshots
- CLI output baselines
- Configuration template baselines
- Any file used as a regression reference
