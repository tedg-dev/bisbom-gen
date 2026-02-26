---
description: Rules for pre-commit quality gates and git execution
---

# Pre-Commit Quality Gates

Before committing any code changes, Cascade **must** complete the following gates in order:

## 1. Run Full Regression Tests

- Run the complete test suite — no skipping, no partial runs
- All tests must pass before proceeding
- If any test fails, fix the issue and re-run the full suite before committing

## 2. Verify Code Coverage

- Overall code coverage must be **97% or higher**
- Every individual source file in `app/` must have **95% or higher** coverage
- If overall coverage drops below 97% or any file drops below 95%, add or improve tests before committing
- Report the per-file and overall coverage percentages to the user

## 3. Single-Step Git Execution

Once tests pass and coverage is verified, execute **all** git commands in a single
chained step. Do not pause between commands or ask for confirmation between them.

For feature branch work:
```bash
git add <files> && git commit -m "<message>" && git push origin <branch>
```

For merging (after user approval), follow the `/merge-pr` workflow — all merge,
push, and cleanup commands in one execution step.

# Summary

The commit flow is:
1. Full regression tests → all pass
2. Code coverage check → per-file 95%+, overall 97%+
3. Git add + commit + push → single command execution

**No code may be committed without passing gates 1 and 2.**
