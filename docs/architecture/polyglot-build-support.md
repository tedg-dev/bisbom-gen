# Polyglot Build Support — Future Work

## Problem Statement

Some target repositories are **polyglot** — they contain multiple languages
and build systems in a single repository. The current OmniBOR analysis
container is equipped with toolchains for C/C++, Go, Rust, and Java
individually, but cannot build projects that require multiple toolchains
simultaneously or include non-supported languages (Python, TypeScript,
etc.) as build-time dependencies.

## Example: datahub

[DataHub](https://github.com/datahub-project/datahub) (`v1.5.0.1`) is a
metadata platform that uses Gradle as its primary build system but includes:

- **Java** — core services, metadata models, GraphQL API
- **Python** — `metadata-ingestion` module (requires Python 3.x + pip)
- **TypeScript/React** — `datahub-web-react` frontend (requires Node.js + npm)
- **Docker** — container build definitions as Gradle subprojects

Running `./gradlew build` fails in our container because Node.js and
Python toolchains are not installed, and the Gradle build does not
provide a way to build only the Java subprojects without also triggering
the frontend and ingestion builds.

## Why datahub Was Removed

datahub was removed from `config.yaml` because:

1. Build consistently fails (~272s) due to missing Node.js/Python toolchains
2. No straightforward Gradle exclude pattern covers all non-Java subprojects
3. Adding Node.js + Python to the Docker image significantly increases
   image size and complexity
4. The SPDX output would be incomplete (missing frontend/ingestion deps)

## Proposed Approach for Next Generation

### Option A: Multi-Stage Analysis

Run separate analysis passes per language, then merge results:

1. Build Java subprojects only (`./gradlew :metadata-service:war:build`)
2. Analyze Python deps via `pip freeze` or `requirements.txt`
3. Analyze TypeScript deps via `package-lock.json`
4. Merge per-language SPDX documents into a unified project SPDX

### Option B: Extended Docker Image

Create a separate Docker image (`omnibor-env-polyglot`) with all
toolchains:

- Java (Maven + Gradle) — already present
- Python 3.x + pip
- Node.js + npm
- Additional build tools as needed

### Option C: Config-Driven Subproject Selection

Allow `config.yaml` to specify which Gradle/Maven subprojects to build:

```yaml
datahub:
  build_steps:
    - './gradlew build -x test -x :datahub-web-react:build -x :metadata-ingestion:build'
  include_subprojects:
    - 'metadata-service/**'
    - 'metadata-models'
    - 'entity-registry'
```

## Other Polyglot Candidates

Projects that may benefit from polyglot support in the future:

| Project | Primary | Secondary | Notes |
|---------|---------|-----------|-------|
| datahub | Java (Gradle) | Python, TypeScript | Metadata platform |
| Apache Spark | Scala (Maven) | Python, R | Big data framework |
| Elasticsearch | Java (Gradle) | Groovy | Search engine |
| VS Code | TypeScript | C++ (native modules) | Editor |

## Priority

Low — current language-specific pipelines cover the majority of
real-world projects. Polyglot support is a nice-to-have for
comprehensive enterprise SBOM coverage.
