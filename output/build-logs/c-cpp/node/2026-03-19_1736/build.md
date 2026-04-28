# Build Log — node

**Date:** 2026-03-19T18:09:57.611910
**Status:** SUCCESS
**Duration:** 1917.5 seconds

## Repository

- **URL:** https://github.com/nodejs/node.git
- **Branch:** v22.19.0
- **Description:** Node.js JavaScript runtime — V8, libuv, OpenSSL, zlib, nghttp2, llhttp all vendored in deps/ (~4M LoC)

## Build Steps

1. `./configure`
2. `make -j$(nproc) CXXFLAGS='-Wno-error=unused-result'`

## Instrumentation

- **Tracer:** bomtrace3
- **Raw logfile:** /tmp/bomsh_hook_raw_logfile.sha1

## Output Binaries

- `out/Release/node`
