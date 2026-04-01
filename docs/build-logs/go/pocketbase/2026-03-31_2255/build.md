# Build Log — pocketbase

**Date:** 2026-03-31T22:58:55.851610
**Status:** SUCCESS
**Duration:** 140.6 seconds

## Repository

- **URL:** https://github.com/pocketbase/pocketbase.git
- **Branch:** v0.25.9
- **Description:** Open source backend (Go, SQLite, REST API, auth, realtime subscriptions)

## Build Steps

1. `go build -a -trimpath -ldflags="-s -w" -o pocketbase ./examples/base`

## Instrumentation

- **Tracer:** bomtrace2 -c /opt/bomsh/bin/bomtrace_go.conf
- **Raw logfile:** /tmp/bomsh_hook_raw_logfile.sha1

## Output Binaries

- `pocketbase`

## Release Build Verification

**Classification:** RELEASE
**Reason:** go build with -trimpath -ldflags="-s -w"

No debug or development flags detected. Build targets production/release binaries.
