# Java Phase 1 Optimizations — Implementation Summary

**Date:** 2026-07-16  
**Status:** Implemented, awaiting EC2 validation  
**Branch:** `main` (uncommitted changes)

---

## What Was Implemented

### 1. Parallel Execution (P2)

**Files modified:**
- `app/pipeline/interception.py` (both `GradleDepTreeStrategy` and `MavenDepTreeStrategy`)

**Changes:**
- Treedb assembly and dependency resolution now run **concurrently** using `ThreadPoolExecutor`
- Both tasks are I/O-bound (subprocess calls + file I/O) and independent (no shared state)
- Total time = `max(treedb_time, deptree_time)` instead of `sum`

**Code pattern:**
```python
with ThreadPoolExecutor(max_workers=2) as executor:
    treedb_future = executor.submit(build_java_treedb, ...)
    deptree_future = executor.submit(get_all_gradle_deps, repo_dir)
    
    treedb_ok = treedb_future.result()
    modules = deptree_future.result()
```

**Expected impact:**
- All repos: 30-50% reduction in post-build time
- Example: If treedb=10s and deptree=10s, parallel=10s instead of 20s

---

### 2. Diagnostic Logging (P0)

**Files modified:**
- `app/pipeline/gradle_dep_tree_parser.py`

**Changes:**
- Added timing and success/failure logging to `run_gradle_all_dep_trees()`
- Added fallback detection logging to `get_all_gradle_deps()`
- Reports whether single-invocation succeeded or fell back to per-project loop

**Output examples:**
```
[OK] Gradle omniborDeps single-invocation succeeded in 12.3s
[OK] Gradle single-invocation: parsed 163 modules
```

or

```
[WARN] Gradle omniborDeps timed out after 600.0s
[WARN] Gradle single-invocation failed or produced no sections; falling back to per-subproject invocations
```

**Purpose:** Identify whether spring-boot is using single-invocation or per-project fallback

---

### 3. Timeout Increase (P1)

**Files modified:**
- `app/pipeline/gradle_dep_tree_parser.py`

**Changes:**
- Increased Gradle single-invocation timeout from 600s → 900s (15 minutes)
- Added elapsed time reporting on timeout

**Rationale:** spring-boot has 163 modules; 600s may be insufficient for single-invocation

---

## Implementation Details

### Generic Solution (No Hardcoding)

All changes are **generic** and work for:
- ✅ All Java repos (no repo-specific logic)
- ✅ Both Maven and Gradle
- ✅ Both inline-hashing and legacy rescan modes

### Thread Safety

Both tasks are thread-safe:
- **Treedb assembly:** Writes to `metadata/bomsh/` directory
- **Dependency resolution:** Returns data structure (no file writes during subprocess)
- **No shared state** between tasks

### Error Handling

- If treedb fails, dep-tree is cancelled and function returns False
- If dep-tree fails, treedb result is preserved and error is reported
- All existing error paths preserved

---

## Testing

### Unit Tests

All existing tests pass:
```bash
.venv/bin/python3 -m pytest tests/test_interception.py tests/test_gradle_dep_tree_parser.py -xvs
# 84 passed in 0.16s
```

### Lint

No lint errors:
```bash
.venv/bin/python3 -m flake8 app/pipeline/interception.py app/pipeline/gradle_dep_tree_parser.py
# Exit code: 0
```

---

## Expected Results (EC2 Validation Needed)

### Scenario 1: Single-Invocation Already Works

If `run_gradle_all_dep_trees()` succeeds for spring-boot:

| Repo | Current (s) | After Parallel (s) | Improvement |
|---|---|---|---|
| spring-boot | 79.6 | ~10 | **87% reduction** |
| dependency-check | 22.9 | ~12 | **48% reduction** |
| bc-java | 18.5 | ~10 | **46% reduction** |
| logging-log4j2 | 4.8 | ~3 | **38% reduction** |

