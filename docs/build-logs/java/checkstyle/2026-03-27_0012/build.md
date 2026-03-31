# Build Log — checkstyle

**Date:** 2026-03-27T00:14:08.226338
**Status:** SUCCESS
**Duration:** 61.5 seconds

## Repository

- **URL:** https://github.com/checkstyle/checkstyle.git
- **Branch:** checkstyle-13.3.0
- **Description:** Static analysis tool (14 direct, 12 transitive - antlr, guava, picocli, commons-beanutils)

## Build Steps

1. `mvn package -DskipTests -q`

## Instrumentation

- **Tracer:** unknown
- **Raw logfile:** /tmp/bomsh_hook_raw_logfile.sha1

## Output Binaries

- `**/target/*.jar`

## Release Build Verification

**Classification:** RELEASE
**Reason:** mvn package -DskipTests

No debug or development flags detected. Build targets production/release binaries.
