# Main Issue Draft — Java Phase 2: Generate SBOMs From Phase 1 Metadata Without the Source Tree

| | |
|---|---|
| **Main issue** | Java Phase 2: Generate SBOMs From Phase 1 Metadata Without the Source Tree |
| **Epic** | Single epic — this main issue is added to it later by the issues team |
| **Relationship** | Java realization of SI-4 (`sidecar-phase-isolation-subissues.md`); supersedes US-1 in `phase1-build-speed-subissues.md`; **hosts the Java slice of SI-5** (delivery to Corona), broken out of the all-languages SI-5 |
| **Applies to** | Java (Maven and Gradle) sidecar mode |
| **Author** | Ted G. |
| **Drafted** | 2026-06-24 (Cascade) |
| **Status** | ✅ Delivered — A1 (#11003) implemented and merged in `tedg-dev/omnibor-analysis#194`; A2 (#11004, hand-off manifest) scoped |
| **Estimate** | ~3 AI-days (implementation + tests), excluding EC2 golden validation |
| **Planned sub-issues** | (1) Generate from metadata — Maven and Gradle (see `docs/sidecar/phase2-consume-dep-capture.md` §8); (2) Deliver Java SBOMs to Corona (Java slice of SI-5) |
| **Design** | `docs/sidecar/phase2-consume-dep-capture.md` |

---

## Background (verified facts, not judgments)

The confirmed enterprise architecture is **sidecar + phase isolation**,
with one **non-negotiable constraint**:

- **Phase 2 has no access to the source repository / build workspace.** In
  the target CI/CD topology, Phase 1 (interception) and Phase 2 (SBOM
  generation) run on **different machines**, and the source tree is gone by
  the time Phase 2 runs.

Within that model:

- **Phase 1** performs OmniBOR build interception and **collects** all
  metadata into the intermediary artifactory. It must be both **thorough**
  (capture everything Phase 2 could need) and **fast** (minimal build-time
  impact).
- **Phase 2** **processes** that collected metadata into SBOMs. It may
  duplicate some of Phase 1's processing, but it must **never read the
  source tree**.

As built (delivered in `tedg-dev/omnibor-analysis#194`), Java Phase 2
satisfies this constraint:

- Phase 1 (`MavenDepTreeStrategy` / `GradleDepTreeStrategy` in
  `app/pipeline/interception.py`) captures **per-module** dependency
  subtrees to `maven_deps.json` / `gradle_deps.json`, parsed from the
  default `mvn dependency:tree` **text** output by
  `app/pipeline/maven_dep_tree_parser.py:parse_text_output` (Gradle:
  `gradle_dep_tree_parser.get_all_gradle_deps`). The capture de-duplicates
  **within** a module only — a component shared by two modules appears
  under both — and preserves the `optional` flag.
- Phase 2 (`generate_java_adg_spdx()` in `app/pipeline/lang_runners.py`)
  reads that capture via `app/spdx/dep_capture_reader.py`
  (`load_capture()` → `get_module_deps()`), resolving each output JAR to
  its module from artifact metadata (JAR filename / build-output path) —
  with **no source-tree access** and no `mvn dependency:tree` /
  `gradlew dependencies` re-run.

The enterprise split therefore works with no source tree. A live-resolution
fallback remains **only** for co-located dev/test runs where the source
tree happens to be present; it never generates golden files (golden files
are sidecar-generated, where the capture is always present).

---

## User Story

As a release engineer whose CI/CD runs Phase 1 and Phase 2 on different
machines,

I want Phase 2 to generate every Java SBOM **solely from the metadata
Phase 1 stored in the artifactory**,

so that SBOM generation works with **no access to the source tree**, while
Phase 1 stays fast and the SBOMs remain as accurate as the trusted
standalone baseline.

---

## Acceptance Criteria

- Given a Phase 2 run with **no source tree present**, when it generates
  the `_build` SBOM for each output JAR, then it succeeds using **only**
  Phase 1 metadata and runs **no** `mvn dependency:tree` /
  `gradlew dependencies` (or any other source-reading command).
- Given a multi-module reactor where a third-party component is a
  dependency of **two or more modules**, when Phase 2 generates each
  module's `_build` SBOM, then that component appears in **every** module
  that depends on it (no loss from cross-module de-duplication).
- Given dependencies marked `optional`, when Phase 2 generates the `_build`
  SBOM, then the `optional` status is preserved (matching today's output).
- Given Phase 1, when it captures dependency metadata, then it does so with
  **no additional resolution step** beyond the single `dependency:tree`
  invocation it already runs — Phase 1 build-time impact does not increase.
- Given the `_analyzed` SBOM view, when it is generated, then it is
  **unchanged**, because `_analyzed` does not include the dependency graph.
- Given each supported multi-module sample repo, when its `_build` SBOMs
  are generated from metadata, then any differences from the current golden
  baseline are **enumerated and reported** for human review. Golden files
  are **not** updated by Cascade.
- Given the new path, when the test suite runs, then unit tests cover:
  per-module reconstruction with a shared component, `optional` preserved,
  metadata-absent fallback, and malformed/empty metadata.
- Given the change is complete, when verification runs locally, then it
  meets the project gates (import, flake8, pytest, coverage thresholds).

---

## Explicitly In and Out of Scope

**In scope:**

- A **parser-only** enhancement to Phase 1 so the captured metadata retains
  per-module attribution and the `optional` flag. This adds **no** build
  time (same single `dependency:tree -DoutputType=dot` invocation) and is
  safe because nothing currently reads the captured file.
- Phase 2 reading that metadata and producing `_build` SBOMs without the
  source tree (duplicating graph-walking work as needed).

**Out of scope:**

- **No new resolution work added to Phase 1** — Phase 1 must not get slower.
  Only the parsing of the output it already produces changes.
- **No golden-file updates by Cascade.** Diffs are reported; the user decides.
- **No change to the `_analyzed` SBOM view.**
- Non-Java languages (tracked separately; C/C++, Go, Rust capture I/O inline
  and have no separate dependency-resolution step).

---

## Why This Is Faithful, Not Best-Effort

The raw `mvn dependency:tree -DoutputType=dot` output already contains a
**complete subtree per module** (one `digraph` block each); the current
parser collapses and de-duplicates them, discarding per-module structure.
Preserving that structure (the in-scope parser change) lets Phase 2
reconstruct each module's dependencies **faithfully** — including shared
components and `optional` flags — rather than best-effort. The trusted
accuracy baseline remains the standalone (ptrace) solution; the goal is to
match it from metadata alone.

---

## Sub-Issue — Deliver Java SBOMs to Corona (Java slice of SI-5)

Broken out of the all-languages SI-5 so that **all Java work — including
delivery — completes before C/C++ work begins**. The shared delivery
mechanism and security/auth model remain with SI-5 in the Build-Based SBOM
Capture & Delivery main issue; this sub-issue covers wiring the **Java**
pipeline's generated SBOMs into that intake and proving it end-to-end for
Java.

**User Story**

As a release manager shipping Java products,
I want the Java SBOMs produced by Phase 2 delivered automatically to the
central SBOM system (Corona),
so that every Java release has a discoverable, correctly filed SBOM with no
manual steps — before we extend the same delivery to other languages.

**Acceptance Criteria**

- Given a completed Java Phase 2 run, when its `_build` SBOM is ready, then
  it is delivered to Corona automatically, filed under the correct product,
  release, and image.
- Given delivery runs in the enterprise split, when it executes, then it
  needs only the generated SBOM and captured metadata — **no source tree**.
- Given existing company intake patterns, when the delivery path is built,
  then it reuses them (see the
  [integration wiki](https://github.com/CiscoSecurityServices/gambit/wiki/Omnibor-Build-Based-SBOM-Integration))
  rather than inventing a new mechanism, and the auth model is the shared
  one defined in SI-5.
- Given the Java delivery, when validated end-to-end on a representative
  Java repo, then the SBOM appears in Corona correctly filed and matches the
  golden baseline.
