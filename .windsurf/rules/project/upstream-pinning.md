---
description: Pin upstream Bisbom build tools to a specific official version
trigger: always_on
priority: critical
---

# Upstream Tool Pinning

This rule governs **build-time tooling** cloned into the Docker image
(`omnibor/bomsh` and any other upstream Bisbom-related repos). It is
distinct from `stable-tags.md` (which governs the *analyzed* repos in
`config.yaml`) and from the golden-file policy (which governs SPDX
baselines).

## Rule

Upstream tool repos MUST be pinned to a specific, official version in the
Dockerfile. NEVER clone from a moving branch (`master`, `main`) without
pinning. Always use the latest **official** version:

1. **If the repo publishes release tags**, pin to the latest release tag.
2. **If the repo has no tags/releases**, pin to a specific commit SHA of
   the default branch (the latest official commit).

Pin via a Dockerfile `ARG` declared once as a global ARG and re-declared
in each stage that uses it — a single source of truth across stages.

## Current pins

| Tool | Type | Value | As of |
|------|------|-------|-------|
| `omnibor/bomsh` | commit SHA (no tags exist) | `5823f7db7e5bd958e4ff868ae6ea79a7d871bb07` | 2024-10-31 |

`ARG BOMSH_COMMIT` in `docker/Dockerfile` is the single source of truth;
both the standalone and sidecar stages full-clone then
`git checkout "$BOMSH_COMMIT"`.

## Periodic update process

Check upstream occasionally for newer official versions (tags first, else
a newer default-branch commit). To bump a pin:

1. Update the `ARG` default in `docker/Dockerfile` (and this table).
2. Rebuild the Docker image.
3. Re-run EC2 golden validation on the largest repos.
4. Accept the bump ONLY if golden-clean. Report any diffs and stop.

## Defense-in-depth: fail-fast appliers

The regex appliers that monkey-patch upstream scripts
(`docker/patches/apply_fast_javap.py`, `docker/patches/apply_fast_io.py`)
MUST exit non-zero if any expected upstream function is not found. This
turns silent upstream drift into a loud build failure instead of shipping
an un-patched (or partially patched) script.

## Violations

- Cloning an upstream tool unpinned = **critical failure**.
- Bumping a pin without EC2 golden validation = **critical failure**.
- An applier that warns-and-continues on a missing function instead of
  failing the build = **critical failure**.
