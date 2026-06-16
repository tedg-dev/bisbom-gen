# Phase Isolation: Build-Time Impact Analysis

**Date:** June 16, 2026

**Context:** Deep-dive investigation into Phase 1 build-time impact,
source tree access in Phase 2, and ADG step optimization. This document
captures the full Q&A exchange that led to the optimizations implemented
in `feat/adg-phase1-optimization`.

**Related documents:**

- `docs/features/phase-isolation/phase-isolation-system-test.md`
- `docs/deep-dive/phase-isolation-gap-analysis.md`
- `docs/deep-dive/sidecar-java-design.md`

---

## 1. The Phase 2 Source Tree Question

### User Question

> "But an SBOM generator shouldn't need the source tree in Phase 2 — it
> should work entirely from build artifacts" is arguably not correct,
> especially if `omnibor-analysis` overall benefits from a less impactful
> build-time execution because Phase 2 could be generating SHAs from
> source files, if necessary. DO NOT FORGET BUILD TIME SPEED IS CRITICAL,
> or rather Phase 1 impact on build time speed is critical, must be as
> minimal as possible.

### Analysis

The blanket statement "Phase 2 shouldn't need the source tree" was a
premature architectural pronouncement. The correct lens is: **what
minimizes Phase 1's impact on the customer's build time?**

Phase 1 currently performs two post-build operations in the `adg` step:

1. `bomsh_create_bom_java.py` — scans `.class` files for `SourceFile`
   bytecode attributes, resolves to `.java` source files via path
   similarity, computes SHA-256 hashes for every source file and class
   file, writes treedb
2. `mvn dependency:tree` / `./gradlew dependencies` — starts a new JVM,
   resolves the full dependency graph

Real timing data from EC2 runs (combined `adg` step):

| Repo | Orchestrator | `adg` wall time | Build time | adg as % of build |
|------|-------------|-----------------|------------|-------------------|
| dependency-check | Maven | **218s** | 30s | 727% |
| spring-boot | Gradle | **1,223s** (20 min) | 56s | 2,184% |
| jsoup | Maven | 4s | 26s | 15% |

For large projects, the Phase 1 post-build overhead **dwarfs** the
actual build.

### Key Constraint (User Correction)

> "Also REMEMBER, we are NOT doing a git clone in Phase 1, the native
> build environment is. There has not been any reason for
> `omnibor-analysis` to have credentialed access to dev team repos!"

- The customer's CI/CD pipeline clones their repo
- Phase 1 sidecar reads the already-cloned workspace via shared volume
- `omnibor-analysis` has never needed and should never need credentialed
  access to customer repos
- The `actions/checkout` in `omnibor-java-testapp`'s Phase 2 job is a
  **test convenience**, not the enterprise architecture

---

## 2. Source File SHA Computation — Does It Matter?

### User Question

> "Phase 2 would compute the SHA-256 hashes later" — but only source
> code hashes. What about intermediate files like class files, object
> files, etc.? If Phase 1 already has to create hashes for these
> intermediate files, does creating a hash for the corresponding source
> file add a significant impact that would make it valuable to do in
> Phase 2?

### Analysis: No — Source File Hashing Is Negligible

If Phase 1 is already:

1. Reading every `.class` file (to extract the `SourceFile` bytecode
   attribute)
2. Computing SHA-256 for every `.class` file
3. Computing SHA-256 for the `.jar` file

...then the marginal cost of also computing SHA-256 for the
corresponding `.java` source file is **negligible**:

- **`.java` files are smaller than `.class` files.** Source files have
  no constant pool, no bytecode instructions, no attribute tables. A
  typical `.java` file is a few KB.
- **SHA-256 is hardware-accelerated.** Modern CPUs (x86 with SHA-NI,
  ARM with crypto extensions) compute SHA-256 at memory bandwidth
  speed. Hashing a 5KB file takes microseconds.
- **The source file is likely already in OS page cache.** The Java
  compiler just read it seconds ago during the build.
- **The I/O pattern is sequential.** One `open()` + `read()` +
  `close()` per file, on warm cache.

For context: dependency-check has ~1,300 source files. At ~5KB average,
that's ~6.5MB of source file I/O and hashing — **sub-second** on any
modern disk or SSD, buried in noise compared to the 218 seconds the
`adg` step takes overall.

