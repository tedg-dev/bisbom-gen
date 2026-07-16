# Java Phase 1 Post-Build Capture Bottleneck Investigation

**Date:** 2026-07-16  
**Investigator:** Cascade AI  
**Objective:** Understand why spring-boot and dependency-check have 100%+ Phase 1 overhead and identify optimization paths

---

## Current Architecture (Verified from Code)

### Phase 1 Post-Build Capture Steps

After the build completes, Phase 1 runs these sequential steps:

1. **Treedb Assembly** (`bomsh_create_bom_java.py` or inline-hashing assembly)
   - Scans workspace for `.class` and `.jar` files
   - Reads `SourceFile` bytecode attribute from each `.class`
   - Computes git-blob SHA-1 for each file
   - Resolves class → source `.java` via path similarity
   - Builds treedb: `{sha1: {file_path, hash_tree: [dependencies]}}`

2. **Dependency Tree Capture**
   - **Maven**: `mvn dependency:tree -DoutputType=text` (default text format)
   - **Gradle**: `./gradlew dependencies` per subproject
   - Runs in offline mode first (`-o` / `--offline`), falls back to online
   - Parses output into structured JSON
   - Writes `maven_deps.json` or `gradle_deps.json`

3. **Identity Index** (if inline-hashing enabled)
   - Writes artifact SHA-256 gitoids to `identity_index.json`

4. **Manifest Generation**
   - Writes `sbom_handoff_manifest.json` with Phase 2 inputs

### Timing Breakdown (from runtime.json)

| Repo | Build (s) | Treedb (s) | Dep Tree (s) | Total Post-Build (s) |
|---|---|---|---|---|
| spring-boot | 20.53 | ? | 79.60 | 79.60 |
| dependency-check | 21.93 | ? | 22.86 | 22.86 |
| bc-java | 137.12 | ? | 18.50 | 18.50 |
| logging-log4j2 | 94.65 | ? | 4.82 | 4.82 |

**Key observation:** The `adg` step in runtime.json is a COMBINED metric (treedb + dep-tree + identity + manifest). Need to break down further.

---

## Problem Statement

**spring-boot** post-build capture takes **79.6 seconds** on a **20.5-second build** (+362% overhead).  
**dependency-check** post-build capture takes **22.9 seconds** on a **21.9-second build** (+102% overhead).

These are **NOT production-ready** for enterprise CI/CD pipelines.

---

## Root Cause Hypothesis

### H1: Dependency Resolution Dominates

**Evidence:**
- spring-boot has 163 modules → `gradlew dependencies` must run 163 times (one per subproject)
- dependency-check has a large transitive dependency tree
- The `adg` step timing correlates with repo complexity, not just build size

**Code location:** `app/pipeline/interception.py`
- `GradleDepTreeStrategy.generate_adg()` lines 734-782
- `MavenDepTreeStrategy.generate_adg()` lines 599-661

**Current implementation:**
```python
# Gradle (interception.py:776-781)
for project in projects:
    run_gradle_dep_tree(repo_dir, project=project)
    # Sequential subprocess calls

# Maven (interception.py:644-650)
run_maven_dep_tree(repo_dir, maven_modules=modules)
# Single subprocess, but large reactor output
```

### H2: Treedb Assembly is Still Slow (Even with Fast I/O)

**Evidence:**
- PR #189 optimized treedb from 244s → 19.5s for dependency-check (12x speedup)
- But spring-boot has **113K treedb entries** vs <10K for other repos
- Even with fast I/O, O(N) file reads + bytecode parsing scales linearly

**Code location:** `docker/patches/bomsh_create_bom_java.py` (legacy rescan) or `app/pipeline/java_capture.py` (inline assembly)

### H3: Sequential Execution (No Parallelism)

**Current flow:**
1. Build completes
2. Treedb assembly (blocks)
3. Dependency resolution (blocks)
4. Identity index (blocks)
5. Manifest write (blocks)

**Opportunity:** Steps 2 and 3 are independent and could run in parallel.

---

## Industry Best Practices for Enterprise Java Builds

### Maven Best Practices

1. **Dependency resolution caching**
   - Use `-o` (offline mode) when `.m2/repository` is warm
   - ✅ Already implemented in `maven_dep_tree_parser.py:run_maven_dep_tree()`

2. **Reactor builds**
   - `mvn dependency:tree` runs once for the entire reactor
   - ✅ Already implemented (not per-module)

