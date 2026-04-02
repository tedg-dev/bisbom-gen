---
description: NEVER update golden files or dismiss differences without explicit user approval
trigger: always_on
priority: critical
---

# Golden File Approval — MANDATORY

## Rule: ALL differences require user review

When comparing new analysis output against golden SPDX files or previous runs:

1. **Report EVERY difference** — no matter how small (package counts, relationship
   counts, names, versions, relationship types, any structural change)
2. **Do NOT assume** any difference is benign, expected, or caused by upstream changes
3. **Do NOT update golden files** until the user has reviewed all diffs and explicitly approved
4. **Do NOT dismiss** differences with phrases like "likely upstream" or "within tolerance"

## What to report

For each SPDX file compared, provide:

- Exact package count (old → new)
- Exact relationship count (old → new)
- Any added/removed/changed package names
- Any added/removed/changed relationship types
- Any changed versions, checksums, or metadata
- Side-by-side summary of what specifically changed

## Workflow

1. Run regression tests
2. If tests pass with zero diffs → report "identical, no changes"
3. If ANY diffs exist → **STOP and report all diffs to user**
4. Wait for explicit user approval before updating golden files
5. Only after approval: copy new output to golden folder and re-run tests

## Violations

Updating golden files without user approval is a **critical violation**.
Dismissing or minimizing differences without investigation is a **critical violation**.
