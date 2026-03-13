# Golden File Regression Testing

This document describes the golden file regression testing framework used to
detect regressions in SPDX SBOM generation. It covers the purpose of golden
files, how they are structured, what the tests verify, and how to update them
when intentional changes are made.

---

## Table of Contents

1. [Purpose](#1-purpose)
2. [Directory Structure](#2-directory-structure)
3. [What Golden Files Contain](#3-what-golden-files-contain)
4. [What the Tests Verify](#4-what-the-tests-verify)
5. [What the Tests Ignore](#5-what-the-tests-ignore)
6. [Test Classes and Parameterization](#6-test-classes-and-parameterization)
7. [When to Update Golden Files](#7-when-to-update-golden-files)
8. [How to Update Golden Files](#8-how-to-update-golden-files)
9. [The _adg to _analyzed/_build Migration](#9-the-_adg-to-_analyzed_build-migration)
10. [Troubleshooting Test Failures](#10-troubleshooting-test-failures)

---

## 1. Purpose

Golden files serve as the **expected correct output** for SPDX generation.
When code changes are made to the SPDX emitter, version detector, or pipeline
logic, the regression tests compare freshly generated SBOMs against these
baselines to catch unintended changes in:

- Package detection (did we lose or gain a component?)
- Version extraction (did a version disappear or change?)
- Relationship types (did the dependency graph structure change?)
- Package counts (did the total component count shift?)

Without golden files, subtle regressions in the SPDX output — like a version
detector change that breaks detection for one library while improving another —
would go unnoticed until a manual review.

## 2. Directory Structure

```
tests/golden/spdx/
├── c-cpp/
│   ├── curl/
│   │   ├── curl_analyzed.spdx.json
│   │   ├── curl_build.spdx.json
│   │   ├── libcurl.so_analyzed.spdx.json
│   │   └── libcurl.so_build.spdx.json
│   ├── ffmpeg/
│   │   ├── ffmpeg_analyzed.spdx.json
│   │   ├── ffmpeg_build.spdx.json
│   │   ├── ffprobe_analyzed.spdx.json
│   │   ├── ffprobe_build.spdx.json
│   │   ├── libavcodec.so_analyzed.spdx.json
│   │   ├── libavcodec.so_build.spdx.json
│   │   ├── libavformat.so_analyzed.spdx.json
│   │   ├── libavformat.so_build.spdx.json
│   │   ├── libavutil.so_analyzed.spdx.json
│   │   ├── libavutil.so_build.spdx.json
│   │   ├── libswscale.so_analyzed.spdx.json
│   │   └── libswscale.so_build.spdx.json
│   ├── nmap/
│   │   ├── nmap_analyzed.spdx.json
│   │   ├── nmap_build.spdx.json
│   │   ├── ncat_analyzed.spdx.json
│   │   ├── ncat_build.spdx.json
│   │   ├── nping_analyzed.spdx.json
│   │   └── nping_build.spdx.json
│   └── redis/
│       ├── redis-server_analyzed.spdx.json
│       ├── redis-server_build.spdx.json
│       ├── redis-cli_analyzed.spdx.json
│       └── redis-cli_build.spdx.json
├── go/
│   └── lazygit/
│       ├── lazygit_analyzed.spdx.json
│       └── lazygit_build.spdx.json
├── java/
│   ├── checkstyle/
│   │   ├── checkstyle_analyzed.spdx.json
│   │   └── checkstyle_build.spdx.json
│   └── jsoup/
│       ├── jsoup_analyzed.spdx.json
│       └── jsoup_build.spdx.json
└── rust/
    ├── dura/
    │   ├── dura_analyzed.spdx.json
    │   └── dura_build.spdx.json
    └── oxipng/
        ├── oxipng_analyzed.spdx.json
        └── oxipng_build.spdx.json
```

**Naming convention:** `{binary}_{type}.spdx.json` where `{type}` is
`analyzed` or `build`.

**Organization:** `{language}/{repository}/` mirrors the output directory
structure.

**Current count:** 36 golden files (18 analyzed + 18 build) across 9
repositories and 4 languages.

## 3. What Golden Files Contain

Each golden file is a complete SPDX 2.3 JSON document, copied directly from a
verified analysis run. They contain:

- **Document metadata:** SPDX version, data license, document name/namespace
- **Packages:** All detected components with names, versions, PURLs, CPEs
- **Relationships:** STATIC_LINK, DYNAMIC_LINK, BUILD_TOOL_OF, DEPENDS_ON,
  CONTAINS
- **File entries:** Source files with checksums (for vendored libraries)
- **External references:** Package URLs and OmniBOR gitoid references

## 4. What the Tests Verify

The regression test framework in `tests/test_spdx_regression.py` performs
several levels of verification:

### Structural integrity (per golden file)

- File exists and is valid JSON
- Has a non-empty `packages` array
- No package names contain path artifacts like `../`
- Root package (first package) has version information

### Comparison against new output (when running full analysis)

The `_compare_summaries()` function checks:

| Check | Catches |
|-------|---------|
| Package count match | Gained or lost a component |
| Package name set match | Renamed or removed a specific package |
| Versioned package count | Version detection regression |
| Newly unversioned packages | A previously versioned package lost its version |
| Relationship type counts | Changed dependency graph structure |

### What a failure looks like

```
nmap: package count mismatch: golden=8, actual=7
nmap: missing packages: ['nsock']
nmap: versioned package count mismatch: golden=5, actual=4
nmap: newly unversioned packages: ['liblua']
nmap: STATIC_LINK relationship count mismatch: golden=7, actual=6
```

## 5. What the Tests Ignore

Golden file comparisons deliberately ignore fields that change between runs:

- **Document namespace** — contains a UUID that changes every run
- **Creation timestamp** — `created` field in `creationInfo`
- **File checksums** — SHA256 hashes change when upstream source is updated
- **Exact version strings** — the test checks *whether* a version exists, not
  its exact value (upstream may update between golden file refreshes)
- **Package ordering** — names are compared as sorted sets

This design means golden files do not need to be regenerated every time an
upstream project releases a new version. They only need updating when our
SPDX generation logic changes.

## 6. Test Classes and Parameterization

### Discovery

The `get_golden_files()` function auto-discovers all golden files by walking
the `tests/golden/spdx/` directory. It looks for files matching:

- `*_analyzed.spdx.json`
- `*_build.spdx.json`
- `*_adg.spdx.json` (legacy, for backward compatibility)

### Parameterized tests

Each golden file becomes a separate parameterized test case. With 36 golden
files and 3 test functions, this produces 108 individual test assertions:

```
tests/test_spdx_regression.py::test_golden_file_exists[c-cpp/nmap/nmap_analyzed.spdx.json]
tests/test_spdx_regression.py::test_golden_file_exists[c-cpp/nmap/nmap_build.spdx.json]
tests/test_spdx_regression.py::TestGoldenFileIntegrity::test_no_bogus_package_names[...]
tests/test_spdx_regression.py::TestGoldenFileIntegrity::test_root_package_has_version[...]
```

### Comparison API

For programmatic use (e.g., in CI or after an analysis run):

```python
from tests.test_spdx_regression import compare_against_golden

diffs = compare_against_golden(
    actual_spdx_path=Path("output/spdx/c-cpp/nmap/.../nmap_analyzed.spdx.json"),
    lang="c-cpp",
    repo="nmap",
    binary="nmap",
)
if diffs:
    print("Regressions found:")
    for d in diffs:
        print(f"  - {d}")
```

## 7. When to Update Golden Files

Golden files should be updated when:

1. **Version detector improvements** — new strategies find versions that were
   previously missing (e.g., liblua going from none to 5.4.8)
2. **SBOM structure changes** — like the _adg → _analyzed/_build split
3. **BUILD_TOOL_OF exclusion** — removing build tools from analyzed SBOMs
   changes package counts
4. **New repo added** — the first successful analysis creates the initial
   golden baseline
5. **Upstream project changes** — a vendored library is added or removed from
   the target project

Golden files should **NOT** be updated to make a failing test pass without
understanding why the output changed.

## 8. How to Update Golden Files

### Manual process (recommended)

1. Run the analysis on EC2:
   ```bash
   ssh omnibor-build "cd /home/ubuntu/omnibor-analysis && \
     docker compose -f docker/docker-compose.yml run --rm omnibor-env \
     python3 /workspace/app/analyze.py --repo <repo> --skip-clone"
   ```

2. Sync results locally:
   ```bash
   rsync -avz omnibor-build:/home/ubuntu/omnibor-analysis/output/spdx/<lang>/<repo>/<timestamp>/ \
     output/spdx/<lang>/<repo>/<timestamp>/
   ```

3. Review the output for correctness (check package names, versions,
   relationships)

4. Copy to golden directory:
   ```bash
   cp output/spdx/<lang>/<repo>/<timestamp>/<binary>_analyzed.spdx.json \
     tests/golden/spdx/<lang>/<repo>/
   cp output/spdx/<lang>/<repo>/<timestamp>/<binary>_build.spdx.json \
     tests/golden/spdx/<lang>/<repo>/
   ```

5. Run tests to verify:
   ```bash
   .venv/bin/python3 -m pytest tests/ -x -q
   ```

### Programmatic update

```python
from tests.test_spdx_regression import update_golden

update_golden(
    actual_spdx_path=Path("output/spdx/c-cpp/nmap/.../nmap_analyzed.spdx.json"),
    lang="c-cpp",
    repo="nmap",
    binary="nmap",
)
```

### Bulk update (after major changes)

After changes that affect all repos (like the version detector rewrite or the
analyzed/build split), re-run all repos and replace all golden files:

```bash
# Delete old golden files
find tests/golden/spdx -name '*_adg*' -delete

# Copy fresh analyzed + build files
for f in <binary list>; do
  cp output/spdx/<lang>/<repo>/<timestamp>/${f}_analyzed.spdx.json \
    tests/golden/spdx/<lang>/<repo>/
  cp output/spdx/<lang>/<repo>/<timestamp>/${f}_build.spdx.json \
    tests/golden/spdx/<lang>/<repo>/
done
```

## 9. The _adg to _analyzed/_build Migration

### History

The original SPDX generation produced a single file per binary with the
`_adg.spdx.json` suffix (ADG = Artifact Dependency Graph). This was replaced
by the two-file approach in March 2026.

### Migration steps taken

1. All 9 repos were re-run on EC2 with the new two-file generation
2. 17 old `_adg.spdx.json` golden files were deleted
3. 36 new `_analyzed.spdx.json` + `_build.spdx.json` golden files were created
4. Old `_adg.spdx.html` visualization files were also cleaned up
5. lazygit (Go) was added as a new golden baseline

### Backward compatibility

The test framework's `get_golden_files()` still matches `*_adg.spdx.json` and
the `compare_against_golden()` function falls back to `_adg` if no
`_analyzed` or `_build` file exists. This allows a gradual migration if needed,
though all current golden files use the new naming.

## 10. Troubleshooting Test Failures

### "Golden file missing"

A new binary was added to a repo's `output_binaries` but no golden file was
created. Run the analysis, verify output, and copy to
`tests/golden/spdx/<lang>/<repo>/`.

### "Package count mismatch"

The number of detected packages changed. This could be:
- A vendored library was added or removed upstream
- A change in the SPDX emitter logic affects package inclusion
- The `static_only` filter behavior changed

Check `git diff` on `app/spdx/emitter.py` and the target project's source tree.

### "Newly unversioned packages"

A package that previously had a version no longer does. This is a regression
in the version detector. Check `app/spdx/version_detector.py` for recent
changes that may have broken a strategy.

### "Relationship count mismatch"

The dependency graph structure changed. Common causes:
- New STATIC_LINK or DYNAMIC_LINK detection logic
- BUILD_TOOL_OF inclusion/exclusion changes
- New transitive dependency resolution

### Test count expectations

As of March 2026:
- **36 golden files** × 3 test functions = **108 parameterized golden tests**
- Plus ~500 unit/integration tests
- Total: **608 tests passing**

---

*Last updated: March 12, 2026*
