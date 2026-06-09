---
description: Always sync results locally after successful remote analysis
---

# Sync Results After Remote Analysis

After every successful analysis run on a remote build host, **always** sync
output back to the local machine before reporting completion.

## Required sync commands

Read the active infrastructure profile to get the SSH alias and repo path,
then run:

```bash
rsync -avz <SSH_ALIAS>:<REPO_PATH>/output/ output/
```

All generated artifacts (SBOMs, build-logs, runtime metrics, binaries) are
under `output/`. The `docs/` directory contains only hand-written documentation
and does not need syncing.

## Rules

1. **Never skip sync.** If the analysis succeeded, sync results immediately.
2. **Sync `output/` only.** All timestamped run artifacts live there.
3. **Report sync status.** Confirm to the user that results are available locally.
4. **On sync failure**, retry once. If it fails again, alert the user.
5. This rule does **not** apply when running analysis locally (Provider: Local).
