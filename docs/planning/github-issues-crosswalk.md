# GitHub Issues Crosswalk & Recreation Record

| | |
|---|---|
| **Purpose** | Durable record tying each drafted Main issue and sub-issue to the PR(s) that implement it, so the hierarchy can be recreated and linked once GitHub Projects/Issues access is restored. |
| **Maintained by** | Cascade (update as PRs merge) |
| **Last updated** | 2026-07-08 |

---

## Why this exists

This file is the single place that maps every drafted Main issue and
sub-issue to its implementing PR(s) and GitHub issue number.

Issues live under **CiscoSecurityServices/gambit** (migrated from the
former `tedg-cisco` org). PRs live in **tedg-dev/omnibor-analysis**.
Always reference PRs with the fully-qualified cross-repo form
`tedg-dev/omnibor-analysis#<n>` — never a bare `#<n>`, which would not
link across repos. The Corona project board is **#255** (renumbered from
#12 during the org migration).

---

## Hierarchy

Single **Epic** (created by the issues team) -> **Main issues** (one per
theme / planning doc) -> **sub-issues** (drafted in the matching planning doc).

---

## Main issues (themes) and their drafts

| Main issue (GitHub title) | Planning doc | Sub-issues | GitHub issue # |
|---|---|---|---|
| Java Phase 2: Generate SBOMs From Phase 1 Metadata Without the Source Tree | `java-phase2-consume-dep-capture-subissue.md` | A1 (#11003), A2 (#11004) | #11002 |
| Phase 1 Build-Speed & Efficiency (Java) | `java/phase1-build-speed-subissues.md` | AF (#11069), A4 (#11006), A5 (#11007) | #11005 |
| Faster SBOM Generation for Java Builds (Retrospective) | `java/retro-subissue-java-treedb-perf.md` | SI-R1 | #11000 |
| Build-Based SBOM Capture & Delivery (Sidecar + Phase Isolation) | `sidecar-phase-isolation-subissues.md` | B1 (#11009), B2 (#11010), B3 (#11011), B4 (#11012), C1/C2 (#11013) | #11008 |

---

## PR crosswalk

| PR | Title | Theme -> sub-issue (index label) | GitHub issue | Status |
|---|---|---|---|---|
| `tedg-dev/omnibor-analysis#194` | Phase 2 generates SBOMs from Phase 1 metadata, no source tree | Java Phase 2 -> **A1** / SI-4 (Java) | #11003 | Merged |
| `tedg-dev/omnibor-analysis#196` | Single-invocation Gradle dependency capture (US-2) | Phase 1 Build-Speed -> **A4** / US-2 | #11006 | Merged |
| `tedg-dev/omnibor-analysis#TBD` | Java inline-hashing interception (sidecar Phase 1, eliminate post-build rescan) | Phase 1 Build-Speed -> **A10** / US-5 | #11005 | Open (flag off; EC2 golden-validation pending) |
| `tedg-dev/omnibor-analysis#200` | Java build-tool detection + `java_build_tool` override | Phase 1 Java capture -> **AF** (pilot foundation) | #11069 | Merged |
| `tedg-dev/omnibor-analysis#199` | Shared `_generate_java_treedb` helper (DRY) | Phase 1 Java capture -> **AF** (pilot foundation) | #11069 | Merged |
| `tedg-dev/omnibor-analysis#198` | Main A scope refinement + design draft | Java Main A scope (comment on #11002) | #11002 | Merged |
| `tedg-dev/omnibor-analysis#204` | C/C++ sidecar docs consolidation + reorg | Planning / docs (Main B enablement) | — | Merged |
| `tedg-dev/omnibor-analysis#195` | Java build-based SBOM sell doc + diagrams + planning reorg | Java Main A enablement (supporting docs) | — | Merged |
| `tedg-dev/omnibor-analysis#193` | Phase 1 build-speed design consolidation | Phase 1 Build-Speed (Java) design reference | — | Merged |
| `tedg-dev/omnibor-analysis#192` | Phase-isolation planning user stories + C/C++ design relocation | Planning / docs | — | Merged |
| `tedg-dev/omnibor-analysis#191`, `#189`, `#187` | Treedb SBOM-generation speedup (retro) | Retrospective -> **A6** / SI-R1 | #11000 | Merged |

Index labels (**A1**, **A4**, ...) refer to the rows in
[`README.md`](README.md), the priority-ordered planning index.

**Documentation tracker:** docs-only PRs (e.g. `#192`, `#193`, `#195`,
`#204`, `#205`, `#206`, `#207`) have no 1:1 theme issue; they are grouped
under the living documentation tracker **#11071** (In Review), which each
docs PR references with a `Part of` line. The tracker's status moves with
docs activity and carries a datetimestamped activity log.

---

## Still open / not yet implemented (no PR)

| Item | Theme -> sub-issue (index label) | GitHub issue | Status |
|---|---|---|---|
| Phase 2 output set + hand-off manifest | Java Phase 2 -> **A2** | #11004 (re-scoped) | Scoped, no PR |
| In-memory JAR class processing (no extract-to-disk) | Phase 1 Build-Speed -> **A8** / US-4 | #11055 | Deferred (validate on EC2), no PR |
| Support non-Maven/Gradle Java builds (Ant/Ivy, Bazel, `make`) | Phase 1 Java capture -> **A9** | #11066 (backlog, Proposed; parentless) | Backlog — **excluded from the Main A gate**. `tedg-dev/omnibor-analysis#202` (Draft, `Proposed` label — tables it for the pilot, fail-fast on ivy/ant/make/bazel); `#201` (Draft, `backlog` label — Ivy parser/reader) |
| Overlap independent post-build steps (measure first) | Phase 1 Build-Speed -> **A5** / US-3 | #11007 | Optional / low, no PR |
| Deliver Java build evidence to Corona | **A7** / SI-5 (Java) | — | Postponed — out of charter |
| Agree on C/C++ build observation | Main B -> **B1** / SI-1 | #11009 | Blocked on Main A |
| Auto-capture C/C++ components | Main B -> **B2** / SI-2 | #11010 | Blocked on Main A |
| Extend capture to static builds | Main B -> **B3** / SI-3 | #11011 | Blocked on Main A |
| C/C++ SBOMs from captured data, no workspace | Main B -> **B4** / SI-4 (C/C++) | #11012 | Blocked on Main A |
| Shared Corona intake + auth + non-Java delivery | Main C -> **C1/C2** / SI-5 (shared) | #11013 | Planned |

---

## Issue structure notes

The 13 themed issues (#11000–#11013), the pilot-foundation issue
**#11069** (In Review, child of #11005), the parentless A9 backlog issue
**#11066**, and the living documentation tracker **#11071** (In Review,
parentless) are live on the Corona project board (#255). Sub-issue parent
links are established (#11069 → #11005; #11066 and #11071 are intentionally
parentless). Assignee: `tedg_cisco`.

The current GitHub main issue structure (#11002, #11005, #11008) does not
map 1:1 to the planning index's Main A / B / C. See the restructuring
plan in `README.md` for how to align them.

**Formatting rules** — in GitHub issue text, use plain **"days"** (never
"AI-days"); keep User Story keywords **ALL CAPS** (AS A / I WANT /
SO THAT). Reference PRs as `tedg-dev/omnibor-analysis#<n>` (cross-repo
links).