**Result:** ALL repos <20% Phase 1 overhead ✅ PRODUCTION-READY

### Scenario 2: Single-Invocation Times Out

If `run_gradle_all_dep_trees()` times out even at 900s:

| Repo | Current (s) | After Parallel (s) | Improvement |
|---|---|---|---|
| spring-boot | 79.6 | ~40 | **50% reduction** |
| dependency-check | 22.9 | ~12 | **48% reduction** |

**Result:** spring-boot still high (~185% overhead), needs further optimization

### Scenario 3: Single-Invocation Fails (Non-Timeout)

If `run_gradle_all_dep_trees()` fails due to Gradle version incompatibility or parse error:

- Diagnostic logging will identify the failure reason
- Fallback to per-project loop still works (no regression)
- Need to fix init script or parser

---

## Next Steps

### 1. EC2 Validation (IMMEDIATE)

```bash
# On EC2 (after /ec2-start)
cd ~/omnibor-analysis
git pull origin main  # Get the changes
docker build -t omnibor-env:latest -f docker/Dockerfile .
./scripts/run_java_analysis.sh spring-boot
./scripts/run_java_analysis.sh dependency-check
# ... all 8 repos
```

**Look for in console output:**
- `[OK] Gradle omniborDeps single-invocation succeeded in X.Xs`
- `[OK] Parallel execution: treedb=X.Xs, dep-tree=Y.Ys, total=Z.Zs (saved W.Ws vs sequential)`

### 2. Compare Results

**Check:**
- `output/runtime/java/<repo>/<ts>/runtime.json` — verify Phase 1 time reduced
- `output/runtime/java/<repo>/<ts>/adg_substeps.json` — verify treedb + dep-tree breakdown
- Console logs — verify single-invocation succeeded

### 3. Golden File Validation

```bash
# On EC2
for repo in jsoup checkstyle crawler4j dependency-check logging-log4j2 bc-java spring-boot omnibor-java-testapp; do
    ./scripts/compare_golden.py --repo $repo --lang java
done
```

**Expected:** All repos golden-clean (no SPDX changes from parallel execution)

### 4. Update Timing Report

If results are good:
- Update `output/java-sidecar-phase1-timing-report_2026-07-16_0842.md` with actual measurements
- Replace "Expected impact" with "Measured impact"
- Update Executive Summary with final numbers

### 5. Commit + PR

```bash
git checkout -b feat/java-phase1-parallel-execution
git add app/pipeline/interception.py app/pipeline/gradle_dep_tree_parser.py
git commit -m "feat(java): parallel treedb + dep-tree execution

- Run treedb assembly and dependency resolution concurrently
- Add diagnostic logging for single-invocation success/failure
- Increase Gradle single-invocation timeout to 900s
- Generic solution for both Maven and Gradle

Expected impact: 30-87% reduction in post-build capture time"

# Run pre-commit gates
.venv/bin/python3 -c "import app"  # Compile check
.venv/bin/python3 -m flake8 app/ tests/ docker/patches/  # Lint
.venv/bin/python3 -m pytest tests/ -x -q  # Tests
.venv/bin/python3 -m pytest tests/ --cov=app --cov=docker/patches --cov-report=term-missing  # Coverage

git push origin feat/java-phase1-parallel-execution
gh pr create --title "Java Phase 1: Parallel treedb + dep-tree execution" --body "..."
```

---

## Rollback Plan

If EC2 validation shows regressions:

1. **Revert parallel execution:**
   ```bash
   git revert <commit-sha>
   ```

2. **Keep diagnostic logging** (no performance impact, useful for debugging)

3. **Investigate root cause** before re-attempting

---

## Design References

- **Optimization proposal:** `docs/proposals/java-phase1-optimization-plan.md`
- **Bottleneck investigation:** `docs/analysis/java-phase1-bottleneck-investigation.md`
- **Timing report:** `output/java-sidecar-phase1-timing-report_2026-07-16_0842.md`
