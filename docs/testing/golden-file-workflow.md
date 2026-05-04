# Golden File Workflow

## What Are Golden Files?

Golden files are known-good SPDX output files stored in the repository
as regression baselines. New pipeline output is compared against these
files to detect unintended changes.

## Location

```
tests/golden/spdx/
├── c-cpp/
│   ├── redis/
│   │   ├── redis-server_analyzed.spdx.json
│   │   ├── redis-server_build.spdx.json
│   │   ├── redis-cli_analyzed.spdx.json
│   │   └── redis-cli_build.spdx.json
│   ├── curl/
│   ├── nmap/
│   └── ffmpeg/
├── go/
│   └── lazygit/
├── rust/
│   ├── dura/
│   └── oxipng/
└── java/
    ├── checkstyle/
    └── jsoup/
```

Each target repo has two files per output binary:
- `*_analyzed.spdx.json` — OmniBOR-enriched SPDX (primary output)
- `*_build.spdx.json` — Build-only SPDX (source + vendored deps)

## Comparison Tool

```bash
# Compare new output against golden baselines:
python3 scripts/compare_golden.py tests/golden/spdx output/spdx

# The script reports:
# - Package count changes
# - Missing/extra packages
# - Version changes
# - Relationship count changes
# - Added/removed relationships
# - External reference changes
```

## Comparison Fields

### Compared (structural):
- Package names and counts
- Package versions (`versionInfo`)
- Relationship types and counts
- Relationship endpoints (source → target pairs)
- External references (PURLs, CPEs)

### Ignored (run-specific):
- SPDX document namespace (contains UUID)
- Creation timestamps
- File checksums (may change with upstream updates)

## Workflow: Updating Golden Files

### Step 1: Generate new output

Run the full pipeline for all affected repos on EC2:

```bash
# Inside Docker container:
python3 -m app.pipeline.facade --repo redis
python3 -m app.pipeline.facade --repo curl
# ... etc.
```

### Step 2: Compare against baselines

```bash
python3 scripts/compare_golden.py tests/golden/spdx output/spdx
```

### Step 3: Review ALL differences

For each difference, determine:
- Is this expected? (e.g., version bump after repo update)
- Is this a bug? (e.g., missing package after refactoring)
- Is this an improvement? (e.g., new dependency detected)

### Step 4: Get approval

Report all differences to the maintainer. Wait for explicit
approval before proceeding.

### Step 5: Update golden files

Only after approval:

```bash
# Copy new output to golden directory:
cp output/spdx/c-cpp/redis/*.spdx.json tests/golden/spdx/c-cpp/redis/
# ... for each approved repo

# Or use the update function:
python3 -c "
from tests.test_spdx_regression import update_golden
from pathlib import Path
update_golden(Path('output/spdx/c-cpp/redis/redis-server_analyzed.spdx.json'),
              'c-cpp', 'redis', 'redis-server')
"
```

### Step 6: Commit golden file updates

```bash
git add tests/golden/
git commit -m "chore: update golden files after <reason>"
```

## Adding Golden Files for a New Repo

1. Run the full pipeline for the new repo
2. Manually review the SPDX output for correctness
3. Copy output to `tests/golden/spdx/<lang>/<repo>/`
4. Commit as the initial baseline
5. The `test_spdx_regression.py` tests will automatically
   discover and validate the new files

## Rules (from golden-file-policy)

- **NEVER** update golden files without explicit maintainer approval
- **NEVER** dismiss differences as "likely upstream" or "within tolerance"
- **ALWAYS** report every difference, no matter how small
- **ALWAYS** stop and wait for approval if any diffs exist
- Updating golden files without approval is a **critical violation**
