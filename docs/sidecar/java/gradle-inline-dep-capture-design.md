# Gradle In-Build Dependency Capture — Design

| | |
|---|---|
| **Status** | Design — docs only, no code until approach is approved |
| **Date** | 2026-07-16 |
| **Issue** | `CiscoSecurityServices/gambit#11104` (child of #11005) |
| **Applies to** | Java sidecar mode, Gradle multi-project builds |
| **Sibling issues** | #11006 (fewest invocations), #11007 (overlap steps) |
| **Follows** | PR `tedg-dev/omnibor-analysis#213` (shim performance fix) |
| **Hard constraints** | Sidecar-only; native build command + `build.gradle`/`settings.gradle` UNCHANGED; env / init-script injection only; golden-clean output |

---

## 1. Problem

After the inline-hashing shim performance fix (PR #213), the Java **build
command** slowdown is down to roughly +2-4%. The dominant residual Phase 1
cost is now the **post-build Gradle dependency capture**, measured on EC2
(sidecar, warm caches):

| Repo | Build system | Normal build | Post-build dep capture | Total Phase 1 increase |
|---|---|---|---|---|
| spring-boot | Gradle | 21.7s | ~25s | +122% |
| bc-java | Gradle | 135.3s | ~10s | +12% |
| dependency-check | Maven | 22.2s | ~3.8s | +25% |
| logging-log4j2 | Maven | 94.8s | ~3.5s | +8% |

Maven (`mvn dependency:tree`) is cheap and **not** the target. Gradle is the
offender, and on a large multi-module project it can more than double the
build-stage wall time — the enterprise adoption blocker.

---

## 2. Current implementation

`app/pipeline/gradle_dep_tree_parser.py:run_gradle_all_dep_trees` runs a
**second** Gradle process after the build:

```text
gradlew omniborDeps --init-script <tmp> --offline --continue
```

The init script (`_OMNIBOR_INIT_SCRIPT`) registers a `DependencyReportTask`
named `omniborDeps` on every project that has a `runtimeClasspath`
configuration, so one invocation reports every module. The rendered text is
split per project (`_split_dep_report_sections`) and parsed
(`app.spdx.gradle_parser.parse_gradle_dep_tree`) into the `deps` structure
that `gradle_deps.json` stores and Phase 2 consumes.

### 2.1 Why it is slow

The inline-hashing build runs with the Gradle daemon disabled
(`GRADLE_OPTS=-Dorg.gradle.daemon=false`) so the `LD_PRELOAD` shim interposes
every compiling JVM. Consequently there is **no warm daemon** for the
post-build query to reuse, so the second `gradlew omniborDeps`:

1. starts a cold JVM,
2. re-initializes and **re-configures** every subproject (~186 for
   spring-boot), and
3. **re-resolves** every `runtimeClasspath` configuration —

all of which the build itself already did once. This duplicated
configuration + resolution is the ~25s.

---

## 3. Constraints (sidecar)

- **C2/C3**: the native build command line, `build.gradle(.kts)`,
  `settings.gradle(.kts)` are untouched. Only environment and
  auto-applied init scripts may be added (the same model as the
  `LD_PRELOAD` shim).
- **Golden-clean**: the captured dependency set must be byte-identical in
  effect to today's `gradle_deps.json` so downstream SPDX and the golden
  baselines are unchanged.
- **Generic**: no per-repo logic; must work for any Gradle project.

---

## 4. Proposed design

Capture the dependency graph **inside the build invocation** so no second
Gradle process runs at all.

### 4.1 Injection: auto-applied init script

Place an init script in `"$GRADLE_USER_HOME"/init.d/omnibor-capture.gradle`
before the build. Gradle automatically applies every script in `init.d/`
to **every** invocation — including the untouched build command — with no
command-line or build-file change (satisfies C2/C3, same posture as
`LD_PRELOAD`). The pipeline writes this file in `instrument_command()` (or a
prepare step) and sets an env var naming the capture output, e.g.
`OMNIBOR_GRADLE_CAPTURE`.

### 4.2 Capture point: end of the build, in-process

The init script hooks build completion and, for each project that has a
`runtimeClasspath` configuration, obtains its resolved dependency graph and
writes it to the capture file. Because this runs in the **build's own
process** after configuration and resolution have already happened, the
marginal cost is near zero (the resolution result is cached in-memory for
the configurations the build resolved).

Gradle API note: `Gradle.buildFinished(Closure)` is deprecated on Gradle 8.x
(spring-boot 3.4.4, bc-java). The capture hook must use a supported
mechanism — a `BuildService` released via `FlowAction`
(`@BuildTerminationAction`-style flow), or a `DependencyReportTask`
finalizer wired via the init script into the existing task graph. The
chosen mechanism must not fail the build if capture fails (best-effort;
fall back to §6).

### 4.3 Capture content — the key decision

The capture must yield the same `deps` records
(`groupId`, `artifactId`, `version`, `scope`, `direct`, `optional`,
`parent`, `depth`) that `parse_gradle_dep_tree` produces today, including
its handling of version conflicts (`declared -> resolved`) and repeated
subtrees (`(*)`).

Two options:

**Option A — render the same report text to a file.**
Reuse `DependencyReportTask`/`AsciiDependencyReportRenderer` but direct its
output to the capture file at build completion. Downstream keeps the
existing, golden-proven text parser unchanged. Lowest golden risk; depends
on Gradle-internal renderer wiring being stable across 8.x.

**Option B — walk `ResolutionResult` and emit JSON.**
In the hook, traverse each configuration's `incoming.resolutionResult` and
emit JSON already in the `deps` shape. Cleaner and version-stable, but must
**exactly** reproduce the text parser's semantics (conflict resolution,
`(*)` dedup, depth, direct vs transitive, scope) or the golden files drift.

**Recommendation:** prototype **Option A** first (reuses the proven parser →
smallest golden-clean surface). If the internal renderer proves unstable
across Gradle versions, fall back to **Option B** gated by a diff of the
emitted `deps` against the current parser output on spring-boot and bc-java.

### 4.4 Consumption

`get_all_gradle_deps(repo_dir)` reads `"$OMNIBOR_GRADLE_CAPTURE"` when
present and returns the same module list it returns today. The separate
`run_gradle_all_dep_trees` invocation is skipped entirely when the capture
file exists.

---

## 5. Interaction with inline hashing

Orthogonal to the `LD_PRELOAD` shim: the build invocation already carries
`GRADLE_OPTS=-Dorg.gradle.daemon=false` and `LD_PRELOAD`; adding an
`init.d` capture script changes neither. The daemon-vs-query tension that
makes the current post-build query cold **disappears**, because there is no
second invocation.

---

## 6. Fallback (fail-loud, not silent)

If the capture file is missing or unparseable (older Gradle, unusual layout),
`get_all_gradle_deps` logs a clear warning and falls back to the existing
`run_gradle_all_dep_trees` invocation (then the per-subproject path). The
result is correct but slower — never silently wrong.

---

## 7. Validation gates (EC2, real build host)

1. `deps` captured in-build are identical to the current
   `run_gradle_all_dep_trees` output for spring-boot and bc-java
   (per-module diff, must be empty).
2. Full pipeline SPDX is **golden-clean** on spring-boot and bc-java.
3. Maven repos are byte-for-byte unchanged (no Gradle path touched).
4. Total Phase 1 overhead (build + metadata) on spring-boot is **well under
   100%** (target: dependency capture drops from ~25s to ~1-2s).
5. The build command, `build.gradle`, and `settings.gradle` are unchanged;
   only `init.d` + env are added.

---

## 8. Out of scope

- Maven dependency capture (already cheap).
- Phase 2 reuse of captured deps (tracked under #11002).
- Overlapping independent post-build steps (#11007).
