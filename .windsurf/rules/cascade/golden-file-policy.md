---
description: Golden file / baseline policy — immutable baselines, user decides ALL updates
trigger: always_on
priority: critical
---

# Golden File / Baseline Policy

Golden SPDX files are **immutable baselines**. They exist solely to detect
changes caused by our code. They are NOT tracking upstream repos.

## Golden Files Are Project-Wide — One Baseline for ALL Variants

Golden files are the **single source of truth for the entire project**.
Every execution variant must produce structurally equivalent SPDX output
when compared against the same golden files:

- **Every OS**: Ubuntu, RHEL (Rocky Linux 9), Alpine 3.19
- **Every mode**: standalone (strace/ptrace), sidecar (dep:tree)
- **Every environment**: EC2, local Docker, CI

If a run on any OS or mode produces SPDX that differs from the golden
file, that is a **regression** that must be investigated and reported.
There are NO per-OS or per-mode golden files — the golden files are
OS-agnostic and mode-agnostic.

## Sidecar Mode Is the Authoritative Baseline

Golden files MUST be generated from **sidecar mode** (Phase 1 + Phase 2
on Ubuntu). Sidecar is the primary enterprise deployment mode — it
produces the ground-truth SPDX via build interception without requiring
SYS_PTRACE. All other variants (standalone, RHEL, Alpine) are then
compared against the sidecar-generated golden files to verify
structural equivalence.

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

## Authorized Exception: `omnibor` -> `bisbom` Rebrand (bounded)

The project rename from `omnibor` to `bisbom` is a **branding change, not a
content change**. Golden files that predate the rename keep the `omnibor`
spelling. The user has pre-approved the following two bounded behaviors —
they do NOT relax any other part of this policy.

### 1. Comparison normalization (keep it — do NOT re-baseline)

`scripts/compare_golden.py` and `scripts/compare_java_golden.py` apply
`_normalize_branding()` (`omnibor` -> `bisbom`) to **both** the golden
baseline and the new candidate at load time. Because the identical
substitution is applied to both sides, it can only mask the rename in
names (repo/package/`SPDXID`/path/download location) — it can **never**
hide a real content difference, since any genuine divergence survives the
same substitution on both sides. This lets pre-rename goldens compare
equal to post-rename output **without re-baselining**. Do NOT remove this
normalization and do NOT edit goldens merely to change the name.

### 2. One-time testapp golden replacement (content-identity gated)

The Java testapp directory rename (`omnibor-java-testapp` ->
`bisbom-java-testapp`) is the **single** case where a golden file may be
replaced with the `bisbom`-named version. This is permitted ONLY after a
real run whose comparison shows the content we care about (package set,
versions, file set, checksums, relationships, external refs) is identical
**modulo the `omnibor`<->`bisbom` name**. Cascade MUST show the user the
comparison output first. This exception applies to this ONE repo only; it
does not authorize any other golden update.

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
