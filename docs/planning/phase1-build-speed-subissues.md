# Sub-Issue Drafts — Phase 1 Build-Speed & Efficiency

| | |
|---|---|
| **Parent issue** | TBD — assigned by the user |
| **Author** | Ted G. |
| **Drafted** | 2026-06-24 (Cascade) |
| **Status** | Draft — ready to attach under the chosen parent issue |
| **Scope** | **Java builds** (Maven and Gradle). Other languages capture inline during the build and are not affected. |
| **Origin** | Verified findings from `docs/deep-dive/phase-isolation-gap-analysis.md` and `docs/deep-dive/phase-isolation-build-time-analysis.md`. |

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

## US-1 — Reuse captured dependency data instead of resolving it twice

**Applies to:** Java builds (Maven and Gradle)

**Estimate:** ~3 AI-days

**Priority:** Highest — largest measured win, and it also advances the
mandatory phase-isolation goal (see related SI-4 in
`sidecar-phase-isolation-subissues.md`).

**User Story**

As a release engineer,
I want the SBOM step to reuse the dependency information already captured
during the build instead of recalculating it,
so that we do not pay for the same expensive dependency resolution twice
and reporting runs faster.

**Why this matters**

Today the build's dependency graph is resolved during capture and saved,
then the reporting step throws that away and resolves it a second time
against the original workspace. On large projects the duplicated step costs
minutes and also forces the reporting step to depend on a workspace that no
longer exists in modern pipelines.

**Acceptance Criteria**

- Given a build whose dependency information was captured, when the SBOM is
  generated, then it uses the captured data and does not re-run the build
  tool's dependency resolver.
- Given the captured data is used, when the resulting SBOM is compared to
  the previously trusted output, then the two are identical.
- Given a build where the captured data is missing or incomplete, when the
  SBOM is generated, then it fails clearly (or uses a documented fallback)
  rather than silently producing a wrong SBOM.
- Given the change, when it is validated on representative Maven and Gradle
  projects on a real build host, then all produce identical, golden-clean
  results.

---

## US-2 — Capture dependencies efficiently for multi-module Java projects

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
