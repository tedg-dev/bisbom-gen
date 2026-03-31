---
description: Check for OmniBOR/bomsh updates before running analysis
---

# OmniBOR Version Check

Before running a new repository analysis, the pipeline SHOULD check for
updates to the upstream OmniBOR/bomsh repository.

## Current Pinned Version

| Component | Repository | Pinned Commit/Tag | Last Checked |
|-----------|------------|-------------------|--------------|
| bomsh | omnibor/bomsh | master (HEAD) | 2026-03-27 |

## Check Logic

At the start of each analysis session (not every repo run):

1. Query GitHub API: `GET /repos/omnibor/bomsh/releases/latest`
2. Compare the latest release tag against the pinned version in Dockerfile
3. If a newer release exists:
   - **STOP** the analysis run
   - Report the version difference to the user
   - Ask if they want to update before proceeding

## Implementation

The check is performed by `app/pipeline/version_checker.py` and called from
the analysis pipeline's initialization phase.

## When to Skip

- If `--skip-version-check` flag is passed
- If running in CI/CD (detected via `CI` environment variable)
- If the check was performed within the last 24 hours (cached)

## Updating bomsh

When the user approves an update:

1. Update the git clone command in `docker/Dockerfile`
2. Rebuild the Docker image: `docker compose build`
3. Run a quick smoke test on a known-good repo (e.g., curl)
4. Commit the Dockerfile change

## Why This Matters

bomsh is under active development. New releases may include:
- Bug fixes for edge cases we've encountered
- Support for new languages or build systems
- Performance improvements
- Breaking changes that require pipeline updates
