# `build_profile` — per-repo build-flavor schema

|  |  |
|---|---|
| **Audience** | Contributors adding/maintaining repos in `config.yaml` |
| **Author** | Ted G. (architect), Cascade AI |
| **Date** | 2026-07-22 |
| **Status** | Implemented |
| **Applies to** | All languages (C/C++, Go, Rust, Java) — this schema is generic, not language-specific |

## Purpose

Every repository analyzed by the pipeline declares **how it is built** in a
generic, machine-queryable way. Before this schema, build flavor was only
*implicit* — inferred from `build_steps` strings (e.g. scanning for
`mvn ... -pl` to detect a Maven reactor). The `build_profile` block makes the
build tool, project structure, and notable traits **explicit and validated**,
which enables:

- Coverage-matrix assertions (e.g. "do we exercise both Groovy and Kotlin
  Gradle DSLs, and Gradle 7.6 / 8.x / 9.x?").
- Self-documenting build docs (rendered as a metadata table).
- A single, config-driven source of truth with no per-repo logic in code.

## Schema

The block lives on each repo entry in `config.yaml`:

```yaml
# Gradle example
build_profile:
  tool: gradle              # required
  structure: multi-module   # required
  dsl: groovy               # optional (build-script language)
  tool_version: "8.13"      # optional (quoted string)
  traits: [dependency-management]  # optional
```

```yaml
# Gradle example pinning the build JDK (older Gradle needs an older JDK)
build_profile:
  tool: gradle
  structure: single-module
  dsl: groovy
  tool_version: "7.6.4"
  java_home: /usr/lib/jvm/java-17-openjdk-amd64  # optional
```

```yaml
# Maven example
build_profile:
  tool: maven
  structure: multi-module
  traits: [reactor, also-make, skip-tests]
```

```yaml
# C/C++ example
build_profile:
  tool: autotools
  structure: single-module
  traits: [vendored]
```

## Field reference

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `tool` | yes | string (enum) | The build driver. Must be in the controlled vocabulary below. |
| `structure` | yes | string (enum) | Project topology. Must be in the controlled vocabulary below. |
| `dsl` | no | string | Build-script language where meaningful (e.g. Gradle `groovy` vs `kotlin`). Omit when not applicable. |
| `tool_version` | no | quoted string | Pinned build-tool version when meaningful (e.g. the Gradle line). **Must be quoted** so YAML does not parse `8.13` as a float — the validator rejects non-strings. |
| `java_home` | no | string | Absolute in-container JDK path the build tool must **run** on. Set only when the container default JDK is incompatible (e.g. Gradle 7.6.x cannot run on JDK 21; its max supported runtime JDK is 19). The pipeline exports this as `JAVA_HOME` (and prepends its `bin/` to `PATH`) for the clean, build, and dependency-capture subprocesses. Repos without it use the container default JDK. |
| `traits` | no | list of strings | Additive, factual descriptors. Open vocabulary. |

## Controlled vocabulary

Defined in `app/config.py` as `BUILD_TOOLS` and `BUILD_STRUCTURES`.

**`tool`:**

`autotools`, `make`, `cmake`, `meson`, `cargo`, `go`, `maven`, `gradle`

**`structure`:**

`single-module`, `multi-module`, `workspace`

**`traits`** is intentionally open. Descriptors in use today:

| Trait | Meaning |
|-------|---------|
| `reactor` | Maven multi-module reactor build (`-pl`) |
| `also-make` | Maven `-am` (build required upstream modules) |
| `skip-tests` | Build skips test execution (release artifact only) |
| `dependency-management` | Uses a BOM / `io.spring.dependency-management` |
| `multi-release-jar` | Produces a multi-release JAR |
| `vendored` | Bundles third-party sources in-tree |
| `custom-configure` | Hand-written (non-autoconf) `./configure` |
| `gyp` | Uses GYP to generate the native build |
| `go-modules` | Go modules dependency management |
| `needs-review` | Auto-generated placeholder; a human must verify the profile |

## Validation

`app/config.py` enforces the schema:

- `validate_build_profile(profile, repo_name)` — validates a single block
  against the controlled vocabulary and field types.
- `validate_repos(config)` — requires **every** repo to declare a valid
  `build_profile`; configs without a `repos` section (e.g. minimal test
  fixtures) pass unchanged.

`load_config()` calls `validate_repos()` by default. Pass
`load_config(path, validate=False)` to load raw YAML without enforcement.

## `/add-repo` behavior

`ConfigGenerator.build_profile_for(build_system)` maps the build system
detected by `BuildSystemDetector` to a schema-valid `build_profile`:

| Detected system | `tool` | traits |
|-----------------|--------|--------|
| `autoconf`, `configure-only` | `autotools` | — |
| `cmake` | `cmake` | — |
| `meson` | `meson` | — |
| `perl-configure` | `make` | `perl-configure` |
| `auto-configure` | `make` | `auto-configure` |
| `make-only` | `make` | — |
| *unknown* | `make` | `needs-review` |

Unknown systems fall back to `make` with a `needs-review` trait so the
generated entry still loads but is clearly flagged for the reviewer.

## Rendering

`app/pipeline/doc_writer.py` renders the profile as a headerless metadata
table under a `## Build Profile` heading in each generated build doc.

## Current coverage matrix (Java)

For the Java repos specifically, the profiles capture our intended
build-flavor coverage:

| Repo | `tool` | `dsl` | `structure` | `tool_version` | `java_home` |
|------|--------|-------|-------------|----------------|-------------|
| `jsoup`, `checkstyle`, `omnibor-java-testapp` | maven | — | single-module | — | — |
| `crawler4j`, `dependency-check`, `logging-log4j2` | maven | — | multi-module | — | — |
| `spring-boot` | gradle | groovy | multi-module | `8.13` | — |
| `bc-java` | gradle | groovy | multi-module | `9.1.0` | — |
| `caffeine` | gradle | kotlin | multi-module | `9.5.0` | — |
| `opentelemetry-java` | gradle | kotlin | multi-module | `9.6.1` | — |
| `rxjava` | gradle | groovy | single-module | `7.6.4` | JDK 17 |

This matrix now exercises both Groovy and Kotlin Gradle DSLs, version
catalogs / composite builds (`caffeine`), a BOM aggregator
(`opentelemetry-java`), and the Gradle 7.6 enterprise floor (`rxjava`,
which pins `java_home` to JDK 17 because Gradle 7.6.4 cannot run on the
container's default JDK 21).
