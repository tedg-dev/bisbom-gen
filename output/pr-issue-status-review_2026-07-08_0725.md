# PR → Issue Status Review

| | |
|---|---|
| **Generated** | 2026-07-08 07:25 HST |
| **Updated** | 2026-07-08 11:41 HST — created docs tracker #11071 (In Review; #207 linked via `Part of`); pilot-foundation #11069 (In Review) owning #199/#200; #11066 tabled (#201/#202); #204→#11008 comment posted |
| **Scope** | PRs merged to `main` since 2026-06-08, plus currently-open PRs |
| **Issue source** | Corona board #255 (`CiscoSecurityServices/gambit`), read via `tedg_cisco` |
| **Purpose** | Review only — NOT to be committed (lives under gitignored `output/`) |

---

## Merged PRs since 2026-06-08 (merge-date order)

<table>
  <colgroup>
    <col style="width:8%">
    <col style="width:7%">
    <col style="width:37%">
    <col style="width:20%">
    <col style="width:13%">
    <col style="width:15%">
  </colgroup>
  <thead>
    <tr><th>Date</th><th>PR</th><th>Description</th><th>Planning label</th><th>Issue</th><th>Issue status</th></tr>
  </thead>
  <tbody>
    <tr><td>06-12</td><td>#185</td><td>Docs: C/C++ sidecar interception strategies + eBPF investigation</td><td>Main B enablement (docs)</td><td><code>#11008</code>/<code>#11009</code> (indirect)</td><td>Proposed</td></tr>
    <tr><td>06-18</td><td>#187</td><td>Optimize Phase 1 ADG step (split timing, offline mode, skip flags)</td><td>A6 / SI-R1</td><td><code>#11000</code></td><td>In Review</td></tr>
    <tr><td>06-18</td><td>#188</td><td>Docs: sidecar phase-isolation research</td><td>Planning/docs</td><td>—</td><td>n/a</td></tr>
    <tr><td>06-18</td><td>#189</td><td>Pure-Python fast-path for bomsh Java treedb (hash/IO/classreader)</td><td>A6 / SI-R1</td><td><code>#11000</code></td><td>In Review</td></tr>
    <tr><td>06-22</td><td>#190</td><td>Chore: snapshot Cascade memories + <code>.windsurf</code> manifest</td><td>Repo chore</td><td>—</td><td>n/a</td></tr>
    <tr><td>06-22</td><td>#191</td><td>fix(java-sidecar+spdx): ADG robustness, <code>sourceInfo</code>, golden comparator + baselines</td><td>A6 / SI-R1</td><td><code>#11000</code></td><td>In Review</td></tr>
    <tr><td>06-24</td><td>#192</td><td>Docs: phase-isolation user stories + C/C++ design relocation</td><td>Planning/docs</td><td>—</td><td>n/a</td></tr>
    <tr><td>06-24</td><td>#193</td><td>Docs: consolidate Phase 1 build-speed design reference</td><td><code>#11005</code> design ref</td><td><code>#11005</code></td><td>Ready</td></tr>
    <tr><td>06-29</td><td>#194</td><td>feat(java): Phase 2 generates SBOMs from Phase 1 metadata, no source tree</td><td>A1 / SI-4 (Java)</td><td><code>#11003</code></td><td>In Review</td></tr>
    <tr><td>06-29</td><td>#195</td><td>Docs: Java build-based SBOM sell doc + diagrams + planning reorg</td><td>Main A enablement (docs)</td><td><code>#11002</code> (parent)</td><td>In Development</td></tr>
    <tr><td>06-29</td><td>#196</td><td>feat(java): single-invocation Gradle dependency capture (US-2)</td><td>A4 / US-2</td><td><code>#11006</code></td><td>In Review</td></tr>
    <tr><td>06-29</td><td>#197</td><td>Docs(planning): GitHub Issues PR crosswalk + status refresh</td><td>Planning/docs</td><td>—</td><td>n/a</td></tr>
    <tr><td>06-29</td><td>#198</td><td>Docs(planning): refine Main A scope + draft A9 sub-issue</td><td>Main A scope (docs)</td><td><code>#11002</code></td><td>In Development</td></tr>
    <tr><td>06-29</td><td>#199</td><td>refactor(java): shared <code>_generate_java_treedb</code> helper</td><td>AF (pilot foundation)</td><td><code>#11069</code></td><td>In Review</td></tr>
    <tr><td>06-29</td><td>#200</td><td>feat(java): <code>_detect_java_build_tool()</code> + <code>java_build_tool</code> override</td><td>AF (pilot foundation)</td><td><code>#11069</code></td><td>In Review</td></tr>
    <tr><td>07-01</td><td>#204</td><td>Docs: consolidate C/C++ sidecar docs, reorganize by topic</td><td>Main B enablement (docs)</td><td><code>#11008</code> (indirect)</td><td>Proposed</td></tr>
    <tr><td>07-06</td><td>#205</td><td>Docs: consolidate sidecar + phase isolation under <code>docs/sidecar/</code></td><td>Planning/docs</td><td>—</td><td>n/a</td></tr>
    <tr><td>07-07</td><td>#206</td><td>Docs: Phase 1 architecture verification and corrections</td><td>Planning/docs (Main A)</td><td><code>#11002</code> (indirect)</td><td>In Development</td></tr>
  </tbody>
