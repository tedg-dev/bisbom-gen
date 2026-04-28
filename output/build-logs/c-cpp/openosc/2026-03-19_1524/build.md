# Build Log — openosc

**Date:** 2026-03-19T15:24:15.208423
**Status:** SUCCESS
**Duration:** 5.7 seconds

## Repository

- **URL:** https://github.com/cisco/OpenOSC.git
- **Branch:** master
- **Description:** Cisco Open Object Size Checking library — buffer overflow detection for C/C++ (v1.0.8, Apache 2.0)

## Build Steps

1. `autoreconf -vfi`
2. `./configure --disable-safec`
3. `make -j$(nproc)`

## Instrumentation

- **Tracer:** bomtrace3
- **Raw logfile:** /tmp/bomsh_hook_raw_logfile.sha1

## Output Binaries

- `src/.libs/libopenosc.so`
