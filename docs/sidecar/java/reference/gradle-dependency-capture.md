# Gradle dependency-graph capture

|  |  |
|---|---|
| **Audience** | Contributors maintaining the Java Gradle capture path |
| **Author** | Ted G. (architect), Cascade AI |
| **Date** | 2026-07-22 |
| **Status** | Current mechanism documented; `#11104` in-build evolution tracked |
| **Applies to** | Java (and other JVM) Gradle builds, sidecar + standalone |
| **Code** | `app/pipeline/gradle_dep_tree_parser.py`, `app/spdx/gradle_parser.py` |

## Why

Phase 2 needs each project's resolved runtime dependency graph. Re-resolving
the graph after the build (one `./gradlew dependencies` per subproject) is
slow and, in sidecar mode, may be impossible (the build workspace is
ephemeral). The capture path resolves the graph **once**, driven by a single
injected init script, and parses it into the same structure the Maven path
produces.

## Current mechanism

`run_gradle_all_dep_trees()` performs **one** Gradle invocation with an
injected init script (`_OMNIBOR_INIT_SCRIPT`) that registers an
`omniborDeps` `DependencyReportTask` on **every** project exposing a
`runtimeClasspath` configuration:

```groovy
allprojects { p ->
    p.afterEvaluate {
        if (p.configurations.findByName('runtimeClasspath') != null) {
            p.tasks.register('omniborDeps', DependencyReportTask) { t ->
                t.configuration = 'runtimeClasspath'
            }
        }
    }
}
```

Key properties:

- **`afterEvaluate`** — registration is deferred because the Java plugin
  creates `runtimeClasspath` during project evaluation, after the init
  script's `allprojects` closure runs.
- **`findByName('runtimeClasspath')` guard** — projects without a runtime
  classpath (e.g. a `java-platform`/BOM project) are skipped cleanly.
- **`--offline --continue`** — run after a successful build (cache is warm);
  `--continue` means one failing module does not abort the rest.
- **`-q` intentionally omitted** — on some Gradle versions the custom report
  task renders below the quiet log level.

The aggregated report is split into per-project sections by
`_split_dep_report_sections()` (`Root project` → `:`, `Project ':x'` → `:x`)
and each section is parsed by `parse_gradle_dep_tree()`. Inter-project
(`project :x`) lines are intentionally **not** emitted as external packages.

## `#11104` in-build evolution

The tracked optimization eliminates the separate capture invocation by
**appending `omniborDeps` to the primary build** via
`startParameter.taskNames` (from the init script) and having each project
write its own report to a dedicated file via `DependencyReportTask.outputFile`
(avoiding stdout interleaving under parallel/`-q` builds). This keeps the
capture inside the single build the enterprise CI/CD already runs.

The two API calls this depends on — `startParameter` mutation from an init
script and `DependencyReportTask.outputFile` — are the axes the version
matrix below exists to protect.

## API stability

`DependencyReportTask.outputFile` (via `AbstractReportTask`) has existed since
early Gradle and is present through 9.x, so it is **not** the low-end limiter.
Gradle 9.x marks `AbstractReportTask` `@Deprecated` (superseded by
`AbstractProjectBasedReportTask`), so `outputFile` is a **removal candidate in
Gradle 10+** — hence the 9.6.x coverage and a renderer-based fallback to
watch.

## Coverage — real repos

The `config.yaml` Gradle repos span the build-flavor and version axes the
capture must handle (see [`build_profile`](../../../reference/build-profile-schema.md)):

| Repo | DSL | Structure | Gradle | Notable |
|------|-----|-----------|--------|---------|
| `spring-boot` | groovy | multi-module | 8.13 | dependency-management BOM |
| `bc-java` | groovy | multi-module | 9.1.0 | multi-release JAR |
| `rxjava` | groovy | single-module | 7.6.4 | enterprise floor |
| `caffeine` | kotlin | multi-module | 9.5.0 | version catalog + composite build |
| `opentelemetry-java` | kotlin | multi-module | 9.6.1 | BOM; large multi-module |

## Coverage — synthetic fixtures

Cosmetic variety is covered by the real repos above; the **execution-model and
topology edges** that can silently drop dependencies are isolated by the
hermetic fixtures in [`tests/fixtures/gradle/`](../../../../tests/fixtures/gradle/):

| Fixture | Isolated variable |
|---------|-------------------|
| `single-module` | root-only build |
| `configure-on-demand` | `org.gradle.configureondemand=true` |
| `configuration-cache` | `org.gradle.configuration-cache=true` |
| `composite-substitution` | `includeBuild` production dependency (known gap) |
| `java-platform` | BOM project with no `runtimeClasspath` |

## Version matrix runner

`tests/test_gradle_capture_matrix.py` runs the fixtures against a matrix of
Gradle versions (7.6.4 / 8.13 / 9.6.1) using the **real** init script from
`gradle_dep_tree_parser`, asserting each fixture's expected sections. It is
opt-in (marker `gradle_matrix`, gated on `OMNIBOR_GRADLE_MATRIX=1` and a
bootstrap `gradle` on `PATH`) so it never runs in the default unit gate.
