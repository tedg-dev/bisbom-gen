# Phase 2 Generates Java SBOMs From Phase 1 Metadata — Design

| | |
|---|---|
| **Date** | 2026-06-24 |
| **Authors** | Ted G. (architect), Cascade AI |
| **Status** | Draft design — docs only, awaiting approval before any code |
| **Applies to** | Java (Maven and Gradle) sidecar mode |
| **Objective** | Phase 2 produces fully accurate Java SBOMs from Phase 1 metadata alone, with no source-tree access; Phase 1 stays fast |
| **Sub-issue** | `docs/planning/java-phase2-consume-dep-capture-subissue.md` |
| **Related** | `phase-isolation-build-time-analysis.md`, `dependency-check-module-dependency-structure.md`, `phase2-binary-artifact-dependencies.md` |

---

## Table of Contents

1. [Objective and Hard Constraints](#1-objective-and-hard-constraints)
2. [Current State (Verified Facts)](#2-current-state-verified-facts)
3. [What Phase 1 Must Capture](#3-what-phase-1-must-capture)
4. [Proposed Design](#4-proposed-design)
5. [Capture Format (Per-Module)](#5-capture-format-per-module)
6. [When Metadata Is Missing](#6-when-metadata-is-missing)
7. [Testing Plan](#7-testing-plan)
8. [Open Decisions for the User](#8-open-decisions-for-the-user)

---

<a id="1-objective-and-hard-constraints"></a>

## 1. Objective and Hard Constraints

**Objective:** Phase 2 produces fully accurate `_build` SBOMs for every
Java artifact using **only** the metadata Phase 1 collected — with **no
access to the source tree** — while Phase 1 stays fast.

**Hard constraints:**

- **Phase 2 must never read the source tree.** In the enterprise topology,
  Phase 1 and Phase 2 run on different machines and the workspace is gone
  when Phase 2 runs. Phase 2 therefore **cannot** run `mvn dependency:tree`
  / `gradlew dependencies` (or any source-reading command).
- **Phase 1 must be thorough *and* fast.** It must capture everything
  Phase 2 could need, but without adding resolution work. The enhancement
  here is **parser-only**: it reuses the single `dependency:tree` output
  Phase 1 already produces.
- **Duplication in Phase 2 is acceptable.** Re-doing graph-walking work that
  Phase 1 also did is fine; the only prohibition is touching the source
  tree.
- **No golden updates by Cascade.** Diffs are reported for review.
- **Accuracy baseline:** the standalone (ptrace) solution. The goal is to
  match its accuracy from metadata alone.

---

<a id="2-current-state-verified-facts"></a>

## 2. Current State (Verified Facts)

**Phase 1 capture (`maven_deps.json`)** is produced by `parse_dot_output()`
in `app/pipeline/maven_dep_tree_parser.py`. Properties:

- Covers the **whole reactor** (all `digraph` blocks in
  `mvn dependency:tree -DoutputType=dot`).
- **Globally de-duplicated** by `(groupId, artifactId)` across all modules.
- Fields per entry: `groupId`, `artifactId`, `version`, `scope`,
  `packaging`, `direct`, `parent`, `is_test`, `module`.
- `module` is set to the owning module's **coordinate** for **direct**
  deps, and `None` for transitives.
- `parent` is the parent **artifactId** for transitives, `None` for direct.
- Does **not** carry the `optional` flag.

**Phase 1 capture (`gradle_deps.json`)** is produced by
`get_all_gradle_deps()` in `app/pipeline/gradle_dep_tree_parser.py`.
Properties: globally de-duplicated by `(groupId, artifactId)`; `scope`
forced to `compile`; `module` set per subproject for subproject deps,
`None` for root.

**Phase 2 consumption today** (`_generate_java_spdx` in
`app/pipeline/lang_runners.py`):

- Iterates each output JAR, derives the JAR's module directory
  (`pom_dir`) by walking up to a build file.
- Calls `JavaSpdxGenerator.generate(pom_dir=...)`, which runs the resolver
  **live, per module** via `app/spdx/maven_parser.py:get_maven_deps`
  (Maven, text output, `parse_dep_tree`) or
  `app/spdx/gradle_parser.py:get_gradle_deps` (Gradle).
- The live Maven text parser **keeps `optional`** and does **not**
  de-duplicate within a module.

**Scope of impact:** Only the `_build` SBOM uses the dependency graph.
The `_analyzed` SBOM strips build-tool and dependency packages, so it is
**unaffected** by this change.

**The core defect:** today's Phase 2 dependency step reads the source tree
(`pom_dir`). Even setting aside the capture's lossiness, this alone makes
Phase 2 non-runnable in the enterprise split. Fixing it requires Phase 2 to
obtain its dependency data from Phase 1 metadata instead.

---

<a id="3-what-phase-1-must-capture"></a>

## 3. What Phase 1 Must Capture

Phase 2 emits **one `_build` SBOM per module**, each listing that module's
**direct** dependencies and their **transitive** closure, hierarchically
(not flattened). The `dependency-check` deep-dive documents the target
shape: the `cli` module lists its 10 direct deps and does **not** absorb
`core`'s transitives (`dependency-check-module-dependency-structure.md`).

To produce this from metadata alone, Phase 1 must capture **per-module**
dependency subtrees — not one flattened reactor list.

**Why the current capture is insufficient (proof):** `parse_dot_output()`
de-duplicates globally by `(groupId, artifactId)` across all modules:

```python
dep_key = (child["groupId"], child["artifactId"])
if dep_key in seen:        # single `seen` set spans ALL digraph blocks
    continue
seen.add(dep_key)
```

So a third-party component that two modules both depend on is stored
**once**, attached to whichever module's edge was parsed first.
Reconstructing per-module from that file would place the component in only
**one** module's SBOM — a loss the live per-module path does not have. The
capture also drops the `optional` flag entirely.

**The information is available from the same single invocation — we were
just asking for the wrong output format.** The `optional` flag is **not
present in the DOT format at all** (DOT edges are labeled with scope only:
`groupId:artifactId:type:version:scope`). Per the Apache Maven Dependency
Plugin *Tree Output Formats* docs, only the **JSON** and **text** formats
carry `optional`. JSON requires `maven-dependency-plugin >= 3.7.0`, which
is **not acceptable** here: in the enterprise topology Phase 1 runs on the
customer's build machine and we do **not** control their Maven or plugin
version. The **default `text`** format, by contrast, has emitted the
`:scope` coordinate plus an ` (optional)` suffix consistently across the
entire 2.x/3.x life of the plugin — **no minimum version, nothing to pin,
nothing to download**. It also encodes a **complete subtree per module**
(reactor sections, hierarchy via indentation depth). Phase 1 already runs
`dependency:tree` once; we simply capture the **default text** output
instead of DOT and parse per module. Capturing per-module structure is
therefore **free** in build-time terms, with **zero** dependency on the
customer's toolchain version.

---

<a id="4-proposed-design"></a>

## 4. Proposed Design

### 4.1 Phase 1 — parser-only thoroughness (no added build time)

Capture the **default `text`** output of the single `dependency:tree`
invocation Phase 1 already runs (switching away from `-DoutputType=dot`,
which cannot carry `optional`), and parse it to **retain per-module
structure** instead of collapsing to a flat, globally-deduped list:

- Segment the reactor text output into per-module blocks (a module begins
  at its root coordinate line, e.g. `groupId:artifactId:jar:version`), and
  parse each block into its own complete subtree, **de-duplicating only
  within a module**, not across modules.
- Preserve the `optional` flag (the ` (optional)` suffix in text output).
- Reuse the **proven** text parser `app/spdx/maven_parser.py:parse_dep_tree`
  — the same parser that already produces today's accurate per-module
  goldens — applied per module segment, to avoid duplicating parsing logic.
- Serialize a **per-module** structure (see
  [Capture Format](#5-capture-format-per-module)).

This reuses the single `dependency:tree` invocation Phase 1 already runs —
**no new subprocess, no extra build time** — and the **default `text`**
format imposes **no version requirement** on the customer's Maven/plugin
(unlike JSON, which needs plugin `>= 3.7.0`). It is safe because nothing
currently reads the captured file.

> **Format decision (corrected from earlier draft):** an earlier version
> of this design assumed the DOT output carried `optional`. It does not —
> DOT carries scope only. The capture therefore uses the **default text**
> format, which is the most version-robust source of `optional` + per-module
> hierarchy and requires no control over the customer's build toolchain.

### 4.2 Phase 2 — generate from metadata only

Introduce a focused reader (`app/spdx/dep_capture_reader.py`) so
`JavaSpdxGenerator` stays within the file-size guideline. For each output
JAR:

1. Determine the JAR's **module key from the artifact itself** — the JAR
   path is `<module>/target/<artifactId>-<version>.jar`, so the module is
   already encoded in the JAR location and filename. This is build-output
   metadata that travels **with the artifact**; no source tree is needed.
   The JAR filename (`<artifactId>-<version>`) maps directly to the
   capture's module coordinate; the treedb `jar_map` is the backup when a
   custom `<finalName>` breaks that convention.
2. Load that module's pre-built subtree directly from the capture.
3. Filter to production scopes (`compile`, `runtime`, `provided`) exactly
   as today.

The returned list keeps the same dict shape `_get_maven_deps()` returns
today, so the downstream `_build_spdx` logic (sibling detection,
relationship emission) is **unchanged**. What is **removed** from Phase 2:
the `pom.xml`/`build.gradle` existence walk (`@lang_runners.py:447-464`) and
the live `mvn dependency:tree` / `gradlew dependencies` resolution — those
are the only source-tree-dependent steps; module identification was never
one of them.

### 4.3 Artifact naming is an industry standard (Maven + Gradle)

The JAR-to-module mapping relies on documented default conventions, not
guesswork:

| | Maven | Gradle |
|---|---|---|
| **Default JAR name** | `${project.build.finalName}` = `${artifactId}-${version}` | `archiveFileName` = `[archiveBaseName]-[archiveVersion].[ext]`; `archiveBaseName` defaults to `archivesName` = `project.name` |
| **Default output dir** | `<module>/target/` | `<subproject>/build/libs/` (`libsDirectory` = `$buildDir/libs`) |
| **Module-name source** | module dir holds `pom.xml`; `artifactId` conventionally matches the dir | `project.name` defaults to the subproject directory name |
| **Capture key** | `groupId:artifactId` (dep-graph root coordinate) | subproject path, e.g. `:core` |

Sources: Apache Maven **Properties Guide** and **POM Reference**
(`${project.build.finalName}` defaults to
`${project.artifactId}-${project.version}`); Gradle **Base Plugin** docs
(`archivesName` default = `$project.name`, `libsDirectory` = `$buildDir/libs`)
and the **`Jar` task DSL**. The only deviations are explicit overrides
(`<finalName>`, `archiveBaseName`/`archivesName`), for which the treedb
`jar_map` is the backup.

### 4.4 Scope: which build tools this covers

| Language | Build tools | This problem applies? |
|---|---|---|
| Java, Kotlin, Scala | Maven, Gradle | **Yes** — JVM dependency resolution is a separate step that today reads the source tree |
| C/C++, Go, Rust | native toolchains | **No** — Phase 1 captures file I/O **inline** during the build (strace / wrapper); there is no separate Phase 2 resolution step and no source-tree dependence |

Kotlin and Scala route through Maven/Gradle (per
`app/pipeline/language_validator.py`), so they need no separate handling.
Other JVM build tools (Ant+Ivy, Bazel, sbt, Mill) are **not supported**
today; if added, each would need its own artifact-naming convention mapped
to the capture key.

---

<a id="5-capture-format-per-module"></a>

## 5. Capture Format (Per-Module)

The captured file becomes a mapping from module key to that module's
dependency list, each entry retaining `optional`:

```json
{
  "tool": "maven",
  "modules": {
    "com.example:core": [
      {"groupId": "org.apache.commons", "artifactId": "commons-lang3",
       "version": "3.14.0", "scope": "compile", "direct": true,
       "optional": false, "parent": null},
      {"groupId": "...", "artifactId": "...", "parent": "commons-lang3"}
    ],
    "com.example:cli": [
      {"groupId": "org.apache.commons", "artifactId": "commons-lang3",
       "version": "3.14.0", "scope": "compile", "direct": true,
       "optional": false, "parent": null}
    ]
  }
}
```

`commons-lang3` appears under **both** modules — that is the whole point.
Maven module key = module coordinate (for example `groupId:artifactId`).
Gradle module key = subproject path (for example `:core`), with the root
project under a well-known key. Within a module, de-duplication is by
`(groupId, artifactId)` (Maven resolves one version per artifact per
module); **across** modules there is no de-duplication.

This format change is internal (nothing else reads the file). The
`_analyzed` SBOM is unaffected.

---

<a id="6-when-metadata-is-missing"></a>

## 6. When Metadata Is Missing

In the enterprise split, Phase 2 has no source tree, so there is **no
source-tree fallback**. If required metadata is absent, Phase 2 must **fail
loudly** with a clear error rather than silently emit an incomplete SBOM.

A **dev/test convenience** (single-machine runs where the source tree
happens to be present) may optionally fall back to live resolution, clearly
logged as a non-enterprise path. Golden files are generated from **sidecar**
mode where the capture is always present, so the convenience path never
produces goldens.

---

<a id="7-testing-plan"></a>

## 7. Testing Plan

Unit tests (no Docker, no network, temp dirs only):

- **Per-module parse (Maven):** a multi-`digraph` fixture parses into
  per-module subtrees with **no cross-module dedup**; a component shared by
  two modules appears in **both**.
- **`optional` preserved:** an optional dep retains its flag through parse
  and into the dependency list.
- **Per-module parse (Gradle):** a multi-subproject fixture parses into
  per-subproject lists.
- **Phase 2 from metadata:** the generator builds a module's `_build` deps
  from the captured file with **no resolver subprocess** invoked (a mock
  asserts no subprocess call).
- **Missing metadata fails loudly:** the enterprise path returns/raises a
  clear error; no silent empty list.
- **Shape parity:** the metadata-derived list matches the dict shape
  `_build_spdx` consumes today, so SBOM construction needs no change.

Integration validation (EC2, sidecar) before merge: run the multi-module
Java repos (for example `dependency-check`, `logging-log4j2`, `checkstyle`)
and **enumerate** every `_build` SBOM diff against the golden baseline for
user review. With faithful per-module capture, the expectation is parity
with today's per-module output; any differences are reported, never
auto-applied.

---

<a id="8-open-decisions-for-the-user"></a>

## 8. Open Decisions for the User

1. **Approved (with corrected mechanism):** retain per-module attribution
   and the `optional` flag from the single `dependency:tree` invocation,
   at zero added build time. **Corrected mechanism:** capture the
   **default `text`** output (not DOT — DOT cannot carry `optional`; JSON
   would require plugin `>= 3.7.0`, a toolchain version we do not control).
   Text is the universal default and imposes no version requirement.
2. **JAR → module-key association** (resolved): the module is encoded in the
   JAR path/filename (`<module>/target/<artifactId>-<version>.jar`), which
   is artifact metadata — no source tree needed. The treedb `jar_map` is the
   backup for custom `<finalName>`. Confirm the `<finalName>` backup
   handling is acceptable.
3. **Missing-metadata behavior:** fail loudly in the enterprise path, with
   a live fallback allowed only for co-located dev/test runs (recommended)?
4. **Sequencing:** Maven first (most multi-module goldens) then Gradle, or
   both together?

No code will be written until these are settled and you approve.
