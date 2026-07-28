# Sub-Issue Drafts — Phase 1 Build-Speed & Efficiency

| | |
|---|---|
| **Main issue** | Phase 1 Build-Speed & Efficiency (Java) |
| **Epic** | Single epic — this main issue is added to it later by the issues team |
| **Author** | Ted G. |
| **Drafted** | 2026-06-24 (Cascade) |
| **Status** | US-2 delivered & merged (PR `tedg-dev/omnibor-analysis#196`, golden-clean on bc-java + spring-boot); US-5 delivered & merged (inline GitOID capture, PR `tedg-dev/omnibor-analysis#212`; #11097 In Development); US-6 added (inline-hashing golden-clean validation — MRJAR/multi-module correctness + build-logic JAR exclusion — #11100 In Development, golden-clean on all 7 Java repos, PR pending); US-4 deferred (in-memory JAR processing); US-3 optional/low; US-1 moved — see below |
| **Scope** | **Java builds** (Maven and Gradle). Other languages capture inline during the build and are not affected. |
| **Detailed design** | `docs/sidecar/java/reference/phase1-build-speed-design.md` (single engineering reference — design, evidence, code-level plan). |

---

## Conventions

- **Template:** standard User Story (`As a … I want … so that …`) with
  **Acceptance Criteria** in Given/When/Then form.
- **Granularity:** each story is consolidated to cover at least two days of
  work.
- **Validation gate:** every change MUST be validated on a real build host
  and produce SBOMs identical to the golden baselines before it is
  accepted. No change ships on a "looks faster" basis alone.

---

## US-1 — (Moved) Reuse captured dependency data

**Status: do NOT create this as a sub-issue here.** This work is the same
deliverable as the dedicated main issue **"Java Phase 2: Generate SBOMs
From Phase 1 Metadata Without the Source Tree"**
(`java-phase2-consume-dep-capture-subissue.md`), which is the canonical,
detailed spec. Create it there, under that main issue.

**Why it moved:** the work is primarily an architecture-correctness change
(Phase 2 must generate SBOMs from Phase 1 metadata with **no source-tree
access**), not merely a speed optimization. Avoiding the second dependency
resolution is a welcome side effect, but it does not belong in the
build-speed theme as a standalone story.

**Correctness note (was an error here):** an earlier draft claimed the
reused result would be "identical to the previously trusted output" from
the capture as-is. That is **only** true with the parser-only per-module
capture fix described in the Java Phase-2 main issue — today's capture is
lossy (globally de-duplicated by `(groupId, artifactId)` and missing the
`optional` flag). The two are therefore inseparable and are tracked
together there.

---

## US-2 — Capture dependencies efficiently for multi-module Java projects

**Status:** Delivered. Multi-module Gradle capture now runs in a single
`gradlew` invocation via an injected init script and was validated
golden-clean on bc-java (11 modules) and spring-boot (186 modules). See
the detailed design reference for the mechanism and findings.

**Applies to:** Java builds (Gradle multi-project in particular)

**Estimate:** ~2 AI-days

**Priority:** Medium — clear win for large multi-module Gradle projects;
needs careful validation because it changes how dependency data is
gathered.

**User Story**

As a product build team with a large multi-module Java project,
I want dependency capture to query the project efficiently rather than
starting a fresh tool process for every module,
so that the reporting step does not scale poorly with the number of
modules.

**Why this matters**

Multi-module Gradle capture currently starts a separate query process per
subproject. For projects with many modules this multiplies start-up cost
many times over, which dominates the capture time for those builds.

**Acceptance Criteria**

- Given a multi-module Java project, when dependency information is
  captured, then it is gathered with the minimum number of build-tool
  invocations needed for completeness.
- Given the more efficient capture, when its output is compared to the
  previous per-module result, then the set of dependencies is identical.
- Given a single-module project, when capture runs, then its behavior and
  results are unchanged.
- Given the change, when it is validated on a representative multi-module
  project on a real build host, then the SBOM is golden-clean.

---

## US-3 — Overlap independent post-build steps only when it measurably helps

> **Priority note:** This is **optional / low value**. Earlier wins (faster
> component hashing, offline resolution, warm daemon) already shrank the gap.
> Pursue **only** if measurement on a real build host shows a real reduction.

**Applies to:** Java builds

**Estimate:** ~1 AI-day (conditional — only pursued if measurement justifies it)

**Priority:** Low / conditional. Earlier optimizations (faster component
hashing and offline dependency resolution) shrank the remaining gap, so
this is worth doing only where measurement shows a real reduction.

**User Story**

As a platform engineer,
I want independent post-build capture steps to run at the same time when it
measurably reduces total time,
so that build-host time is used efficiently — without adding complexity
where the gain is negligible.

**Acceptance Criteria**

- Given two independent capture steps, when running them concurrently
  measurably reduces total time on a representative build, then they run
  concurrently.
- Given a build type where concurrency shows no measurable benefit, when
  capture runs, then it stays sequential to avoid needless complexity.
- Given concurrent execution, when the SBOM is produced, then it is
  identical to the sequential result.

---

## US-4 — Process JAR class files fully in memory (no extract-to-disk)

**Status:** Deferred — implement after EC2 golden validation of the current
extract-to-disk fast-IO variant. This is the **remaining build-speed item
with real value.**

**Applies to:** Java builds (Phase 1 component processing of JARs)

**Estimate:** ~1–2 AI-days

**Priority:** Medium-high — eliminates the per-JAR temp-directory extraction
lifecycle (est. ~5–10s/build for JAR-heavy projects).

**User Story**

As a product build team with many JAR dependencies,
I want JAR component hashing to read `.class` bytes directly from the archive
in memory rather than extracting every JAR to a temp directory,
so that Phase 1 avoids the disk I/O and subprocess churn of extract-to-disk.

**Why this matters**

Component processing currently extracts each JAR (`jar -xf` /
`zipfile.extractall`) to a temp directory, hashes files on disk, then
`rmtree`s it. For builds with many JARs this disk lifecycle dominates.
Reading `.class` entries from the zip in memory and hashing with
`git_blob_hash_data` removes the entire unbundle -> find -> `rmtree` cycle.

**Acceptance Criteria**

- Given a JAR, when its components are processed, then `.class` GitOIDs are
  computed from in-memory bytes with no extraction to disk.
- Given the in-memory path, when its output is compared to the extract-to-disk
  result, then the GitOIDs and the SBOM are identical (golden-clean).
- Given a malformed or edge-case archive, when processed, then it fails
  gracefully with a clear error (no silent skip).
- Given the change, when validated on a representative multi-JAR build on a
  real build host, then the SBOM matches the golden baseline.

**Implementation note:** refactor the class-processing path to accept
in-memory data rather than file paths; mirrors the existing fast-IO /
classreader patches in `docker/patches/`. Deferred per the follow-up noted in
`retro-subissue-java-treedb-perf.md`.

---

## US-5 — Capture GitOIDs inline during the build (eliminate the post-build rescan)

**Status:** Delivered & merged (Python assembler + Maven/Gradle strategy
wiring + config flag + `LD_PRELOAD` shim) in PR
`tedg-dev/omnibor-analysis#212`. The config flag
(`omnibor_java.java_inline_hash`) now defaults to `true` after the byte-identity
gate (US-6) passed golden-clean on the EC2 build host; it remains as an explicit
override to force the legacy rescan on platforms where the shim cannot interpose
(musl/Alpine, V4). GitHub sub-issue **#11097** (child of #11005,
status **In Development**).

