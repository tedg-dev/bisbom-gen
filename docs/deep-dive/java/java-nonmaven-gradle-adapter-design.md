# Engineering Design — Non-Maven/Gradle Java Dependency Adapters

| | |
|---|---|
| **Sub-issue** | A9 — Support non-Maven/Gradle Java builds (`../../planning/java/java-nonmaven-gradle-build-tools-subissue.md`) |
| **Audience** | Cascade + reviewers implementing the Ivy/Bazel adapters |
| **Author** | Ted G. |
| **Drafted** | 2026-06-29 (Cascade) |
| **Status** | Design — no code yet |
| **Scope** | Phase 1 dependency capture + Phase 2 consumption for Ant/Ivy, Bazel, and `make`/`javac` Java builds |

---

## 1. Goal

Extend Java dependency capture beyond Maven/Gradle **without inventing a
parallel pipeline**. New build tools plug into the existing strategy pattern
and produce the **same capture contract** that Phase 2 already consumes.

---

## 2. Architecture recap (what already exists)

Java sidecar capture runs through `InterceptionStrategy.generate_adg()`
(`app/pipeline/interception.py`). Both `MavenDepTreeStrategy` and
`GradleDepTreeStrategy` do exactly two things:

1. **Universal treedb step (build-tool-agnostic).** They run
   `bomsh_create_bom_java.py -r <repo_dir> -j <treedb_file>`, which scans the
   built workspace and maps JAR -> `.class` -> source using the `SourceFile`
   bytecode attribute plus path similarity. **This step does not know or care
   which build tool produced the workspace.**
2. **Per-ecosystem dependency capture (enrichment).** They run
   `mvn dependency:tree` / `gradlew dependencies`, parse it, and write a
   capture file (`maven_deps.json` / `gradle_deps.json`).

Strategy selection happens in `_select_java_strategy()`
(`app/pipeline/lang_runners.py`): today it checks `is_gradle_project()` and
otherwise defaults to Maven.

Phase 2 (`generate_java_adg_spdx()` in `lang_runners.py`) reads the capture
via `app/spdx/dep_capture_reader.py` (`load_capture()` -> `resolve_module()`
-> `get_module_deps()`) and hands the dependency list to `JavaSpdxGenerator`
for the per-JAR `_build` SBOM. The treedb drives the `_analyzed` SBOM.

**Key consequence:** the universal layer (step 1) already works for *any*
Java build. Adapters only need to supply step 2 (the declared graph) in the
existing contract — or, where there is no declared graph, fall back to the
artifact-only path.

### 2.1 Investigation findings (grounded in the code)

These were verified by reading the code, not assumed:

- **The treedb step is build-tool-agnostic.** `bomsh_create_bom_java.py`
  maps JAR -> `.class` -> source using the `.class` `SourceFile` bytecode
  attribute, with strace/filename-heuristic fallback
  (`docker/patches/README-bomsh_java_sourcefile.md`). It reads the *built
  workspace* and never inspects build files, so it is independent of
  Maven/Gradle/Ant/Bazel/`make`.
- **The treedb scope is output-JAR -> source only.** `AdgParser`
  (`app/spdx/parser.py`) shows treedb entries are `{sha1: {file_path,
  hash_tree, ...}}`, tracing output JAR -> compiled class -> source. The
  treedb is the basis for the `_analyzed` SBOM.
- **The treedb does NOT contain the consumed dependency (classpath) JARs.**
  The Maven/Gradle `_build` dependency graph comes from the *separate*
  dep:tree capture (`maven_deps.json` / `gradle_deps.json`), not the treedb.
- **Consumed classpath JARs are observable only via strace** in standalone
  mode (`AdgParser.parse_strace_openat_log()` records every opened file).
  Sidecar mode has no equivalent capture.

These findings drive §8 (artifact-only path) and §11.

---

## 3. The capture contract (what adapters must produce)

Every adapter writes a JSON capture file with this shape (matching
`dep_capture_reader.load_capture()` expectations):