3. **Parallel builds**
   - Maven supports `-T` (threads) for parallel module builds
   - ❌ Not relevant here (we're post-build)

### Gradle Best Practices

1. **Dependency resolution caching**
   - Use `--offline` when Gradle cache is warm
   - ✅ Already implemented in `gradle_dep_tree_parser.py:run_gradle_dep_tree()`

2. **Configuration cache**
   - Gradle 6.5+ supports `--configuration-cache` to skip configuration phase
   - ❌ Not used (would require Gradle 6.5+ and may not work with `dependencies` task)

3. **Parallel execution**
   - Gradle supports `--parallel` for parallel project execution
   - ❌ Not relevant for `dependencies` task (it's a report, not a build)

4. **Single invocation for all subprojects**
   - `./gradlew dependencies` without `-p` runs for all subprojects
   - ❓ Need to verify if current code does this or runs per-project

---

## Code Analysis: Where is the Time Spent?

### Gradle Dependency Resolution (spring-boot outlier)

**File:** `app/pipeline/gradle_dep_tree_parser.py`

```python
def run_gradle_dep_tree(repo_dir, project=None, runner=None):
    """Run ``./gradlew dependencies`` for a project."""
    # ...
    cmd = ["./gradlew", "dependencies", "--offline"]
    if project:
        cmd.extend(["-p", project])
    # ...
```

**File:** `app/pipeline/interception.py:734-782`

```python
# GradleDepTreeStrategy.generate_adg()
projects = _find_gradle_projects(repo_dir)
for project in projects:
    tree_output = run_gradle_dep_tree(
        repo_dir, project=project, runner=runner,
    )
    # Sequential subprocess calls - NO PARALLELISM
```

**Problem:** spring-boot has 163 modules → 163 sequential `./gradlew dependencies -p <module>` invocations.

**Question:** Does `./gradlew dependencies` (without `-p`) run for ALL subprojects in one invocation?

### Maven Dependency Resolution (dependency-check outlier)

**File:** `app/pipeline/maven_dep_tree_parser.py:223-333`

```python
def run_maven_dep_tree(repo_dir, runner=None, maven_modules=None):
    """Run ``mvn dependency:tree -DoutputType=dot``."""
    # ...
    cmd = ["mvn", "dependency:tree"]
    if maven_modules:
        cmd.extend(["-pl", maven_modules])
    # ...
    # Tries offline first, falls back to online
    # Single invocation for entire reactor
```

**Problem:** dependency-check has a large transitive dependency tree → large reactor output to parse.

**Question:** Is the bottleneck in the subprocess execution or the parsing?

---

## Optimization Paths (Ranked by Impact)

### O1: Parallel Dependency Resolution + Treedb Assembly (A5/US-3)

**Impact:** High (50-80% reduction in post-build time)  
**Complexity:** Medium  
**Implementation:**
- Run `mvn dependency:tree` / `gradlew dependencies` in parallel with treedb assembly
- Use `concurrent.futures.ThreadPoolExecutor` or `multiprocessing.Pool`
- Both steps are I/O-bound and independent

**Code changes:**
- `app/pipeline/interception.py`: Refactor `generate_adg()` to run treedb + dep-tree in parallel
- Add timing breakdown to distinguish treedb vs dep-tree cost

### O2: Single-Invocation Gradle Dependencies (Extend A4)

**Impact:** High for Gradle multi-module repos (90% reduction for spring-boot)  
**Complexity:** Low  
**Implementation:**
- Run `./gradlew dependencies` ONCE without `-p` flag
- Parse output to extract per-subproject trees
- Already implemented for single-invocation in A4, needs extension

**Code changes:**
- `app/pipeline/gradle_dep_tree_parser.py`: Add `run_gradle_dep_tree_all_projects()`
- `app/pipeline/interception.py`: Use single invocation instead of per-project loop

**Question:** Does this already work? Need to test.

### O3: Inline Dependency Capture (Extend A4 to Maven)

**Impact:** Very High (eliminates post-build dep-tree subprocess entirely)  
**Complexity:** High  
**Implementation:**
- Capture dependency resolution during the build via Gradle/Maven plugin or build-tool hooks
- A4 already does this for Gradle single-invocation
- Extend to Maven and multi-invocation Gradle

**Blockers:**
- Requires build-tool integration (plugin or wrapper)
- May violate sidecar constraint C2 (no build modifications)

### O4: In-Memory JAR Processing (A8/US-4)

**Impact:** Medium (10-30% reduction in treedb time)  
**Complexity:** High  
**Implementation:**
- Process JAR members in-memory without extract-to-disk
- Reduces I/O for large JARs

**Code changes:**
- `docker/patches/bomsh_create_bom_java.py`: Use `zipfile` module instead of `jar -xf`
- `app/pipeline/java_capture.py`: Already in-memory (inline-hashing path)

---

## Immediate Action Items

1. **Measure treedb vs dep-tree breakdown**
   - Add separate timing entries for treedb and dep-tree in `generate_adg()`
   - Re-run spring-boot and dependency-check to see where the 79.6s and 22.9s are spent

2. **Test single-invocation Gradle dependencies**
   - Run `./gradlew dependencies` (no `-p`) on spring-boot
   - Measure wall time vs 163 sequential invocations
   - Verify output contains all subprojects

3. **Implement O1 (parallel treedb + dep-tree)**
   - Refactor `generate_adg()` to use `ThreadPoolExecutor`
   - Measure impact on spring-boot and dependency-check

4. **Implement O2 (single-invocation Gradle)**
   - If test in #2 succeeds, update `GradleDepTreeStrategy` to use single invocation
   - Measure impact on spring-boot

---

## Expected Outcome

**After O1 + O2:**
- spring-boot: 79.6s → <10s post-build (90% reduction)
- dependency-check: 22.9s → <10s post-build (60% reduction)
- **Total Phase 1 overhead: <20% for all repos**

This would make Java sidecar **production-ready** for enterprise CI/CD pipelines.
