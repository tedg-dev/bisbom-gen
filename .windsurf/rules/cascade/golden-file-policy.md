---
description: Golden file / baseline approval policy — NEVER update without user approval
trigger: always_on
priority: critical
---

# Golden File / Baseline Policy

Applies to any project that uses known-good output files (golden files,
snapshots, baselines) for regression testing.

## Rule: ALL Differences Require User Review

When comparing new output against golden files or previous runs:

1. **Report EVERY difference** — no matter how small (counts, names,
   versions, types, structural changes)
2. **Do NOT assume** any difference is benign, expected, or caused by
   upstream changes
3. **Do NOT update golden files** until the user has reviewed all diffs
   and explicitly approved
4. **Do NOT dismiss** differences with phrases like "likely upstream"
   or "within tolerance"

## What to Report

For each file compared, provide:

- Exact metric changes (old → new) for all key counts
- Any added, removed, or changed entries
- Any changed versions, checksums, or metadata
- Side-by-side summary of what specifically changed

## Workflow

1. Run regression tests
2. If tests pass with zero diffs → report "identical, no changes"
3. If ANY diffs exist → **STOP and report all diffs to user**
4. Wait for explicit user approval before updating golden files
5. Only after approval: copy new output to golden folder and re-run tests

## Violations

- Updating golden files without user approval is a **critical violation**
- Dismissing or minimizing differences without investigation is a
  **critical violation**

## Applicability

This policy applies to:

- SPDX SBOM golden files
- API response snapshots
- CLI output baselines
- Configuration template baselines
- Any file used as a regression reference