```json
{
  "tool": "ivy",
  "modules": [
    {
      "key": "org.apache.ant:ant-ivy",
      "groupId": "org.apache.ant",
      "artifactId": "ant-ivy",
      "version": "2.5.2",
      "packaging": "jar",
      "deps": [ { "...dep dict..." } ]
    }
  ]
}
```

Each entry in `deps` uses the canonical dep-dict shape produced by
`app/spdx/maven_parser.parse_dep_tree` and consumed by `JavaSpdxGenerator`:

| Field | Type | Meaning |
|---|---|---|
| `groupId` | str | Group / organization |
| `artifactId` | str | Artifact / module name |
| `version` | str | Resolved version |
| `scope` | str | `compile` / `runtime` / `provided` / `system` (test excluded) |
| `direct` | bool | Direct vs transitive dependency |
| `optional` | bool | Optional flag |
| `parent` | str | Parent coordinate (`""` if direct) |
| `depth` | int | Tree depth (0 = direct) |

Adapters MUST emit production scopes only (drop `test`), consistent with
`maven_dep_tree_parser._PRODUCTION_SCOPES`.

---

## 4. Integration points (exact changes)

| Layer | File / symbol | Change |
|---|---|---|
| Detection | `lang_runners._select_java_strategy` | Add Ivy / Bazel / `make` branches before the Maven default; add a `_detect_java_build_tool()` helper |
| Strategy | `app/pipeline/interception.py` | New `IvyDepCaptureStrategy`, `BazelDepCaptureStrategy`, `ArtifactOnlyStrategy` (treedb-only) |
| Parser | `app/pipeline/ivy_report_parser.py` (new) | Parse Ivy resolution report XML -> capture dict |
| Parser | `app/pipeline/bazel_lockfile_parser.py` (new) | Parse `maven_install.json` -> capture dict |
| Phase 2 | `app/spdx/dep_capture_reader.py` | Add `ivy_deps.json` / `bazel_deps.json` to `_CAPTURE_FILES`; add `_resolve_ivy()` / `_resolve_bazel()` dispatch in `resolve_module()` |

All new strategies reuse the **identical treedb step** from the Maven/Gradle
strategies (extract it into a shared `_generate_java_treedb()` helper to
avoid copy-paste — DRY).

---

## 5. Detection design

Add `_detect_java_build_tool(repo_dir, repo_cfg)` returning one of
`gradle` / `maven` / `ivy` / `bazel` / `make`. Precedence and signals:

| Tool | Primary signal | Notes |
|---|---|---|
| `gradle` | `build.gradle` / `build.gradle.kts` (existing `is_gradle_project`) | unchanged, highest precedence |
| `bazel` | `WORKSPACE` / `WORKSPACE.bazel` / `MODULE.bazel` + `BUILD`/`BUILD.bazel` | check for `maven_install.json` for enrichment |
| `ivy` | `ivy.xml` (usually alongside `build.xml`) | Ant + Ivy |
| `maven` | `pom.xml` | existing default |
| `make` | `Makefile`/`makefile` with no other Java build file | artifact-only |

A `build_system` field in `config.yaml` overrides detection (config-driven,
never repo-name-keyed). Detection is a pure function over the repo file list,
unit-testable without a real build.

---

## 6. Ivy adapter

**Input (declared graph):** the Ivy *resolution report* XML. Ant builds that
use Ivy emit per-configuration reports (e.g.
`<module>-<conf>.xml`) under the Ivy resolution-report directory
(`ivy:report` task output, or the cache report). The report lists resolved
modules with `organisation`, `name`, `revision`, and the `conf` they belong
to.

**Mapping to the dep dict:**

| Ivy report field | Dep-dict field |
|---|---|
| `organisation` | `groupId` |
| `name` | `artifactId` |
| `revision` | `version` |
| `conf` (configuration) | `scope` via a config map |
| caller depth / `caller` | `direct` / `depth` / `parent` |

