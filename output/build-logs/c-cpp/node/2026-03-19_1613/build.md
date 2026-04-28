# Build Log — node

**Date:** 2026-03-19T16:49:41.787001
**Status:** SUCCESS
**Duration:** 2047.8 seconds

## Repository

- **URL:** https://github.com/nodejs/node.git
- **Branch:** v22.x
- **Description:** Node.js JavaScript runtime — V8, libuv, OpenSSL, zlib, nghttp2, llhttp all vendored in deps/ (~4M LoC)

## Build Steps

1. `./configure`
2. `make -j$(nproc) CXXFLAGS='-Wno-error=unused-result'`

## Instrumentation

- **Tracer:** bomtrace3
- **Raw logfile:** /tmp/bomsh_hook_raw_logfile.sha1

## Output Binaries

- `out/Release/node`