</table>

---

## Open PRs (not yet merged)

<table>
  <colgroup>
    <col style="width:7%">
    <col style="width:33%">
    <col style="width:12%">
    <col style="width:48%">
  </colgroup>
  <thead>
    <tr><th>PR</th><th>Description</th><th>State</th><th>Disposition</th></tr>
  </thead>
  <tbody>
    <tr><td>#201</td><td>feat(java): Ivy report parser + Phase 2 reader support (A9)</td><td>Draft</td><td><b>Parked</b> — <code>backlog</code> label; decoupled from A9 pilot. Revive with backlog issue #11066</td></tr>
    <tr><td>#202</td><td>chore(java): table non-Maven/Gradle Java for pilot (A9)</td><td>Draft</td><td><b>Parked</b> — <code>Proposed</code> label; fail-fast on ivy/ant/make/bazel. Tracked by backlog issue #11066; comment posted 2026-07-08</td></tr>
    <tr><td>#203</td><td>docs(c-cpp): fix sidecar-design.md (broken links + strategy ordering)</td><td>Open</td><td>Main B (blocked); docs-only — leave or merge later</td></tr>
    <tr><td>#207</td><td>docs(planning): mark A9 as backlog (#11066) + refresh crosswalk</td><td>Open</td><td>Docs-only; planning index + crosswalk. Awaiting review/merge</td></tr>
  </tbody>
</table>

---

## Live issue statuses (board #255, `omnibor-analysis` issues)

<table>
  <colgroup>
    <col style="width:10%">
    <col style="width:55%">
    <col style="width:18%">
    <col style="width:17%">
  </colgroup>
  <thead>
    <tr><th>Issue</th><th>Title (short)</th><th>Label</th><th>Status</th></tr>
  </thead>
  <tbody>
    <tr><td><code>#11000</code></td><td>Faster SBOM generation for Java (retro)</td><td>A6 / SI-R1</td><td>In Review</td></tr>
    <tr><td><code>#11002</code></td><td>Java Phase 2 — SBOMs from Phase 1 metadata (Main)</td><td>Main A parent</td><td>In Development</td></tr>
    <tr><td><code>#11003</code></td><td>Generate Java SBOMs from metadata — Maven &amp; Gradle</td><td>A1</td><td>In Review</td></tr>
    <tr><td><code>#11004</code></td><td>Java Phase 2 output set + hand-off manifest</td><td>A2</td><td>In Development</td></tr>
    <tr><td><code>#11005</code></td><td>Phase 1 build-speed &amp; efficiency for Java (Main)</td><td>Main</td><td>Ready</td></tr>
    <tr><td><code>#11006</code></td><td>Efficient multi-module dependency capture</td><td>A4 / US-2</td><td>In Review</td></tr>
    <tr><td><code>#11007</code></td><td>Overlap independent post-build steps</td><td>A5 / US-3</td><td>Ready</td></tr>
    <tr><td><code>#11008</code></td><td>C/C++ build-based SBOM capture &amp; delivery (Main)</td><td>Main B</td><td>Proposed</td></tr>
    <tr><td><code>#11009</code></td><td>Agree on C/C++ build observation approach</td><td>B1 / SI-1</td><td>Proposed</td></tr>
    <tr><td><code>#11010</code></td><td>Auto-capture C/C++ components</td><td>B2 / SI-2</td><td>Proposed</td></tr>
    <tr><td><code>#11011</code></td><td>Extend capture to statically linked builds</td><td>B3 / SI-3</td><td>Proposed</td></tr>
    <tr><td><code>#11012</code></td><td>SBOMs from captured data, no workspace</td><td>B4 / SI-4</td><td>Proposed</td></tr>
    <tr><td><code>#11013</code></td><td>Deliver build evidence to Corona (shared + non-Java)</td><td>C / SI-5</td><td>Proposed</td></tr>
    <tr><td><code>#11055</code></td><td>Process JAR class files fully in memory</td><td>A8 / US-4</td><td>Proposed</td></tr>
    <tr><td><code>#11066</code></td><td>Non-Maven/Gradle Java (Ant/Ivy, Bazel, make)</td><td>A9 (backlog, parentless)</td><td>Proposed</td></tr>
    <tr><td><code>#11069</code></td><td>Java Phase 1 capture foundation (build-tool detect + treedb helper)</td><td>AF / child of #11005</td><td>In Review</td></tr>
    <tr><td><code>#11071</code></td><td>Java pilot documentation (living tracker)</td><td>Docs tracker (parentless)</td><td>In Review</td></tr>
  </tbody>
