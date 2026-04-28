# Spring Boot — Repository Notes

## Overview

- **Repo**: <https://github.com/spring-projects/spring-boot.git>
- **Branch**: `v3.4.4`
- **Build system**: Gradle 8.13
- **JDK**: 21
- **Language**: Java (multi-module Gradle project)

## Module Structure

Spring Boot is a massive multi-module project. All submodules live
under `spring-boot-project/`:

| Module | Purpose |
|--------|---------|
| `spring-boot` | **Core framework** — the module we build |
| `spring-boot-actuator` | Health checks, metrics, info endpoints |
| `spring-boot-actuator-autoconfigure` | Auto-config for actuator |
| `spring-boot-autoconfigure` | Auto-configuration annotations and logic |
| `spring-boot-dependencies` | BOM — version management only, no code |
| `spring-boot-devtools` | Live reload, dev-time utilities |
| `spring-boot-docker-compose` | Docker Compose integration |
| `spring-boot-docs` | Documentation (reference guide) |
| `spring-boot-parent` | Parent POM — build config only |
| `spring-boot-starters` | Starter POMs (dozens of sub-modules) |
| `spring-boot-test` | Testing support (MockBean, etc.) |
| `spring-boot-test-autoconfigure` | Auto-config for test slices |
| `spring-boot-testcontainers` | Testcontainers integration |
| `spring-boot-tools` | Maven/Gradle plugins, CLI, loader |

## What We Build

We target **only** the core module:

```
./gradlew :spring-boot-project:spring-boot:build -x test -x check --no-daemon -q
```

This produces 3 JARs (and 3 SPDX SBOMs):

| JAR | Description |
|-----|-------------|
| `spring-boot-3.4.4.jar` | Core framework (~1.7 MB, ~120 runtime deps) |
| `spring-boot-configuration-processor-3.4.4.jar` | Annotation processor (~133 KB, ~4 deps) |
| `buildSrc.jar` | Build-time Gradle plugin code (~432 KB, ~117 deps) |

## Why Only One Module

Building the entire project would:

1. Take significantly longer (dozens of modules, each with tests)
2. Produce hundreds of JARs, many of which are starters (POM-only, no code)
3. Require additional infrastructure dependencies (Docker for testcontainers, etc.)

The core `spring-boot` module is the most meaningful target — it's the
actual framework code that ships in every Spring Boot application.

## Dependency Resolution

Dependencies are resolved per-module using the Gradle subproject path:

```
gradlew :spring-boot-project:spring-boot:dependencies --configuration runtimeClasspath
```

The `_gradle_project_from_dir()` method in `java_generator.py` derives
the subproject path from the JAR's build output directory relative to
the repo root.

## Build Performance

| Phase | Duration | Notes |
|-------|----------|-------|
| Gradle build | ~2-3 min | Cached after first run |
| bomsh post-build (strace → treedb) | ~25-35 min | ~113K `.class` file checksums |
| SPDX generation (Gradle dep trees) | ~2-3 min | One `gradlew dependencies` call per module |
| **Total** | **~30-40 min** | bomsh is the bottleneck |

The bomsh post-build step (`bomsh_create_bom_java.py`) is upstream
OmniBOR tooling, not our pipeline code. It runs `git hash-object` and
`dpkg-query --search` for every `.class` file in every dependency JAR.
