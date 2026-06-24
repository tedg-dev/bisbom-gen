# Phase 1 Build-Speed & Efficiency — Design & Implementation Plan

| | |
|---|---|
| **Audience** | Engineering (design + implementation reference) |
| **Pairs with** | `docs/planning/phase1-build-speed-subissues.md` (high-level user stories US-1/US-2/US-3) |
| **Consolidates** | `phase-isolation-build-time-analysis.md`, the Java-efficiency portions of `phase-isolation-gap-analysis.md`, and `bomsh-java-performance-optimization.md` |
| **Scope** | Java builds (Maven and Gradle). Other languages capture inline during the build and have no separate dependency-resolution step. |
| **Status** | Active design; baseline optimizations delivered, US-1/US-2 pending implementation |
| **Author** | OmniBOR Analysis project |
| **Drafted** | 2026-06-24 (Cascade) |

> This is the **single detailed engineering reference** for Phase 1
> build-speed and efficiency work. The matching user stories
> (`phase1-build-speed-subissues.md`) stay deliberately high-level for the
> extended team; all evidence, code locations, and implementation detail
> live here.

---

## 1. Purpose

Phase 1 is the build-capture phase: it runs alongside the customer's build
and produces the artifacts Phase 2 consumes to generate the SPDX SBOM. The
overriding constraint is **minimal impact on the customer's build time**.

This document explains where Phase 1 time is spent, what has already been
optimized, and the concrete design + implementation plan for the remaining
beneficial changes. Each plan maps to a user story:

| Story | Title | Status |
|-------|-------|--------|
| US-1 | Reuse captured dependency data instead of resolving it twice | Pending — highest value |
| US-2 | Efficient dependency capture for multi-module Java projects | Pending — Gradle multi-project |
| US-3 | Conditional concurrency of independent post-build steps | Conditional — only if measured |

---

## 2. Background: where Phase 1 time goes (Java)

The Phase 1 post-build `adg` step has two sub-steps:

1. **Treedb generation** — `bomsh_create_bom_java.py` scans `.class` files,
   resolves them to `.java` sources, and hashes everything into the OmniBOR
   treedb.
2. **Dependency resolution** — `mvn dependency:tree` /
   `gradlew dependencies` resolves the transitive dependency graph and is
   written to `maven_deps.json` / `gradle_deps.json` in `bom_dir`.

### 2.1 Split-timing evidence (EC2, June 16 2026)

Before optimization, the combined `adg` step was dominated by treedb, not
dependency resolution:

| Repo | Orchestrator | Treedb | Dependency resolution | Treedb share |
|------|--------------|--------|-----------------------|--------------|
| `dependency-check` | Maven | 240.85s | 3.47s | **98.6%** |
| `spring-boot` | Gradle | 486.09s | 139.64s | **77.7%** |

`dependency-check` produced 55,673 treedb entries; `spring-boot` 113,524.

---

## 3. Delivered optimizations (baseline — already in place)

These shipped already and are **not** new work. They reset the baseline for
the remaining plan.

| Optimization | Effect | Delivered |
|--------------|--------|-----------|
| Offline dependency resolution (`-o` / `--offline`) | Skips network metadata checks after a successful build | PR #187 |
| Lifecycle skip flags (tests, javadoc, enforcer, checkstyle) | Prevents unneeded plugin work during resolution | PR #187 |
| Reuse warm Gradle daemon (dropped `--no-daemon` for the query) | Avoids cold JVM start for the post-build query | PR #187 |
| Per-sub-step timing → `adg_substeps.json` | Makes the treedb-vs-resolution split measurable | PR #187 |
| Pure-Python treedb fast path | Removes per-file subprocess spawning | PR #189 |
| Module targeting (`-pl`) inferred from build steps | Limits resolution to modules that produce output | PR #180 |

### 3.1 The treedb fast path (PR #189) in brief

The treedb step was slow because the upstream `bomsh_create_bom_java.py`
shelled out per `.class` file — roughly `3N` subprocess spawns per JAR
(`git hash-object` twice plus `diff -q`), e.g. ~18,000 `fork+exec` calls
for `dependency-check` alone. The fix replaced those with pure-Python
equivalents, applied at Docker build time without forking upstream:

