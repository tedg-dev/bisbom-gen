# Gradle Dependency Resolution Optimization Investigation

**Date:** 2026-07-16  
**Current bottleneck:** `gradlew omniborDeps` takes 22.67s for 186 modules  
**Target:** Reduce to <10s

---

## Current Implementation Analysis

### What We're Doing Now

**File:** `app/pipeline/gradle_dep_tree_parser.py:43-62`

```groovy
import org.gradle.api.tasks.diagnostics.DependencyReportTask

allprojects { p ->
    p.afterEvaluate {
        if (p.configurations.findByName('runtimeClasspath') != null) {
            p.tasks.register('omniborDeps', DependencyReportTask) { t ->
                t.configuration = 'runtimeClasspath'
            }
        }
    }
}
```

**Command:** `./gradlew omniborDeps --init-script <temp> --offline --continue`

**What this does:**
1. Registers a `DependencyReportTask` on every project
2. Task runs dependency resolution
3. Task **formats output as human-readable text** (ASCII tree with `+---`, `\---`, etc.)
4. We parse the formatted text back into structured data

**Time breakdown (estimated):**
- Dependency resolution: ~5-8s (actual graph traversal)
- Text formatting: ~10-15s (ASCII tree generation for 186 modules)
- Parsing: <1s (our Python code)

**Problem:** We're paying for text formatting we don't need.

---

## Industry Best Practice: Gradle ResolutionResult API

### What Gradle Recommends

**Source:** Gradle documentation on dependency resolution  
**API:** `Configuration.getIncoming().getResolutionResult()`

**Benefits:**
- Direct access to resolved dependency graph (no formatting)
- Structured data (ResolvedComponentResult objects)
- Faster (skips text formatting)
- More accurate (no parsing ambiguity)

### Example Init Script (Industry Standard)

```groovy
import groovy.json.JsonOutput

allprojects { p ->
    p.afterEvaluate {
        def config = p.configurations.findByName('runtimeClasspath')
        if (config != null) {
            p.tasks.register('omniborDepsJson') {
                doLast {
                    def result = config.incoming.resolutionResult
                    def root = result.root
                    
                    def deps = []
                    root.dependencies.each { dep ->
                        if (dep instanceof ResolvedDependencyResult) {
                            def selected = dep.selected
                            deps << [
                                group: selected.moduleVersion.group,
                                name: selected.moduleVersion.name,
                                version: selected.moduleVersion.version,
                                requested: dep.requested.displayName
                            ]
                        }
                    }
                    
                    def output = [
                        project: p.path,
                        dependencies: deps
                    ]
                    
                    println "===OMNIBOR_START==="
                    println JsonOutput.toJson(output)
                    println "===OMNIBOR_END==="
                }
            }
        }
    }
}
```

**Output format:** JSON (one per project, delimited by markers)

**Expected time:** 5-10s (no text formatting overhead)

---

## Alternative: Gradle Configuration Cache

### What It Is

**Source:** Gradle 6.5+ feature  
**Flag:** `--configuration-cache`

**What it does:**
- Caches the result of project configuration phase
- Skips re-evaluating build scripts on subsequent runs
- Dependency resolution is part of configuration

**Benefits:**
- First run: same time as current
- Subsequent runs: ~50% faster (skips configuration)

**Limitations:**
- Requires Gradle 6.5+ (spring-boot uses 8.13 ✅)
- Not all tasks are compatible
- Cache invalidation on build script changes

**Risk:** Medium (may not work with custom tasks)

---

## Alternative: Gradle Build Scan API

### What It Is

**Source:** Gradle Enterprise / Build Scan plugin  
**API:** Programmatic access to build metadata

**What it does:**
- Gradle already resolves dependencies during the build
- Build scan captures this data
- We could extract it instead of re-running resolution

**Benefits:**
- Zero additional resolution time (reuse build data)
- Most accurate (exactly what the build used)

**Limitations:**
- Requires Gradle Enterprise license (enterprise only)
- Or self-hosted build scan server
- Not feasible for open-source repos

**Verdict:** Not applicable (requires enterprise infrastructure)

---

## Alternative: Dependency Locking

### What It Is

**Source:** Gradle dependency locking feature  
**Files:** `gradle.lockfile` per project

**What it does:**
- Gradle can write resolved versions to lockfiles
- Lockfiles are human-readable (group:name:version per line)
- Generated during build, not post-build

**Benefits:**
- Lockfile parsing is trivial (no tree parsing)
- Already generated if project uses locking
- Fast to read (<1s)

**Limitations:**
- Not all projects use dependency locking
- Would require modifying build (adding `dependencyLocking {}`)
- Violates sidecar constraint C2 (no build modifications)

**Verdict:** Not feasible (requires build modification)

---

## Recommended Optimization: JSON ResolutionResult API

### Implementation Plan

**Change:** Replace `DependencyReportTask` with custom task using `ResolutionResult` API