**Applies to:** Java builds (Maven and Gradle), sidecar / phase-isolated mode

**Estimate:** ~3 days

**Priority:** High — removes the post-build workspace rescan that dominates
Phase 1 wall time and is **impossible in a phase-isolated sidecar** where the
build workspace is destroyed when the job ends. Directly serves the Main A
constraint of lowest possible impact on the enterprise build phase.

**User Story**

AS A product build team running Java builds in a phase-isolated CI/CD pipeline,
I WANT the OmniBOR GitOIDs for my compiled classes and JARs computed inline as
the build produces them,
SO THAT SBOM evidence is captured without a post-build workspace rescan and
without changing my build commands.

**Why this matters**

Today the Java `generate_adg()` defers all gitoid/treedb work to a post-build
workspace rescan (`bomsh_create_bom_java.py`: `find` + unzip + re-hash of every
`.class`/`.jar`). That rescan cannot run in a phase-isolated sidecar because the
workspace no longer exists, and even where it can, it dominates Phase 1 time.
Every treedb input is derivable from the bytes of each artifact at the instant
the build writes it, so capturing inline turns `generate_adg()` into an assembly
step over an append-only capture log.

**Acceptance Criteria**

- Given a Java build with inline hashing enabled, when the build finalizes each
  `.class`/`.jar`, then its git-blob SHA-1 and SHA-256 gitoid are captured to an
  append-only log with no change to the build command.
