# Build Log — redis

**Date:** 2026-03-10T22:13:01.795699
**Status:** SUCCESS
**Duration:** 39.3 seconds

## Repository

- **URL:** https://github.com/redis/redis.git
- **Branch:** unstable
- **Description:** In-memory data store with 8 vendored libs (jemalloc, lua, hiredis, etc.) (~293K LoC, C)

## Build Steps

1. `make -j$(nproc)`

## Instrumentation

- **Tracer:** bomtrace3
- **Raw logfile:** /tmp/bomsh_hook_raw_logfile.sha1

## Output Binaries

- `src/redis-server`
- `src/redis-cli`
