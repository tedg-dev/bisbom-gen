---
description: Pre-commit quality gates — tests, coverage, lint, format
trigger: always_on
priority: critical
---

# Pre-Commit Verification Gate

Every code change MUST pass ALL of these checks locally before committing,
creating a PR, or declaring work complete. No exceptions.

## Required Verification Steps (in order)

1. **Compile / import check** — zero errors
   `.venv/bin/python3 -c "import app"`

2. **Lint clean** — zero warnings treated as errors
   `.venv/bin/python3 -m flake8 app/ tests/`

3. **Tests pass** — full suite, no skips
   `.venv/bin/python3 -m pytest tests/ -x -q`

4. **Coverage check** — meets project threshold
   - **Overall project**: ≥97% line coverage
   - **Individual source files**: ≥95% line coverage
   - Report per-file and overall coverage to the user
   - If any file drops below threshold, add tests before committing

5. **No unused imports/variables** — fix them, do not suppress

## Rules

- NEVER commit code that does not compile or import
- NEVER commit code with lint errors that CI will catch
- NEVER skip these steps "to save time"
- If ANY step fails, fix it before proceeding. Do not defer fixes
- Run formatting AFTER all code edits, then re-verify lint and tests

## Git Execution

Once all gates pass:

```bash
git add <files>
git commit -m "<message>"
git push origin <branch>
```

**No code may be committed without passing all verification gates.**

## Meta-Rule: Record New Rules

Any time a new rule or process requirement is introduced, persist it
in `.windsurf/rules/` in the same PR. This applies to rules requested
by the user AND rules Cascade determines are necessary.
