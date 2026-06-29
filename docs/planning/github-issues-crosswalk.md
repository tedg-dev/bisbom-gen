# GitHub Issues Crosswalk & Recreation Record

| | |
|---|---|
| **Purpose** | Durable record tying each drafted Main issue and sub-issue to the PR(s) that implement it, so the hierarchy can be recreated and linked once GitHub Projects/Issues access is restored. |
| **Maintained by** | Cascade (update as PRs merge) |
| **Last updated** | 2026-06-29 |

---

## Why this exists

GitHub Projects/Issues access is temporarily unavailable, so issues cannot be
created or updated right now. This file is the single place that maps every
drafted Main issue and sub-issue to its implementing PR(s). When access
returns, the issues team uses this to recreate the issue hierarchy and link
the PRs.

Issues live under the **tedg-cisco** org; PRs live in **tedg-dev/omnibor-analysis**.
Always reference PRs with the fully-qualified cross-repo form
`tedg-dev/omnibor-analysis#<n>` — never a bare `#<n>`, which would not link.

---

## Hierarchy

Single **Epic** (created by the issues team) -> **Main issues** (one per
theme / planning doc) -> **sub-issues** (drafted in the matching planning doc).

---

## Main issues (themes) and their drafts

| Main issue (GitHub title) | Planning doc | Sub-issues | Existing GitHub issue # |
|---|---|---|---|
| Build-Based SBOM Capture & Delivery (Sidecar + Phase Isolation) | `sidecar-phase-isolation-subissues.md` | SI-1..SI-5 | — |
| Phase 1 Build-Speed & Efficiency (Java) | `java/phase1-build-speed-subissues.md` | US-2, US-3 (US-1 moved) | — |
| Faster SBOM Generation for Java Builds (Retrospective) | `java/retro-subissue-java-treedb-perf.md` | SI-R1 | — |
| Java Phase 2: Generate SBOMs From Phase 1 Metadata Without the Source Tree | `java-phase2-consume-dep-capture-subissue.md` | (1) Generate from metadata (Maven/Gradle); (2) Deliver Java SBOMs to Corona | Corona #11003; handoff scope #11004 |

---

## PR crosswalk

| PR | Title | Theme -> sub-issue (index label) | Status |
|---|---|---|---|
| `tedg-dev/omnibor-analysis#194` | Phase 2 generates SBOMs from Phase 1 metadata, no source tree | Java Phase 2 main issue -> sub (1) Generate from metadata; index **A1**; SI-4 (Java) / Corona #11003 | Merged |
| `tedg-dev/omnibor-analysis#196` | Single-invocation Gradle dependency capture (US-2) | Phase 1 Build-Speed (Java) -> **US-2**; index **A4** | Merged |
| `tedg-dev/omnibor-analysis#195` | Java build-based SBOM sell doc + diagrams + planning reorg | Java Main A enablement (supporting docs) | Merged |
| `tedg-dev/omnibor-analysis#193` | Phase 1 build-speed design consolidation | Phase 1 Build-Speed (Java) design reference | Merged |
| `tedg-dev/omnibor-analysis#192` | Phase-isolation planning user stories + C/C++ design relocation | Planning / docs | Merged |
| `tedg-dev/omnibor-analysis#191`, `#189`, `#187` | Treedb SBOM-generation speedup (retro) | Retrospective -> **SI-R1**; index **A6** | Merged |

Index labels (**A1**, **A4**, ...) refer to the rows in
[`README.md`](README.md), the priority-ordered planning index.

---

## Still open / not yet implemented (no PR)

| Item | Theme -> sub-issue (index label) | Status |
|---|---|---|
| Phase 2 output set + hand-off manifest | Java Phase 2 main issue; index **A2**; Corona #11004 | Scoped, no PR |
| Overlap independent post-build steps (measure first) | Phase 1 Build-Speed (Java) -> **US-3**; index **A5** | Conditional, no PR |
| Deliver Java build evidence to Corona | Java Phase 2 main issue -> sub (2); index **A7**; SI-5 (Java) | Planned, no PR |
| Non-Maven/Gradle build-tool support (Ant/Ivy, Bazel, `make`) | Phase 1 Java capture (new sub-issue to draft) | Next R&D, no PR |

---

## Recreation checklist (run when Issues access returns)

1. Create the single **Epic** (issues team).
2. For each theme above, create **one Main (regular) issue** under the Epic,
   using its GitHub title from the table.
3. Under each Main issue, create the **sub-issues** from the matching planning
   doc, reusing the drafted User Story + Acceptance Criteria.
4. Link the implementing PR(s) from the **PR crosswalk** to each sub-issue and
   mark delivered items Done.
5. In GitHub issue text, use plain **"days"** (never "AI-days"); keep User
   Story keywords **ALL CAPS** (AS A / I WANT / SO THAT).
6. Reference PRs as `tedg-dev/omnibor-analysis#<n>` (cross-repo links).
