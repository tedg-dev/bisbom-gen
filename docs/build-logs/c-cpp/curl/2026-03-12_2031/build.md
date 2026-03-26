# Build Log — curl

**Date:** 2026-03-12T20:33:20.576483
**Status:** SUCCESS
**Duration:** 70.2 seconds

## Repository

- **URL:** https://github.com/curl/curl.git
- **Branch:** master
- **Description:** HTTP transfer library and CLI tool (~170K LoC)

## Build Steps

1. `autoreconf -fi`
2. `./configure --with-openssl --with-zlib --with-nghttp2 --with-libssh2 --with-brotli`
3. `make -j$(nproc)`

## Instrumentation

- **Tracer:** bomtrace3
- **Raw logfile:** /tmp/bomsh_hook_raw_logfile.sha1

## Output Binaries

- `src/.libs/curl`
- `lib/.libs/libcurl.so`
