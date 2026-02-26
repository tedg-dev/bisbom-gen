---
description: Reminder to stop cloud compute resources when done for the day
---

# Cloud Compute Shutdown Reminder

At the **end of every work session** (when the user says they're done, wrapping up,
or about to close/sleep their laptop), Cascade **must**:

1. Read `.windsurf/rules/infrastructure/active-profile.md` for the user's provider
2. Use the **Power Management** commands from that profile to remind the user

If the active profile shows **Provider: Local**, skip this reminder (no cost).

> **Don't forget to stop your build server!**
> Check your active infrastructure profile for the shutdown command.

## When to Trigger

- User says "done for the day", "wrapping up", "going to sleep", "signing off", etc.
- User says they're closing or sleeping their laptop
- End of a long session where cloud compute was used

## Why This Matters

- Cloud VMs charge per hour/minute even when idle
- The OmniBOR analysis container only needs to run during active analysis
- Stopping the VM preserves disk state; destroying it saves all costs
- Always verify no analysis is in progress before stopping

## Where to Find Shutdown Commands

The user's specific shutdown commands are in:

```
.windsurf/rules/infrastructure/active-profile.md → Power Management section
```

If that file doesn't exist, remind the user to set one up:

```
cp .windsurf/rules/infrastructure/templates/<provider>.md \
   .windsurf/rules/infrastructure/active-profile.md
```
