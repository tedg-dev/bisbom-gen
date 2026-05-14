# Metadata Collection Pipeline Integration

**Date:** 2026-02-26
**PR:** #20

## Summary

Integrated `collect_metadata.py` and `collect_dynamic_libs.py` into the
official `analyze.py` pipeline as a new `MetadataCollector` step. Previously,
these scripts had to be run manually between the build and ADG SPDX
generation steps. Now they execute automatically.

## Problem

After the instrumented build with bomtrace3, two manual steps were required
before the ADG SPDX generator could produce accurate SBOMs:

1. **`collect_metadata.py`** — resolves system files in the bomsh treedb to
   dpkg packages with full metadata (name, version, source, maintainer)
2. **`collect_dynamic_libs.py`** — identifies dynamic library dependencies
   per binary using `ldd` and `readelf`, resolves to dpkg packages

Without these, `AdgSpdxStep` would fail with:
```
[ERROR] component_metadata.json not found. Run collect_metadata.py first.
```

## Solution

New `MetadataCollector` class in `analyze.py` that runs as step 5b in the
pipeline, between the OmniBOR SPDX generation (5a) and ADG SPDX (5c):

```
Step 4:  Instrumented build (bomtrace3)
Step 5a: Generate SPDX from OmniBOR (bomsh_sbom.py)
Step 5b: Collect component metadata + dynamic libs  ← NEW
Step 5c: Generate per-binary ADG SPDX
Step 6:  Validate SPDX documents
```

### MetadataCollector.collect() behavior

1. **Checks for treedb** — if the bomsh treedb doesn't exist (build failed),
   skips with a warning and returns False
2. **Runs collect_metadata.py once** — reads treedb, resolves system files to
   dpkg packages, writes `component_metadata.json` to the metadata dir.
   Skips if the file already exists (idempotent).
3. **For each output binary:**
   - Creates per-binary metadata dir (`metadata/<bin_name>/`)
   - Copies `component_metadata.json` into the per-binary dir
   - Runs `collect_dynamic_libs.py` with the binary path
   - Writes `dynamic_libs.json` to the per-binary dir
   - Skips if `dynamic_libs.json` already exists (idempotent)
4. **Error handling** — catches exceptions from either script, logs the error,
   and continues. Returns False only if metadata collection itself fails.

### Idempotency

Both metadata and dynamic lib collection are idempotent — they skip if their
output files already exist. This means re-running the analysis won't redo
collection unnecessarily, but you can force re-collection by deleting the
output files.

## Pipeline Integration

`MetadataCollector` is wired into `AnalysisPipeline` as a new component:

```python
self.metadata_collector = (
    metadata_collector
    or MetadataCollector(self.runner)
)
```

And invoked in `main()` after the build succeeds:

```python
# Step 5b: Collect component metadata + dynamic libs
if success:
    pipeline.metadata_collector.collect(
        args.repo, repo_cfg, paths_cfg,
    )
```

## Tests

5 new tests in `TestMetadataCollector`:
- No treedb → returns False
- Full collection with mocked scripts → metadata + dynlibs called
- Skips existing dynamic_libs.json (idempotent)
- Binary not found → warns and continues
- collect_metadata failure → returns False

349 tests pass, 98% overall coverage.

## Files Changed

- `app/analyze.py` — new `MetadataCollector` class, wired into
  `AnalysisPipeline` and `main()` as step 5b
- `tests/test_analyze.py` — 5 new tests, updated `_mock_pipeline` helper
