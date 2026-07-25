# Planning Index

Single source of truth for planned and in-flight work. Every work item has a
stable, tool-agnostic label (**Main X** / **Sub X#**). A label maps to
whatever the tracker uses — a JIRA issue, a user story, a GitHub PR — with
**1:1 as the goal**. This is a **living index**: add a row when work is
planned; never invent a competing numbering scheme.

## Conventions

- **Main X** — a master issue / epic-level workstream. **Mains are listed in
  priority order — Main A is the highest priority.**
- **Sub X#** — a sub-issue under that master.
- **Maps to** — the concrete tracker IDs (JIRA `#`, GitHub `PR`, legacy
  `SI-`/`US-` labels).
- A work item is **owned by exactly one row**; other rows *link* to it and
  never re-describe it.
- Labels are stable. Status and mappings change over time.
- Detail lives in the matching per-language folder; this index only links.

## Priority & sequencing (read first)

**TOP PRIORITY — Main A: complete Java Sidecar Phase Isolation, including all
testing.** The guiding constraint throughout Main A is the **lowest possible
impact on the enterprise build phase/cycle in CI/CD** — build and reporting
may run on different machines, and instrumentation overhead must stay minimal.

**Main A → B gate — LIFTED (2026-07-24):** Java (Main A) is functionally
complete (A8/#11055 and A12/#11104 in final review), so **Main B** (C/C++)
may now proceed. **Main C** still follows Main B. (Historically this was a
hard gate requiring 100% of Main A before any Main B work; that gate is now
cleared per the project lead.)

## Index

### Main A — Complete Java Sidecar Phase Isolation (TOP PRIORITY)

**All Java. Focus: lowest impact on the enterprise CI/CD build phase/cycle.**
Includes ALL testing. (Main A → B gate **lifted** 2026-07-24 — Java
functionally complete; **Main B may proceed**, A8/#11055 and A12/#11104 in
final review.)

Detail: build-speed sub-issues [java/phase1-build-speed-subissues.md](java/phase1-build-speed-subissues.md)
(A3–A5) with engineering design [../sidecar/java/reference/phase1-build-speed-design.md](../sidecar/java/reference/phase1-build-speed-design.md);
Java Phase 2 main issue `java-phase2-consume-dep-capture-subissue.md`
(delivered in PR #194); treedb retro [java/retro-subissue-java-treedb-perf.md](java/retro-subissue-java-treedb-perf.md).

PR/issue mapping (the crosswalk mirrors the live `CiscoSecurityServices/gambit`
issues; it is a convenience index, NOT a substitute — GitHub Issues access is
always available via the `tedg_cisco` account):
[github-issues-crosswalk.md](github-issues-crosswalk.md).

| Sub | Title | Status | Maps to |
|-----|-------|--------|---------|
| AF | Java Phase 1 capture foundation — build-tool detection + shared treedb helper | Merged (issue **In Review**) | #11069 / PRs #199, #200 |
| A1 | Phase 2 generates SBOMs from Phase 1 metadata, no source tree (phase-isolation core) | Merged | SI-4 (Java) / #11003 / PR #194 |
| A2 | Phase 2 output set + hand-off manifest | Closed — not planned (#11004): peer team integrates Phase 2 into Corona directly, so no hand-off boundary is needed; Java charter complete at #11003 (A1) | #11004 → [java/java-phase2-11004-handoff-scope.md](java/java-phase2-11004-handoff-scope.md) |
| A3 | Build efficiency — reuse captured dependency data (no double resolution) | Delivered via A1 | US-1 |
| A4 | Build efficiency — single-invocation multi-module Gradle capture | Merged | US-2 / PR #196 |
| A5 | Build efficiency — overlap independent post-build steps only when measurable | Closed — won't do (#11007, not planned): Phase 2 is out-of-band and inline hashing (A10) already removed the hot path | US-3 |
| A6 | Treedb SBOM-generation speedup (retro) | Delivered | SI-R1 / PRs #189, #187, #191 |
| A7 | Deliver Java build evidence to Corona (Java delivery slice) | Postponed — out of charter (Corona / Phase 2-incorporation team owns delivery + verification) | SI-5 (Java) |
| A8 | Build efficiency — fully in-memory JAR class processing (no extract-to-disk) | **PR #211 open** — tested (1886 pass, 99% cov, patch files 100%) + EC2 golden-validated 2026-07-14 (jsoup/checkstyle identical); synced with `main` (mergeable), awaiting review. Note: EC2 validation predates the inline-hashing default, so A8 now primarily benefits the `java_inline_hash: false` fallback path | US-4 / #11055 |
| A9 | Support non-Maven/Gradle Java builds (Ant/Ivy, Bazel, `make`) | **Backlog** — parentless issue, not in the initial pilot; **excluded from the Main A completion gate** | #11066 (Proposed) / [java/java-nonmaven-gradle-build-tools-subissue.md](java/java-nonmaven-gradle-build-tools-subissue.md) |
| A10 | Build efficiency — inline GitOID capture during the build (eliminate post-build rescan) | Delivered & merged (PR #212); **enabled by default** (`java_inline_hash: true`), golden-validated via A11 (PR #213) | US-5 / #11097 (child of #11005, In Review) / PR tedg-dev/omnibor-analysis#212 — [java/phase1-build-speed-subissues.md](java/phase1-build-speed-subissues.md) |
| A11 | Inline-hashing golden-clean validation — MRJAR/multi-module correctness + build-logic JAR exclusion | **Merged (PR #213)**; golden-clean on all 7 Java repos; A10 flag enabled by default | US-6 / #11100 (child of #11005, In Review) — [java/phase1-build-speed-subissues.md](java/phase1-build-speed-subissues.md) |
| A12 | Build efficiency — capture the Gradle dependency graph during the build (eliminate the post-build re-resolution) | **In Development** (Walk 21); design doc merged, no code PR yet | #11104 (child of #11005) — [../sidecar/java/gradle-inline-dep-capture-design.md](../sidecar/java/gradle-inline-dep-capture-design.md) |

**Standing gate (not a sub-issue):** testing — golden validation, the
`regression-gate`, and multi-distro runs (Ubuntu/RHEL/Alpine) — is a
**continuous requirement applied to every item above**, not a discrete
deliverable. No A-row is "done" until it passes these gates.

**A9 exclusion:** A9 is **backlog and parentless** (GitHub issue #11066,
Proposed) and is **not** part of the Main A completion gate. It is very
likely not required for the initial pilot: the universal artifact-based
capture path (`.class` + classpath JAR GitOID via treedb) already covers
Ant and `make`/`javac` without a declared-graph adapter, and the Ivy/Bazel
declared-graph adapters are post-pilot accuracy enrichments. The parked
work is `tedg-dev/omnibor-analysis#201` (Ivy parser, `backlog` label) and
`#202` (tables non-Maven/Gradle for the pilot, `Proposed` label). The
generic build-tool detection + shared treedb helper (#199/#200) is **pilot
foundation** tracked in #11069 (AF), not under A9. **Java delivery
completion does not depend on A9.**

### Main B — C/C++ Sidecar Interception & Phase Isolation

The **Main A → B gate is lifted** (2026-07-24 — Java functionally complete;
A8/#11055 and A12/#11104 in final review), so **Main B may proceed**. Epic:
gambit **#11008**; the four B1–B4 stories (#11009–#11012) plus the epic are
**Ready** in gambit. The four rows below are the **higher-level user
stories**
(cross-language framing in
[sidecar-phase-isolation-subissues.md](sidecar-phase-isolation-subissues.md));
each is decomposed into concrete **work-item sub-issues** (`B1.1`, `B2.1`, …)
in [c-cpp/interception-phase-isolation-subissues.md](c-cpp/interception-phase-isolation-subissues.md),
grounded in the reconciled design `../sidecar/c-cpp/sidecar-design.md`. The
gambit work-item sub-issues are **drafts** — created under their parent story
only when Main B work begins.

| Sub | Title (higher-level user story) | Work items | Lang | Status | Maps to |
|-----|-------|------|------|--------|---------|
| B1 | Agree how we observe C/C++ builds without changing them | B1.1–B1.3 (#11176–#11178) | C/C++ | Ready (B1.1 #11176 In Development) | SI-1 / #11009 |
| B2 | Auto-capture C/C++ components during a normal build (`LD_PRELOAD` primary) | B2.1–B2.5 | C/C++ | Ready | SI-2 / #11010 |
| B3 | Extend capture to self-contained (static) builds (eBPF/audit node observers) | B3.1–B3.3 | C/C++, Go | Ready | SI-3 / #11011 |
| B4 | C/C++ realization — SBOMs from captured data, no workspace | B4.1–B4.5 | C/C++ | Ready | SI-4 (C/C++) / #11012 |

### Main C — Shared Delivery & Remaining Languages

After Java (Main A); coordinated with / after C/C++ (Main B). Detail:
[sidecar-phase-isolation-subissues.md](sidecar-phase-isolation-subissues.md).

| Sub | Title | Lang | Status | Maps to |
|-----|-------|------|--------|---------|
| C1 | Shared Corona intake + auth model (build once, reuse existing patterns) | all | Out of charter — Corona owns (#11013 closed, not planned) | SI-5 (shared) |
| C2 | Deliver build evidence for C/C++, Rust, Go | C/C++, Rust, Go | Out of charter — Corona owns (#11013 closed, not planned) | SI-5 (non-Java) |
| C3 | SI-4 realizations for Rust and Go | Rust, Go | Planned | SI-4 (Rust/Go) |

## Adding new work

1. Pick the right **Main** (or add a new Main letter for a new master issue).
2. Add a **Sub** row with the next number; fill Title, Lang, Status, Maps to.
3. Put the detail in the matching per-language folder and link it here.
4. If the work supersedes an existing row, update that row to point here —
   do **not** duplicate the description.
5. Respect **Main** priority order. The **Main A → B gate is lifted**
   (2026-07-24 — Java functionally complete); **Main C** still follows Main B.
