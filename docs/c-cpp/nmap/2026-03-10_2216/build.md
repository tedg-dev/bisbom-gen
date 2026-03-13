# Build Log — nmap

**Date:** 2026-03-10T22:17:12.151749
**Status:** SUCCESS
**Duration:** 49.2 seconds

## Repository

- **URL:** https://github.com/nmap/nmap.git
- **Branch:** master
- **Description:** Network scanner with 10 vendored libs + 10+ dynamic system deps (~420 source files, C/C++)

## Build Steps

1. `./configure --with-libpcre=/usr --with-libz=/usr --with-libssh2=/usr --with-openssl=/usr --with-libdnet=included --with-liblua=included --with-liblinear=included --without-zenmap --without-ndiff`
2. `make -j$(nproc)`

## Instrumentation

- **Tracer:** bomtrace3
- **Raw logfile:** /tmp/bomsh_hook_raw_logfile.sha1

## Output Binaries

- `nmap`
- `ncat/ncat`
- `nping/nping`