**New init script:**
```groovy
import groovy.json.JsonOutput
import org.gradle.api.artifacts.result.ResolvedDependencyResult

allprojects { p ->
    p.afterEvaluate {
        def config = p.configurations.findByName('runtimeClasspath')
        if (config != null) {
            p.tasks.register('omniborDepsJson') {
                doLast {
                    def result = config.incoming.resolutionResult
                    def root = result.root
                    
                    def collectDeps
                    collectDeps = { component, depth, parent ->
                        def deps = []
                        component.dependencies.each { dep ->
                            if (dep instanceof ResolvedDependencyResult) {
                                def selected = dep.selected
                                def modVer = selected.moduleVersion
                                def depMap = [
                                    groupId: modVer.group,
                                    artifactId: modVer.name,
                                    version: modVer.version,
                                    scope: 'runtime',
                                    depth: depth,
                                    direct: (depth == 1),
                                    parent: parent
                                ]
                                deps << depMap
                                // Recursive: collect transitive deps
                                deps.addAll(collectDeps(selected, depth + 1, "${modVer.group}:${modVer.name}"))
                            }
                        }
                        return deps
                    }
                    
                    def allDeps = collectDeps(root, 1, null)
                    
                    def output = [
                        key: p.path,
                        project: (p.path == ':' ? null : p.path.substring(1)),
                        deps: allDeps
                    ]
                    
                    println "===OMNIBOR_JSON_START==="
                    println JsonOutput.toJson(output)
                    println "===OMNIBOR_JSON_END==="
                }
            }
        }
    }
}
```

**Parser changes:**
- Replace text parsing with JSON parsing
- Extract JSON blocks between delimiters
- Map to existing data structure

**Expected impact:**
- Current: 22.67s (resolution + formatting + parsing)
- After: 8-12s (resolution + JSON serialization)
- **Reduction: 40-50%**

**Risk:** Low (ResolutionResult API is stable since Gradle 1.0)

---

## Secondary Optimization: Parallel Module Processing

### Current Behavior

Gradle runs `omniborDeps` task sequentially across projects (even with `--parallel`).

### Optimization

Use Gradle's `--parallel` flag with `--max-workers=4`:

```bash
./gradlew omniborDepsJson --init-script <temp> --offline --continue --parallel --max-workers=4
```

**Expected impact:**
- Current: 8-12s (after JSON optimization)
- After: 4-6s (with 4 workers on c6i.xlarge)
- **Additional reduction: 40-50%**

**Risk:** Low (Gradle parallel execution is well-tested)

---

## Tertiary Optimization: Configuration Cache

### Implementation

Add `--configuration-cache` flag:

```bash
./gradlew omniborDepsJson --init-script <temp> --offline --continue --parallel --max-workers=4 --configuration-cache
```

**Expected impact:**
- First run: same as parallel (4-6s)
- Subsequent runs: 2-3s (skips configuration)
- **Additional reduction: 33-50% on subsequent runs**

**Risk:** Medium (init scripts may not be configuration-cache compatible)

---

## Combined Optimization Impact

| Optimization | Time (s) | Reduction | Cumulative |
|---|---|---|---|
| Baseline (current) | 22.67 | — | — |
| JSON ResolutionResult API | 10.0 | 56% | 56% |
| + Parallel (4 workers) | 5.0 | 50% | 78% |
| + Configuration cache | 2.5 | 50% | 89% |

**Final target: 2.5-5s** (vs current 22.67s)

**Total Phase 1 overhead:**
- Current: +109% (45.4s / 21.7s)
- After: **+28-37%** (27.9-30.4s / 21.7s) ✅ **EXCELLENT**

---

## Implementation Priority

### P1: JSON ResolutionResult API (High Impact, Low Risk)

**Effort:** 2-3 hours
- Write new init script
- Update parser to handle JSON
- Test on spring-boot + dependency-check
- Validate golden-clean

**Expected:** 22.67s → 10s

### P2: Parallel Execution (Medium Impact, Low Risk)

**Effort:** 30 minutes
- Add `--parallel --max-workers=4` flags
- Test on spring-boot
- Measure impact

**Expected:** 10s → 5s

### P3: Configuration Cache (Medium Impact, Medium Risk)

**Effort:** 1 hour
- Add `--configuration-cache` flag
- Test compatibility with init script
- Handle cache invalidation

**Expected:** 5s → 2.5s (subsequent runs)

---

## Risks & Mitigations

### Risk 1: JSON parsing overhead

**Mitigation:** JSON parsing is faster than text parsing (no regex, no tree reconstruction)

### Risk 2: Parallel execution race conditions

**Mitigation:** Each project writes to stdout independently; we parse by delimiter markers

### Risk 3: Configuration cache incompatibility

**Mitigation:** Keep as optional flag; fallback to non-cached if it fails

---

## Next Steps

1. ✅ Implement P1 (JSON ResolutionResult API)
2. ✅ Test on spring-boot (validate 22.67s → ~10s)
3. ✅ Test on dependency-check (Maven equivalent already fast)
4. ✅ Implement P2 (parallel execution)
5. ✅ Test combined (validate ~5s)
6. ⏳ Implement P3 (configuration cache) if P1+P2 insufficient
7. ✅ Golden file validation
8. ✅ Commit + PR

---

## References

- Gradle ResolutionResult API: https://docs.gradle.org/current/javadoc/org/gradle/api/artifacts/result/ResolutionResult.html
- Gradle parallel execution: https://docs.gradle.org/current/userguide/multi_project_configuration_and_execution.html#sec:parallel_execution
- Gradle configuration cache: https://docs.gradle.org/current/userguide/configuration_cache.html
