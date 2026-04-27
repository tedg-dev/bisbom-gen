---
description: Testing philosophy, isolation, coverage, and regression policy
trigger: always_on
priority: critical
---

# Testing Standards

Every project MUST have a comprehensive test suite. Tests are not optional
and are never deferred to "later."

## Philosophy

1. **Tests are documentation** — a well-written test explains how the code
   is intended to be used better than any comment
2. **Tests are a safety net** — they catch regressions before users do
3. **Tests enable refactoring** — without tests, refactoring is guessing

## Coverage Requirements

- **Overall project**: ≥95% line coverage (configurable per project)
- **Individual source files**: ≥90% line coverage
- **New code**: 100% of new public functions must have at least one test
- Report coverage to the user after every test run

## Test Isolation

- Each test MUST be independent — no shared mutable state between tests
- Tests MUST pass in any order (`pytest --randomly` / `cargo test` / `go test -shuffle`)
- Use temporary directories for file I/O, not fixed paths
- Mock all external I/O: subprocess calls, network requests, file system
  access to paths outside the test sandbox

## Test Organization

- Mirror the source tree: `app/spdx/emitter.py` → `tests/test_emitter.py`
- Group tests by class under test using test classes
- Name tests descriptively: `test_parse_dep_tree_handles_optional_scope`
- Separate unit tests from integration tests (unit tests run without Docker,
  network, or external services)

## What to Test

| Layer | What to verify | Isolation method |
|-------|---------------|-----------------|
| Pure functions | Input → output correctness | Direct calls |
| Classes with I/O | Behavior with mocked dependencies | `unittest.mock` / `mockall` / `gomock` |
| CLI entry points | Argument parsing, exit codes | Subprocess or in-process with captured stdout |
| Config loading | Schema validation, defaults, error cases | Temp files with known content |
| Error paths | Graceful failure messages, no crashes | Force errors via mocks |

## What NOT to Test

- Third-party library internals (test your usage of them, not their code)
- Private implementation details that may change (test public API behavior)
- Exact log message wording (test that logging occurs, not the exact string)

## Regression Testing

- When a bug is found, write a failing test FIRST, then fix the bug
- Regression tests must reference the issue or describe the scenario
- Never delete a regression test without explicit user approval

## Golden File / Baseline Testing

- When comparing output against known-good baselines (golden files):

  1. Report EVERY difference — no matter how small
  2. Do NOT assume any diff is benign
  3. Do NOT update golden files without explicit user approval
  4. Provide a side-by-side summary of what changed

- Updating golden files without approval is a **critical violation**

## Pre-Existing Failures

- All pre-existing test failures MUST be fixed — do not ignore them
- All pre-existing lint failures MUST be corrected
- If a fix is non-trivial, create a dedicated PR before other work
- Never disable or skip a failing test to "unblock" a feature

## Continuous Integration

- The full test suite MUST run on every PR
- CI failures block merge — no exceptions
- Flaky tests must be fixed immediately, not retried or skipped