**Configuration -> scope map** (Ivy configs are project-defined, so use a
conservative default map, config-overridable):

| Ivy conf | scope |
|---|---|
| `compile`, `default`, `master` | `compile` |
| `runtime` | `runtime` |
| `provided` | `provided` |
| `test` | dropped (test excluded) |

**Module shape:** Ant/Ivy projects are typically single-artifact, so the
capture has one module keyed by the project's `org:name`. If the report
exposes no module coordinate, key by the repo name and leave `groupId` empty.

**Strategy:** `IvyDepCaptureStrategy.generate_adg()` = shared treedb step +
locate the resolution report (configurable path) + `ivy_report_parser` ->
write `ivy_deps.json`.

---

## 7. Bazel adapter

**Input (declared graph):** `rules_jvm_external`'s pinned lockfile
`maven_install.json`. It enumerates resolved Maven coordinates and the
dependency edges between them.

**Mapping:** each lockfile artifact coordinate `group:artifact:version` maps
directly to `groupId` / `artifactId` / `version`; `scope` is `compile`
(lockfiles do not carry test scope); `direct` vs transitive is derived from
the lockfile's `dependencies` adjacency (roots = direct), giving `depth` and
`parent`.

**Module shape:** Bazel does not have Maven-style reactor modules. Use a
single synthetic module keyed by the Bazel target (or repo name). Phase 2
JAR -> module resolution falls through to the single-module case in
`dep_capture_reader` (already handled: "if exactly one module, use it").

