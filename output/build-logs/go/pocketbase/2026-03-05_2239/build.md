# Build Log — pocketbase

**Date:** 2026-03-05T22:39:35.674915
**Status:** FAILED
**Duration:** 0.4 seconds

## Repository

- **URL:** https://github.com/pocketbase/pocketbase.git
- **Branch:** master
- **Description:** Open-source backend in 1 file (SQLite, Auth, S3) — 21 direct + 20 indirect Go deps

## Build Steps

1. `go mod vendor`
2. `CGO_ENABLED=0 go build -a -mod=vendor -o pocketbase ./examples/base`

## Instrumentation

- **Tracer:** bomtrace2 (Go-specific conf)
- **Raw logfile:** /tmp/bomsh_hook_raw_logfile.sha1
- **Watched tools:** compile, link

## Output Binaries

- `pocketbase`