- Given the capture log, when `generate_adg()` runs, then it assembles the
  OmniBOR treedb from the log with no workspace rescan (no `find`, unzip, or
  re-hash), and fails loudly if the log is missing or incomplete.
- Given the assembled treedb, when compared to the legacy rescan result on a
  real build host, then the treedb and the SBOM are byte-identical
  (golden-clean).
- Given the native build, when inline hashing is enabled, then
  `pom.xml`/`build.gradle` and the `mvn`/`gradle` invocation are unchanged
  (env-only injection) and build-phase overhead stays within a few percent.
- Given both Maven and Gradle projects, when inline hashing runs, then one
  generic code path handles both (no per-repo or per-tool logic).

**Design reference:** `docs/sidecar/java/reference/inline-hashing-interception-design.md`
(with `inline-hashing-explained.md` and the four sequence/mechanism diagrams).

---

## US-6 — Validate inline hashing golden-clean (MRJAR/multi-module correctness + build-logic JAR exclusion)

**Status:** Implemented on branch `feat/java-inline-hashing` (follow-on to
the merged US-5 / PR `tedg-dev/omnibor-analysis#212`); **golden-clean on all
eight Java repos at package and file level** (re-validated on EC2 with the flag
on — spring-boot and dependency-check confirmed 0 file diffs); the flag is now
defaulted `true` in the same PR (#213). GitHub sub-issue
**#11100** (child of #11005, status **In Development**).

**Applies to:** Java builds (Maven and Gradle), sidecar / phase-isolated mode

**Estimate:** ~2 days

**Priority:** High — this is the byte-identity gate that lets the
`omnibor_java.java_inline_hash` flag be turned on. US-5 shipped the inline
path with the flag off pending exactly this validation.

**User Story**

AS A product build team using Java inline-hashing sidecar capture,
I WANT the inline-assembled OmniBOR treedb to be byte-identical to the legacy
workspace rescan across Multi-Release and multi-module Java builds, with
build-logic JARs excluded from product SBOMs,
SO THAT inline hashing can be enabled with SBOM output that exactly matches the
approved golden baselines.

**Why this matters**

Validating US-5 against real multi-module and Multi-Release JAR (MRJAR) repos
(`logging-log4j2`, `spring-boot`, `dependency-check`) surfaced differences
versus the legacy rescan in JAR-member correlation and source attribution,
plus one class of over-inclusion (Gradle `buildSrc` build-logic JARs). Making
the inline output byte-identical and correctly scoped is the remaining
"golden-clean" acceptance criterion of US-5 and the gate to enabling the flag.

**Acceptance Criteria**

- Given an MRJAR build, when the treedb is assembled from the capture log,
  then JAR members are correlated by content (git-blob SHA-1), not name, and
  versioned `META-INF/versions/<N>/` members are retained.
- Given a class compiled identically into a base module and a sibling module,
  when its source and canonical path are resolved, then the attribution is
  byte-identical to the legacy rescan (deterministic, order-independent).
- Given a Gradle project with a reserved `buildSrc` directory, when product
  SBOM targets are selected, then build-logic JARs are excluded generically
  (not by repo name), consistent across sidecar and standalone modes.
- Given all configured Java repos, when run on a real build host, then every
  SBOM is golden-clean at package AND file level.
- Given both Maven and Gradle projects, when the above runs, then one generic,
  config-driven code path handles both.

**Design reference:** `docs/sidecar/java/reference/inline-hashing-interception-design.md`;
investigation `docs/issues/gradle-buildsrc-not-a-product-sbom-target.md`.

---

## Already delivered (no new work)

For reference, the following earlier recommendations are already in place
and are **not** part of this set:

| Recommendation | Status |
|----------------|--------|
| Offline dependency resolution after the build | Done |
| Skip unnecessary build-lifecycle work during resolution | Done |
| Reuse the warm build daemon instead of a cold start | Done |
| Per-step timing breakdown for diagnosis | Done |
| Faster per-component processing (the former dominant bottleneck) | Done |
| Targeting only the modules that produce output | Functional today |
