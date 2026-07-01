# Sub-Issue Drafts — Phase 1 Build-Speed & Efficiency

| | |
|---|---|
| **Main issue** | Phase 1 Build-Speed & Efficiency (Java) |
| **Epic** | Single epic — this main issue is added to it later by the issues team |
| **Author** | Ted G. |
| **Drafted** | 2026-06-24 (Cascade) |
| **Status** | US-2 delivered & merged (PR `tedg-dev/omnibor-analysis#196`, golden-clean on bc-java + spring-boot); US-4 added (deferred, in-memory JAR processing); US-3 optional/low; US-1 moved — see below |
| **Scope** | **Java builds** (Maven and Gradle). Other languages capture inline during the build and are not affected. |
| **Detailed design** | `docs/deep-dive/sidecar/java/phase1-build-speed-design.md` (single engineering reference — design, evidence, code-level plan). |

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
