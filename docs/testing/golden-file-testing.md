# Golden File Regression Testing

Golden files are known-good SPDX output files stored in the repository
as regression baselines. New pipeline output is compared against these
files to detect unintended changes in package detection, version
extraction, relationship types, and component counts.

---

## Table of Contents

1. [Directory Structure](#1-directory-structure)
2. [What Golden Files Contain](#2-what-golden-files-contain)
3. [Comparison Tool](#3-comparison-tool)
4. [What the Tests Verify](#4-what-the-tests-verify)
5. [What the Tests Ignore](#5-what-the-tests-ignore)
6. [Test Classes and Parameterization](#6-test-classes-and-parameterization)
7. [Workflow: Updating Golden Files](#7-workflow-updating-golden-files)
8. [Adding Golden Files for a New Repo](#8-adding-golden-files-for-a-new-repo)
9. [Troubleshooting Test Failures](#9-troubleshooting-test-failures)

---

## 1. Directory Structure

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

**Naming:** `{binary}_{type}.spdx.json` where `{type}` is `analyzed`
or `build`.

**Organization:** `{language}/{repository}/` mirrors the output
directory structure.

## 2. What Golden Files Contain

Each golden file is a complete SPDX 2.3 JSON document, copied directly
from a verified analysis run:

- **Document metadata** — SPDX version, data license, document
  name/namespace
- **Packages** — all detected components with names, versions, PURLs,
  CPEs
- **Relationships** — `STATIC_LINK`, `DYNAMIC_LINK`, `BUILD_TOOL_OF`,
  `DEPENDS_ON`, `CONTAINS`
- **File entries** — source files with checksums (for vendored
  libraries)
- **External references** — Package URLs and OmniBOR gitoid references

## 3. Comparison Tool

```bash
python3 scripts/compare_golden.py tests/golden/spdx output/spdx
```

The script reports: package count changes, missing/extra packages,
version changes, relationship count changes, added/removed
relationships, and external reference changes.

## 4. What the Tests Verify

The regression test framework in `tests/test_spdx_regression.py`
performs several levels of verification:

### Structural integrity (per golden file)

- File exists and is valid JSON
- Has a non-empty `packages` array
- No package names contain path artifacts like `../`
- Root package (first package) has version information

### Comparison against new output

| Check | Catches |
|-------|---------|
| Package count match | Gained or lost a component |
| Package name set match | Renamed or removed a specific package |
| Versioned package count | Version detection regression |
| Newly unversioned packages | A previously versioned package lost its version |
| Relationship type counts | Changed dependency graph structure |
| Relationship endpoints | Source → target pair changes |
| External references | PURL or CPE changes |

### What a failure looks like

```text
nmap: package count mismatch: golden=8, actual=7
nmap: missing packages: ['nsock']
nmap: versioned package count mismatch: golden=5, actual=4
nmap: newly unversioned packages: ['liblua']
nmap: STATIC_LINK relationship count mismatch: golden=7, actual=6
```

## 5. What the Tests Ignore

Golden file comparisons deliberately ignore fields that change between
runs:

- **Document namespace** — contains a UUID that changes every run
- **Creation timestamp** — `created` field in `creationInfo`
- **File checksums** — SHA256 hashes change when upstream source is
  updated
- **Exact version strings** — the test checks *whether* a version
  exists, not its exact value
- **Package ordering** — names are compared as sorted sets

## 6. Test Classes and Parameterization

### Discovery

`get_golden_files()` auto-discovers all golden files by walking
`tests/golden/spdx/`, matching `*_analyzed.spdx.json`,
`*_build.spdx.json`, and `*_adg.spdx.json` (legacy).

### Parameterized tests

Each golden file becomes a separate parameterized test case:

```text
test_spdx_regression.py::test_golden_file_exists[c-cpp/nmap/nmap_analyzed.spdx.json]
test_spdx_regression.py::TestGoldenFileIntegrity::test_no_bogus_package_names[...]
test_spdx_regression.py::TestGoldenFileIntegrity::test_root_package_has_version[...]
```

### Comparison API

```python
from tests.test_spdx_regression import compare_against_golden

diffs = compare_against_golden(
    actual_spdx_path=Path("output/spdx/c-cpp/nmap/.../nmap_analyzed.spdx.json"),
    lang="c-cpp",
    repo="nmap",
    binary="nmap",
)
```

## 7. Workflow: Updating Golden Files

### Step 1: Generate new output

Run the full pipeline for all affected repos on EC2.

### Step 2: Compare against baselines

```bash
python3 scripts/compare_golden.py tests/golden/spdx output/spdx
```

### Step 3: Review ALL differences

For each difference, determine: Is this expected? Is this a bug? Is
this an improvement?

### Step 4: Get approval

Report all differences to the maintainer. **Wait for explicit approval
before proceeding.** Updating golden files without approval is a
**critical violation**.

### Step 5: Update golden files

Only after approval:

```bash
cp output/spdx/<lang>/<repo>/<ts>/<binary>_analyzed.spdx.json \
  tests/golden/spdx/<lang>/<repo>/
cp output/spdx/<lang>/<repo>/<ts>/<binary>_build.spdx.json \
  tests/golden/spdx/<lang>/<repo>/
```

### Step 6: Commit

```bash
git add tests/golden/
git commit -m "chore: update golden files after <reason>"
```

## 8. Adding Golden Files for a New Repo

1. Run the full pipeline for the new repo
2. Manually review the SPDX output for correctness
3. Copy output to `tests/golden/spdx/<lang>/<repo>/`
4. Commit as the initial baseline
5. `test_spdx_regression.py` will automatically discover and validate
   the new files

## 9. Troubleshooting Test Failures

- **"Golden file missing"** — a new binary was added to a repo's
  `output_binaries` but no golden file was created. Run analysis,
  verify, and copy to `tests/golden/spdx/<lang>/<repo>/`.
- **"Package count mismatch"** — vendored library added/removed
  upstream, or SPDX emitter logic changed. Check `git diff` on
  `app/spdx/emitter.py`.
- **"Newly unversioned packages"** — a package that previously had a
  version no longer does. Check `app/spdx/version_detector.py` for
  recent changes.
- **"Relationship count mismatch"** — dependency graph structure
  changed. Common causes: new `STATIC_LINK`/`DYNAMIC_LINK` detection,
  `BUILD_TOOL_OF` inclusion changes, transitive dependency resolution.

---

## Rules

- **NEVER** update golden files without explicit maintainer approval
- **NEVER** dismiss differences as "likely upstream" or "within
  tolerance"
- **ALWAYS** report every difference, no matter how small
- **ALWAYS** stop and wait for approval if any diffs exist

See `.windsurf/rules/cascade/golden-file-policy.md` for the full
policy.