- `git hash-object` → `hashlib.sha1` of `blob <size>\0<data>`
- `diff -q` → `filecmp.cmp(shallow=False)`
- `find` → `os.walk`; `jar -xf` → `zipfile`

**Result (EC2, June 22 2026, golden-clean):** the treedb step (the Phase 2
`Analysis` column) dropped to a minor cost for small/medium repos
(`jsoup` 8.4s, `crawler4j` 7.6s, `checkstyle` 13.2s, `logging-log4j2`
18.6s). `bc-java` remains large in absolute terms (224s) purely due to its
multi-module output volume.

**Net effect on this plan:** with treedb no longer dominant and dependency
resolution already offline, the largest *remaining* inefficiency is
**resolving dependencies twice** (Section 4), and the largest remaining
*Gradle-specific* cost is **per-subproject query start-up** (Section 5.2).

---

## 4. Core remaining inefficiency: duplicate dependency resolution

Dependency resolution runs **twice** for Java today — once in Phase 1
(saved, then ignored) and again in Phase 2.

**Phase 1 resolves and saves the graph:**

- `app/pipeline/interception.py` — `MavenDepTreeStrategy.generate_adg()`
  runs `run_maven_dep_tree()` and writes `maven_deps.json`.
- The Gradle strategy writes `gradle_deps.json` the same way.

**Phase 2 ignores those files and resolves again against `repo_dir`:**

- `app/spdx/java_generator.py` — `_get_maven_deps()` calls
  `get_maven_deps()` / `get_gradle_deps()`.
- `app/spdx/maven_parser.py` — `get_maven_deps()` runs `mvn dependency:tree`
  as a fresh subprocess against the source tree.
- `app/spdx/gradle_parser.py` — `get_gradle_deps()` runs
  `./gradlew dependencies` similarly.

This is wasteful on two axes:

1. **Time** — a full duplicate resolution (minutes on large repos).
2. **Phase isolation** — Phase 2 depends on `repo_dir`, which does not exist
   in an ephemeral CI/CD pipeline where build and reporting run on separate
   machines. (Full multi-language audit: `phase-isolation-gap-analysis.md`.)

---

## 5. Design & implementation plan

### 5.1 US-1 — Phase 2 reuses captured dependency data

**Goal:** Phase 2 reads `maven_deps.json` / `gradle_deps.json` from
`bom_dir` and stops re-running the resolver against `repo_dir`.

**Current → target:**

- Current: `java_generator._get_maven_deps()` → live
  `get_maven_deps()` / `get_gradle_deps()` against `repo_dir`.
- Target: load the captured JSON from `bom_dir`; fall back to the live
  command **only** if the JSON is absent (e.g. legacy runs), with a clear
  warning.

**Format-compatibility risk (must verify):**

- Phase 1 writes JSON parsed from `mvn dependency:tree -DoutputType=dot`
  (`parse_dot_output`).
- Phase 2 currently parses the **text** form (`parse_dep_tree`).
- The downstream SPDX generator expects dependency dicts with
  `groupId`, `artifactId`, `version`, `scope`, `direct`, `optional`,
  `parent`. The implementation must confirm the captured JSON carries the
  identical field set/semantics so the SPDX does not change. This is the
  primary reason golden validation is mandatory (Section 7).

**Files likely touched:**

- `app/spdx/java_generator.py` — read captured JSON; inject as the
  dependency source.
- `app/spdx/maven_parser.py` / `app/spdx/gradle_parser.py` — keep the live
  path as a guarded fallback only.
- Possibly a small loader helper in the Phase 2 path that resolves the
  `bom_dir` JSON path.

**Acceptance (engineering view):** identical SPDX vs golden across
representative Maven and Gradle repos; no `repo_dir` read for dependency
data; graceful, explicit fallback when capture is missing.

### 5.2 US-2 — Efficient capture for multi-module Java projects

**Goal:** stop starting a separate query process per Gradle subproject.