</table>

---

## Observations

- `#11000` shows **In Review** although delivering PRs #187/#189/#191 merged 06-18..06-22. Only the Issues team may move it to Done.
- `#11003` (In Review) and `#11006` (In Review) match merged PRs #194 and #196 — consistent.
- **Pilot foundation (#199/#200) is now issue #11069** (In Review, child of #11005 — build-tool detection + shared treedb helper). It is **not** part of the tabled A9 work.
- **A9 (non-Maven/Gradle Java) is backlog issue #11066** (Proposed, parentless, excluded from the Main A gate). Its only work is parked: #201 (Draft, `backlog`) and #202 (Draft, `Proposed`).
- Docs-only PRs (#185, #188, #190, #192, #195, #197, #204, #205, #206) have no 1:1 theme issue.
- **Docs tracker #11071** (In Review) now groups docs-only PRs (#192/#193/#195/#204/#205/#206/#207); each references it via `Part of`. Status moves with docs activity; datetimestamped log lives in the issue.

---

## Post-#197 PR → issue assignment analysis

<table>
  <colgroup>
    <col style="width:7%">
    <col style="width:28%">
    <col style="width:25%">
    <col style="width:40%">
  </colgroup>
  <thead>
    <tr><th>PR</th><th>Kind</th><th>Best-fit issue</th><th>Recommendation</th></tr>
  </thead>
  <tbody>
    <tr><td>#198</td><td>Docs (Main A scope + design)</td><td><code>#11002</code> (In Development)</td><td><b>Done</b> — comment posted on <code>#11002</code> (2026-07-08)</td></tr>
    <tr><td>#199</td><td>Code — shared treedb helper</td><td>AF → <code>#11069</code> (In Review)</td><td><b>Done</b> — foundation merged; tracked by <code>#11069</code></td></tr>
    <tr><td>#200</td><td>Code — build-tool detection</td><td>AF → <code>#11069</code> (In Review)</td><td><b>Done</b> — foundation merged; tracked by <code>#11069</code></td></tr>
    <tr><td>#204</td><td>Docs — C/C++ sidecar reorg</td><td><code>#11008</code> (Proposed, blocked)</td><td><b>Done</b> — reference comment posted on <code>#11008</code> (2026-07-08); status left Proposed</td></tr>
    <tr><td>#205</td><td>Docs — sidecar/phase-isolation consolidation</td><td>cross-cutting</td><td>No status change</td></tr>
    <tr><td>#206</td><td>Docs — Phase 1 architecture verification</td><td><code>#11005</code> (Ready)</td><td><b>Done</b> — comment posted on <code>#11005</code> (2026-07-08)</td></tr>
  </tbody>
</table>

**Resolution (2026-07-08):** the merged pilot foundation (#199/#200, with #198 scope docs) was
split out of the tabled A9 issue into its **own parent issue #11069** ("Java Phase 1 capture
foundation"), created **In Review** as a sub-issue of **#11005**. **#11066** now holds only the
tabled non-Maven/Gradle work: **#201** (Draft, `backlog`) and **#202** (Draft, `Proposed`); its
body was corrected to remove the foundation claim. The planning docs (README.md + crosswalk) were
updated on **docs PR #207**.
