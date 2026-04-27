---
description: Quality gates that must pass before every commit
trigger: always_on
priority: critical
---

# Pre-Commit Verification Gate

Every code change MUST pass ALL of these checks locally before committing,
creating a PR, or declaring work complete. No exceptions.

## Required Verification Steps (in order)

1. **Compile / import check** — zero errors
   - Python: `python -c "import app"` (or your package name)
   - Rust: `cargo check --workspace`
   - Go: `go build ./...`
   - Java: `mvn compile -q`
   - C/C++: `make -j$(nproc)` or `cmake --build build`

2. **Lint clean** — zero warnings treated as errors
   - Python: `flake8 app/ tests/` + `pylint app/`
   - Rust: `cargo clippy --workspace --all-targets -- -D warnings`
   - Go: `golangci-lint run ./...`
   - Java: `mvn checkstyle:check` or Spotless
   - C/C++: `clang-tidy` or project-specific linter

3. **Format clean** — zero diffs
   - Python: `black --check app/ tests/` or `ruff format --check`
   - Rust: `cargo fmt --all -- --check`
   - Go: `gofmt -l .` (should produce no output)
   - Java: `mvn spotless:check` or google-java-format
   - C/C++: `clang-format --dry-run --Werror`

4. **Tests pass** — full suite, no skips
   - Python: `.venv/bin/python3 -m pytest tests/ -x -q`
   - Rust: `cargo test --workspace`
   - Go: `go test ./...`
   - Java: `mvn test -q`
   - C/C++: `ctest --test-dir build`

5. **Coverage check** — meets project threshold
   - Report per-file and overall coverage percentages
   - If any file drops below threshold, add tests before committing

6. **No unused imports/variables** — warnings-as-errors catches these;
   fix them, do not suppress without a comment explaining why

## Rules

- NEVER commit code that does not compile or import
- NEVER commit code with lint errors that CI will catch
- NEVER skip these steps "to save time" — a broken CI push always
  costs more than running checks locally
- If ANY step fails, fix it before proceeding. Do not defer fixes
- Run formatting AFTER all code edits, then re-verify lint and tests

## Git Execution

Once all gates pass, execute git commands in a single chained step:

```bash
git add <files> && git commit -m "<message>" && git push origin <branch>
```

For merging, follow the project's merge workflow.
**No code may be committed without passing all verification gates.**