**No lockfile present:** if `maven_install.json` is absent (unpinned
`maven_install`), there is no declared graph — fall back to the artifact-only
path (Section 8) and log a clear warning. We require pinned lockfiles for
enrichment (consistent with the project's pinning policy).

**Strategy:** `BazelDepCaptureStrategy.generate_adg()` = shared treedb step +
`bazel_lockfile_parser` on `maven_install.json` -> write `bazel_deps.json`.

---

## 8. Ant-only and `make`/`javac` — artifact-only path

These builds have **no declared dependency graph**. The design does not fake
one. Instead:

- **`_analyzed` SBOM** — produced as usual from the treedb (source files
  compiled into each JAR). Fully accurate, no change needed. **Grounded:**
  `bomsh_create_bom_java.py` derives JAR -> class -> source from the `.class`
  `SourceFile` bytecode attribute (with strace/heuristic fallback) — it reads
  the built workspace and has no build-tool knowledge, so this works
  unchanged for Ant/`make` (see §2.1).
- **`_build` SBOM** — there is no resolved-coordinate graph, so dependencies
  are represented as the **classpath JARs the build consumed**, identified by
  GitOID (and best-effort coordinates parsed from the JAR filename).

**Grounded constraint (from §2.1): the treedb does NOT record consumed
classpath JARs** — it records output-JAR -> source provenance only. The
consumed JARs are therefore sourced differently per mode:

| Mode | Consumed-classpath source | Feasible today? |
|---|---|---|
| **Standalone** (strace) | `AdgParser.parse_strace_openat_log()` already records every opened file; filter `.jar` opens, excluding output JARs and JDK/runtime jars | Yes — generic, exists |
| **Sidecar** (no strace) | No capture exists; needs an explicit, standard classpath-capture step | No — design gap |

So the artifact-only `_build` path is **straightforward in standalone mode**
but a **genuine gap in sidecar mode** for Ant-only/`make`. Ivy and Bazel do
not have this gap because they ship a declared graph (Ivy report,
`maven_install.json`). Recommended scoping: deliver Ivy + Bazel first; treat
the sidecar artifact-only `_build` path for Ant-only/`make` as a separate,
explicitly-scoped problem (candidate standard mechanisms: a `javac` classpath
manifest emitted by the build, or parsing the resolved classpath the build
used — to be designed, not guessed).

`ArtifactOnlyStrategy.generate_adg()` runs only the shared treedb step and
writes **no** `*_deps.json`. In standalone mode an artifact-only `_build`
mode in `generate_java_adg_spdx()` lists the strace-observed classpath JARs
as GitOID-identified components; in sidecar mode it emits the `_analyzed`
SBOM and a clearly-logged, dependency-less `_build` until the capture
mechanism above is designed.

---

## 9. Phase 2 reader changes

`dep_capture_reader.py`:

```python
_CAPTURE_FILES = {
    "maven_deps.json": "target",
    "gradle_deps.json": "build",
    "ivy_deps.json": "build",      # Ant default output dir
    "bazel_deps.json": "bazel-bin",
}
```

`resolve_module()` dispatches on `capture["tool"]`: `ivy` and `bazel` both use
single-module/`artifactId`-match resolution (reuse `_resolve_maven`-style
logic; Bazel almost always single-module). No change to `get_module_deps()`
or `JavaSpdxGenerator` — they consume the canonical dep dict unchanged.

---

## 10. Testing plan

- **Unit (no network, no Docker):**
  - `ivy_report_parser`: fixture Ivy report XML -> expected capture dict,
    including conf->scope mapping and test-scope exclusion.
  - `bazel_lockfile_parser`: fixture `maven_install.json` -> expected capture
    dict, including direct/transitive depth derivation.
  - `_detect_java_build_tool`: file-list fixtures for each tool + config
    override.
  - `dep_capture_reader`: `ivy_deps.json` / `bazel_deps.json` resolution.
- **Integration (EC2, golden-gated):** the verifier repos from the sub-issue
  (`apache/ant-ivy`, `apache/ant`, `bazelbuild/examples` java-maven, the
  `make` test app). SBOMs reviewed against USER-approved golden baselines —
  never auto-generated.
- Coverage thresholds (>=97% overall, >=95% per file) apply to new modules.

---

## 11. Findings (investigated) and remaining open questions

**Resolved by investigation (no longer assumptions):**

- **Treedb `_analyzed` layer is build-tool-agnostic — confirmed.**
  `bomsh_create_bom_java.py` maps JAR -> class -> source via the `.class`
  `SourceFile` attribute (strace/heuristic fallback), reading the built
  workspace with no build-tool knowledge
  (`docker/patches/README-bomsh_java_sourcefile.md`,
  `AdgParser.get_jar_source_files`). Ant/Bazel/`make` `_analyzed` SBOMs are
  feasible via the existing treedb step.
- **Treedb does NOT record consumed dependency JARs — confirmed.** It records
  output-JAR -> class -> source only; the Maven/Gradle `_build` graph comes
  from the separate dep:tree capture, not the treedb (`AdgParser`,
  `dep_capture_reader`). Consumed JARs are observable via
  `parse_strace_openat_log()` in **standalone mode only** (see §8 table).

**Remaining genuine open questions:**

- **Sidecar artifact-only `_build` capture** — Ant-only/`make` in sidecar
  mode has no consumed-classpath source; needs a standard mechanism (§8). To
  be designed before that path is implemented — not guessed.
- **Ivy report location** — varies by project; must be config-overridable and
  may require running the `ivy:report` task.
- **Bazel toolchain weight** — adding Bazel to the Docker image is heavy;
  gated on USER confirmation (see sub-issue). Ivy can land first.
- **sbt** remains out of scope (Scala-first).

---

## 12. Incremental delivery order

1. Extract shared `_generate_java_treedb()` helper (pure refactor, golden-clean).
2. `_detect_java_build_tool()` + config override + unit tests.
3. Ivy: `ivy_report_parser` + `IvyDepCaptureStrategy` + reader support + tests.
4. `make`/Ant-only: `ArtifactOnlyStrategy` + artifact-only `_build` mode + tests.
5. Bazel: `bazel_lockfile_parser` + `BazelDepCaptureStrategy` + reader support
   + tests (after the Bazel toolchain decision).
6. EC2 golden validation per verifier repo — present diffs, await USER review.