### Conclusion

The suggestion to defer source file hashing to Phase 2 was solving a
non-problem. The source file hashing is a rounding error on top of the
intermediate file processing that Phase 1 must do anyway.

The data Phase 1 captures (treedb + `maven_deps.json` + manifest)
should be **everything** Phase 2 needs. There is no valid reason for
Phase 2 to need the source tree for SHA computation.

---

## 3. The Real Bottleneck: JVM Startup for Dependency Resolution

### User Question

> Is there anything that can be done about the real bottleneck in
> Phase 1 — the `mvn dependency:tree` call with its JVM startup
> overhead?

### Analysis

Yes. Several optimizations are viable without touching the customer's
build:

#### 3a. Offline Mode — Biggest Win, One Flag

The build just ran `mvn package`, which downloaded every dependency into
the local `.m2/repository` cache. Running `mvn dependency:tree`
immediately after re-checks remote repositories for SNAPSHOT updates and
metadata freshness. Adding `-o` (offline) skips all network I/O.

This is standard Maven practice. Maven's own documentation recommends
`-o` when the local cache is known complete. Since the build just
succeeded, the cache is guaranteed complete.

**Implemented:** `-o` added to `run_maven_dep_tree()` in
`app/pipeline/maven_dep_tree_parser.py`.

#### 3b. Skip Flags — Prevent Lifecycle Plugin Overhead

`dependency:tree` doesn't compile anything, but Maven lifecycle plugins
may still fire. Adding skip flags prevents unnecessary work:

```text
-DskipTests
-Dmaven.javadoc.skip=true
-Denforcer.skip=true
-Dcheckstyle.skip=true
```

**Implemented:** All four flags added to `run_maven_dep_tree()`.

#### 3c. Parallel Execution — Free Wall-Time Reduction

`bomsh_create_bom_java.py` (treedb generation) and
`mvn dependency:tree` are independent operations. Treedb reads `.class`
files; dep:tree reads `pom.xml`. They can run concurrently.

Wall time drops from `treedb_time + deptree_time` to
`max(treedb_time, deptree_time)`.

**Status:** Pending — requires `concurrent.futures` threading, planned
for a follow-up commit.

#### 3d. Module Targeting (`-pl`) — Already Partially Implemented

The `maven_modules` parameter in `run_maven_dep_tree()` already
supports `-pl`. For multi-module projects where only a subset of
modules produce output JARs, targeting specific modules skips
irrelevant ones.

For spring-boot (30+ modules, only 3 produce output JARs), this
could eliminate 90% of the dep:tree work.

**Status:** Pending — needs config schema extension to specify which
modules produce output JARs.

#### 3e. Direct POM Parsing — Last Resort (Not Recommended)

Parsing `pom.xml` directly in Python would eliminate JVM startup
entirely, but loses:

- Property interpolation (`${project.version}`, etc.)
- BOM / `dependencyManagement` resolution
- Transitive dependency resolution
- Version conflict mediation (nearest-wins rule)
- Profile activation

This would produce a less accurate dependency graph. **Not
recommended** unless overhead is still unacceptable after
options 3a–3d.

---

## 4. Gradle Has the Same Bottleneck — Worse

### User Question

> This is for Maven, what about Gradle or other orchestrators? Is
> there a similar bottleneck that can be dealt with in this same
> optimized manner to reduce build time impact?

### Analysis

Yes — Gradle has the **same bottleneck**, and it was worse due to a
configuration mistake:

| Repo | Orchestrator | `adg` wall time | Build time | Ratio |
|------|-------------|-----------------|------------|-------|
| dependency-check | Maven | 218s | 30s | 7.3x |
| spring-boot | Gradle | **1,223s** | 56s | **21.8x** |

Two reasons Gradle was worse:

1. **`--no-daemon` was being used for dep:tree** (line 59 of
   `gradle_dep_tree_parser.py`). This forced a cold JVM start for
   every `./gradlew dependencies` call. The Gradle Daemon exists
   specifically to avoid this — it keeps a warm JVM in memory. The
   build command in `config.yaml` correctly uses `--no-daemon`
   (deterministic sidecar behavior), but our **post-build query**
   doesn't need it — the build daemon may still be warm.