**Current behavior:** `app/pipeline/gradle_dep_tree_parser.py` —
`get_all_gradle_deps()` runs `run_gradle_dep_tree()` once for the root and
then **once per subproject** discovered in `settings.gradle`. Each call is a
separate Gradle invocation.

**Design caveat (do not guess):** a plain `./gradlew dependencies` at the
root does **not** aggregate subproject dependencies. A correct
single-invocation approach needs either a generated aggregate task
(an `allDeps`-style task that iterates `allprojects`) or a single call that
emits all subprojects' resolved configurations. The chosen mechanism must
be generic (no per-repo logic) and produce a dependency set identical to
the current per-subproject union.

**Files likely touched:**

- `app/pipeline/gradle_dep_tree_parser.py` — query construction and
  aggregation.

**Acceptance (engineering view):** minimum build-tool invocations needed
for completeness; identical dependency set vs the per-subproject result;
single-module projects unchanged; golden-clean on a representative
multi-module repo.

### 5.3 US-3 — Conditional concurrency of independent post-build steps

**Goal:** overlap treedb generation and dependency resolution **only where
it measurably reduces wall time**.

**Context:** treedb and resolution are independent (treedb reads `.class`
files; resolution reads `pom.xml` / `build.gradle`). Concurrency saves up
to `min(treedb, resolution)` of wall time. After PR #189 + offline mode,
Maven resolution is ~1–2% of `adg`, so the Maven payoff is negligible; the
Gradle payoff is larger but still secondary.

**Design (if pursued):** run the two sub-steps via a
`concurrent.futures.ThreadPoolExecutor` in the relevant `generate_adg()`
paths, collecting results before writing outputs. Keep sequential where
measurement shows no benefit, to avoid needless complexity.

**Files likely touched:**

- `app/pipeline/interception.py` — `generate_adg()` for the Gradle (and
  possibly Maven) strategy.

**Acceptance (engineering view):** concurrency used only where it
measurably helps; identical SPDX vs sequential; no added complexity where
the gain is negligible.

---

## 6. Phase-isolation context

US-1 directly advances the mandatory phase-isolation goal: Phase 2 must
operate solely on `bom_dir` artifacts and never read `repo_dir`, because
`repo_dir` is destroyed when the build stage exits in modern pipelines.
US-1 removes the Java dependency-graph dependency on `repo_dir`; the
remaining `repo_dir` reads (binaries, version files, static manifests, and
the C/C++/Rust/Go paths) are catalogued in
`phase-isolation-gap-analysis.md` and tracked separately under the
phase-isolation sub-issues.

---

## 7. Validation plan (mandatory)

Per the project golden-file policy, no build-speed change ships on a
"looks faster" basis. Every change in Section 5 must:

1. Pass the full local unit-test suite and coverage gates.
2. Be run on the EC2 build host across representative Java repos (Maven and
   Gradle, including a multi-module project).
3. Produce SPDX **identical to the golden baselines** — report exact diffs
   if any and STOP for user review; never update golden files without
   explicit approval.
4. Confirm dependency counts and treedb entry counts are unchanged.

---

## 8. Recommendation status matrix

| Recommendation | Source | Status |
|----------------|--------|--------|
| Offline dependency resolution | build-time-analysis §3a/§4 | Done (#187) |
| Lifecycle skip flags | build-time-analysis §3b | Done (#187) |
| Reuse warm Gradle daemon | build-time-analysis §4 | Done (#187) |
| Split-timing instrumentation | build-time-analysis §5 | Done (#187) |
| Pure-Python treedb fast path | bomsh-java-performance §4–§5 | Done (#189) |
| Module targeting (`-pl`) | build-time-analysis §3d | Done (#180) |
| **Phase 2 reuses captured dep JSON** | gap-analysis §2.1, §7 | **Pending — US-1** |
| **Single-invocation Gradle query** | build-time-analysis §4 (pending) | **Pending — US-2** |
| Concurrency of treedb + resolution | build-time-analysis §3c | Conditional — US-3 |
| Direct POM parsing (no Maven) | build-time-analysis §3e | Not recommended |
