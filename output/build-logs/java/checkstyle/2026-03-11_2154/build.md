# Build Log — checkstyle

**Date:** 2026-03-11T21:56:07.697758
**Status:** SUCCESS
**Duration:** 66.7 seconds

## Repository

- **URL:** https://github.com/checkstyle/checkstyle.git
- **Branch:** master
- **Description:** Static analysis tool (14 direct, 12 transitive - antlr, guava, picocli, commons-beanutils)

## Build Steps

1. `mvn package -DskipTests -q`

## Instrumentation

- **Tracer:** bomtrace2 (Go-specific conf)
- **Raw logfile:** /tmp/bomsh_hook_raw_logfile.sha1
- **Watched tools:** compile, link

## Output Binaries

- `target/checkstyle-*-all.jar`