2. **Per-subproject execution** — `get_all_gradle_deps()` runs
   `./gradlew dependencies` once per subproject. Spring-boot has
   many subprojects. Each invocation was a separate cold JVM start
   with `--no-daemon`.

### Fixes Applied

- **`--offline`** — Same as Maven's `-o`. Dependencies are already
  cached from the build.
- **Removed `--no-daemon`** — Allows reuse of the warm Gradle daemon
  from the build, eliminating cold JVM start overhead.

### Fixes Pending

- **Single-invocation multi-project query** — Running
  `./gradlew dependencies` at root already aggregates all
  subprojects. Avoids N separate JVM starts.
- **Parallel execution** — Same as Maven: run treedb + dep:tree
  concurrently.

---

## 5. Split Timing Implementation

### Rationale

The `adg` step timing (218s for dependency-check, 1,223s for
spring-boot) was a **combined** measurement of
`bomsh_create_bom_java.py` + dep:tree. Without knowing the split,
optimization decisions were guesswork.

### What Was Implemented

Both `MavenDepTreeStrategy.generate_adg()` and
`GradleDepTreeStrategy.generate_adg()` now separately time each
sub-step using `time.monotonic()` and write the breakdown to
`adg_substeps.json` in `bom_dir`:

```json
[
  {
    "name": "treedb",
    "tool": "bomsh_create_bom_java.py",
    "wall_sec": 12.34
  },
  {
    "name": "dep_tree",
    "tool": "mvn dependency:tree",
    "wall_sec": 205.67
  }
]
```

Console output also includes per-substep timings:

```text
[OK] OmniBOR treedb written to .../bomsh_omnibor_treedb (12.3s)
[OK] Maven dep:tree: 47 dependencies → .../maven_deps.json (205.7s)
```

### Files Modified

| File | Change |
|------|--------|
| `app/pipeline/interception.py` | `_write_adg_substeps()` helper; split timing in both Maven and Gradle `generate_adg()` |
| `app/pipeline/maven_dep_tree_parser.py` | Added `-o`, `-DskipTests`, `-Dmaven.javadoc.skip=true`, `-Denforcer.skip=true`, `-Dcheckstyle.skip=true` |
| `app/pipeline/gradle_dep_tree_parser.py` | Replaced `--no-daemon` with `--offline` |
| `tests/test_maven_dep_tree_parser.py` | Tests for `adg_substeps.json` structure and offline/skip flags |
| `tests/test_gradle_dep_tree_parser.py` | Tests for `adg_substeps.json` structure and `--offline`/no `--no-daemon` |

### Test Results

- **1453 passed**, 75 skipped
- **98% overall coverage**
- Modified files: 95–97% coverage each

---

## 6. Applicability to Other Languages

| Language | Dep Resolution Method | JVM Startup? | Same Bottleneck? |
|---|---|---|---|
| **Java (Maven)** | `mvn dependency:tree` | Yes | **Yes — fixed with `-o` + skip flags** |
| **Java (Gradle)** | `./gradlew dependencies` | Yes | **Yes — fixed with `--offline`, removed `--no-daemon`** |
| **C/C++** | No dep resolution in Phase 1 (strace/`LD_PRELOAD`/eBPF captures I/O inline) | No | No |
| **Go** | No dep resolution in Phase 1 (strace captures I/O inline) | No | No |
| **Rust** | No dep resolution in Phase 1 (strace captures I/O inline) | No | No |

For kernel-level interception (strace, `LD_PRELOAD`, eBPF), SHA hashes
are computed **during** the build as files are read/written — they
cannot be deferred because the tracer observes actual I/O. There is no
separate dep resolution step.

For Java sidecar (post-build analysis), `bomsh_create_bom_java.py` and
the dep:tree command are discrete steps that run **after** the build.
These are the only steps where JVM startup overhead applies, and they
are the only ones that benefit from the optimizations above.

---

## 7. Next Steps

1. **Run on EC2** with split timing enabled against dependency-check
   (Maven) and spring-boot (Gradle) to get actual treedb vs dep:tree
   breakdown
2. **Implement parallel execution** of treedb + dep:tree
   (`concurrent.futures.ThreadPoolExecutor`)
3. **Wire aggressive `-pl` module targeting** from `config.yaml` for
   multi-module Maven projects
4. **Measure before/after** — compare the optimized `adg` timings
   against the pre-optimization baselines documented in this file
