# Build Log — node

**Date:** 2026-03-16T23:54:54.109949
**Status:** SUCCESS
**Duration:** 5947.0 seconds

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
