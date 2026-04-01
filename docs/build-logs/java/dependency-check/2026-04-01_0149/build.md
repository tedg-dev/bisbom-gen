# Build Log — dependency-check

**Date:** 2026-04-01T02:12:21.672591
**Status:** SUCCESS
**Duration:** 374.5 seconds

## Repository

- **URL:** https://github.com/jeremylong/DependencyCheck.git
- **Branch:** v9.2.0
- **Description:** OWASP dependency-check CLI (6 modules - utils, core, cli, ant, maven, archetype)

## Build Steps

1. `mvn package -DskipTests -q -pl cli -am`

## Instrumentation

- **Tracer:** unknown
- **Raw logfile:** /tmp/bomsh_hook_raw_logfile.sha1

## Output Binaries

- `**/target/*.jar`

## Release Build Verification

**Classification:** RELEASE
**Reason:** mvn package -DskipTests

No debug or development flags detected. Build targets production/release binaries.
