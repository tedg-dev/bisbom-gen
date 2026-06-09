# Golden File Changelog Policy

Every golden file update MUST be accompanied by a changelog entry in
`tests/golden/spdx/README.md`.

## When Golden Files Are Updated

1. **Add a dated changelog entry** to `tests/golden/spdx/README.md`
2. Each entry MUST include:
   - **Date** of the update
   - **PR number** that triggered the update (the PR containing the
     golden file changes)
   - **Root cause PR(s)** — which code/config changes caused the SPDX
     output to differ from the previous golden files
   - **Repos affected** — which repos had golden files updated
   - **Summary of changes** — exact counts (packages, files,
     relationships) and what changed (versions, added/removed entries)
   - **Reason for approval** — why the user approved the update
3. The changelog entry MUST be in the **same commit** as the golden
   file changes

## When Comparing Runs to Golden Files

1. **ALWAYS** compare output against golden files after every
   successful run
2. **ALWAYS** report every diff with root cause analysis
3. **ALWAYS** check `tests/golden/spdx/README.md` changelog to
   determine if a known diff is expected from a recent update
4. **NEVER** update golden files without adding a changelog entry
5. **NEVER** update golden files without explicit user approval

## Changelog Entry Format

```markdown
### YYYY-MM-DD — PR #NNN: Brief description

**Root cause:** PR #NNN (description of code change)

| Repo | File | Change |
|------|------|--------|
| repo-name | file.spdx.json | description of diff |

**Approved by:** user (reason for approval)
```
