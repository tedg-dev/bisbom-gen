# Test Coverage Improvements: Per-File 95%+, Overall 97%+

**Date:** 2026-02-26
**PR:** #19 (commit 2 of 3)

## Summary

Raised test coverage from 95% overall to **98%**, and established stricter
coverage gates: every source file must have **95%+ individual coverage** and
the overall project must maintain **97%+ coverage**. Two previously
under-covered files were brought up to standard.

## Coverage Before and After

| File | Before | After | Delta |
|---|---|---|---|
| `app/spdx_visualize.py` | **83%** | **100%** | +17% |
| `app/analyze.py` | **90%** | **99%** | +9% |
| `app/add_repo.py` | 98% | 98% | — |
| `app/compare.py` | 100% | 100% | — |
| `app/data_loader.py` | 99% | 99% | — |
| `app/spdx_from_adg.py` | 96% | 96% | — |
| **Overall** | **95%** | **98%** | **+3%** |

Total tests: **344** (up from 311).

## New Test File: `tests/test_spdx_visualize.py`

Created from scratch with 18 tests covering:

### `TestExtractGraph` (10 tests)
- Empty document handling
- Root-only package (APPLICATION purpose → "root" group)
- STATIC_LINK targets → "static" group
- DYNAMIC_LINK targets → "dynamic" group
- BUILD_TOOL_OF sources → "build" group
- Unrelated packages → "other" group
- CONTAINS relationship counting (file counts)
- Edge filtering (DESCRIBES and CONTAINS are excluded)
- Edges only between known packages (non-package IDs skipped)
- Full integration: root + static + dynamic + build
- Version and comment preservation

### `TestGenerateHtml` (5 tests)
- Output file creation and return value
- HTML contains D3.js script reference
- HTML contains document name
- HTML contains graph data (package names, relationship types)
- Parent directory auto-creation

### `TestMain` (2 tests)
- Default output path (`.spdx.json` → `.spdx.html`)
- Explicit `-o` output path

## New Tests in `tests/test_analyze.py`

Added 12 tests in 4 new test classes:

### `TestVersionDetection` (7 tests)
Covers all branches of `_bomsh_version()` and `_bomtrace_version()`:
- ver + commit → `"0.0.1-5823f7d"`
- commit only → `"git-abc1234"`
- ver only → `"0.0.1"`
- empty output → graceful handling
- bomtrace3 found with version string
- bomtrace3 not in PATH
- strings command failure / no version match

### `TestSpdxValidatorCoverage` (3 tests)
- Schema validation success path (fetch + validate → PASS)
- More than 10 schema errors (truncation in summary output)
- More than 10 semantic errors (truncation in summary output)

### `TestAdgSpdxStep` (3 tests)
- No output_binaries → returns `[]`
- Full generate path with vendored_dirs
- direct_only=True when shared lib in output_binaries list

### `TestMainAdgValidation` (1 test)
- ADG files get validated alongside the main SPDX file

## Remaining Uncovered Lines (4 lines in `analyze.py`)

Lines 524-525 and 690-691 are `except Exception` handlers for:
- OmniBOR ref injection failure (malformed logfile)
- HTML visualization generation failure

These are defensive exception handlers deep in the SpdxGenerator pipeline
that would require full end-to-end pipeline mocking to trigger. The cost of
test fragility outweighs the coverage gain.

## Updated Pre-Commit Rules

`.windsurf/rules/pre-commit.md` now enforces:

1. **Per-file coverage**: every `app/*.py` file must have **95%+** coverage
2. **Overall coverage**: must be **97%+**
3. Report both per-file and overall numbers before committing

Previous rule was a single 95% overall threshold with no per-file enforcement.

## Files Changed

- `tests/test_spdx_visualize.py` — new file, 18 tests
- `tests/test_analyze.py` — 12 new tests in 4 classes
- `.windsurf/rules/pre-commit.md` — stricter coverage gates
