# Stash Discipline

## Rule: Never Leave Stashed Work Behind

If Cascade stashes the user's work (via `git stash`), Cascade MUST
unstash it before ending its turn. The user should never have to
manually recover stashed changes.

### Required Sequence

1. `git stash push -m "reason" -- <files>`
2. Do whatever branch/pull operation required the stash
3. Switch back to the user's original branch
4. `git stash pop`
5. Verify the working tree is restored

All five steps MUST happen in the same turn. Never stop after step 2.

### Why

- The user may have other AI conversations or manual edits in progress
- Stashed changes are invisible and easy to forget
- Forcing the user to run `git stash list` and `git stash pop` manually
  is a workflow disruption that Cascade caused

### Alternatives to Stashing

Before stashing, consider whether the operation can be done without it:

- `git pull --rebase` on the current branch (no stash needed if on the
  right branch)
- `git fetch origin main` without switching branches
- Read-only operations (`git log`, `git rev-list`) never need a stash

### Multi-Conversation Awareness

Cascade is not the only agent working on the repo. Other AI
conversations or the user may have uncommitted changes at any time.
Never assume the working tree is "ours" to manipulate freely.
