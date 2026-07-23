# Synthetic Gradle capture fixtures

Minimal, hermetic Gradle projects that isolate **one** build-system
variable each, used to validate the #11104 in-build dependency-capture
init script across the code paths our capture is actually sensitive to
(execution model + project topology). Cosmetic variety (DSL, version
catalog, module count) is covered by the real repos in `app/config.yaml`
(`spring-boot`, `bc-java`, `caffeine`) and is deliberately **not**
re-tested here.

## Why these exist

Our capture registers a `DependencyReportTask` (`omniborDeps`) on every
`allprojects` project that exposes `runtimeClasspath`, appends it to the
primary invocation via `startParameter`, and writes each project's report
to its own file. The behaviours that can change capture correctness are
enumerated below; each fixture forces exactly one of them.

## Hermetic strategy

- **No network.** Dependencies resolve from the committed POM-only Maven
  repo at `local-repo/`. The dependency **report** resolves the graph from
  module metadata (POMs) only — it does not download artifact JARs — so
  POM-only entries are sufficient and fully deterministic.
- **No compilation.** The capture is exercised with a light primary task
  (`help`) plus the injected `omniborDeps`, so no `src/` or JDK toolchain
  is required.
- **Pinned Gradle.** All fixtures except the version-drift case run on the
  same pinned Gradle as `spring-boot` (8.13). Gradle **9.x** API drift is
  covered by a real repo (`opentelemetry-java`, `gradle-9.6.1`), not a
  fixture, because a real build is the honest test of upstream behaviour.

## Local Maven repo (`local-repo/`)

| Module | Version | Depends on | Purpose |
|--------|---------|-----------|---------|
| `com.example:libcore` | `1.0` | — | Transitive leaf |
| `com.example:libutil` | `1.0` | `com.example:libcore:1.0` | Direct dep with one transitive edge |

## Fixture matrix

| Fixture | Isolated variable | Expected capture outcome |
|---------|-------------------|--------------------------|
| `single-module/` | Root-only build (no subprojects) | One section `:` with `libutil -> libcore` |
| `configure-on-demand/` | `org.gradle.configureondemand=true` | Sections for **both** `:app` and `:lib` (on-demand must not drop `:lib`) |
| `configuration-cache/` | `org.gradle.configuration-cache=true` | Capture still runs; `startParameter` mutation + task registration survive the configuration cache |
| `composite-substitution/` | `includeBuild` providing a **production** dependency via `dependencySubstitution` | **Known gap:** the included build's project is not in the root's `allprojects`, so `libutil` is captured as a skipped `project ` line and currently **missed**. Fixture is the spec for the future fix (walk included builds). |
| `java-platform/` | A `java-platform` (BOM) project with no `runtimeClasspath` | `:platform` produces **no** section (skipped by the `findByName('runtimeClasspath')` guard); `:app` is captured |

## Test runner

The Gradle-version compatibility matrix runner is
[`tests/test_gradle_capture_matrix.py`](../../test_gradle_capture_matrix.py)
(marker `gradle_matrix`, registered in `tests/conftest.py`). For each
Gradle version in the matrix (7.6.4 / 8.13 / 9.6.1) and each fixture it:

1. Copies the whole fixtures tree to a temp dir (so each fixture's
   `${rootDir}/../local-repo` file repository resolves).
2. Pins a wrapper to the matrix version (`gradle wrapper
   --gradle-version <v>`).
3. Runs the **real** capture code
   (`app.pipeline.gradle_dep_tree_parser.get_all_gradle_deps`, which
   injects the production init script) and asserts the per-project
   sections match the **Expected capture outcome** column above.

It is opt-in (it downloads Gradle distributions and builds), so it never
runs in the default unit gate. Enable with::

    OMNIBOR_GRADLE_MATRIX=1 pytest tests/test_gradle_capture_matrix.py

A bootstrap `gradle` must be on `PATH` (used only to generate the pinned
wrappers) and the JDK must be compatible with every matrix version
(JDK 17 covers 7.6.4 through 9.6.1).
