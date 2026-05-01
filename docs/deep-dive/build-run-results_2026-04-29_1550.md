# Build Run Results — 2026-04-29

Full analysis re-run of all 21 configured repositories with
root package version detection (PR #87).

## EC2 Build Host

| Field | Value |
|-------|-------|
| **Instance Type** | `c6i.xlarge` |
| **vCPUs** | 4 (2 cores × 2 threads) |
| **RAM** | 8 GB |
| **CPU** | Intel Xeon Platinum 8375C @ 2.90 GHz |
| **Storage** | 50 GB gp3 (3000 IOPS) |
| **OS** | Ubuntu 22.04 x86_64 (kernel 6.8.0-1052-aws) |
| **Docker** | 29.3.1 |
| **Region** | us-west-1 |

## Results — 21/21 Successful

| Language | Repo | Tag | Duration | Notes |
|----------|------|-----|----------|-------|
| C/C++ | openosc | v1.0.7 | 6s | Minimal C library, bomtrace3 |
| C/C++ | redis | 8.0-rc1 | 31s | Single-binary server, bomtrace3 |
| C/C++ | nmap | 7.95 | 51s | Network scanner, autoconf, bomtrace3 |
| C/C++ | curl | curl-8_12_1 | 72s | HTTP client, autoconf, bomtrace3 |
| C/C++ | ffmpeg | n7.1 | 741s (12m) | Large multimedia framework, bomtrace3 |
| C/C++ | node | v22.14.0 | 5,976s (100m) | V8 + libuv, massive C++ codebase, bomtrace3 |
| Go | fzf | v0.61.1 | 48s | Fuzzy finder, bomtrace2 |
| Go | croc | v10.2.3 | 75s | File transfer, bomtrace2 |
| Go | dive | v0.13.1 | 104s | Docker image explorer, bomtrace2 |
| Go | gdu | v5.34.1 | 119s | Disk usage analyzer, bomtrace2 |
| Go | lazygit | v0.46.0 | 122s | Git TUI, bomtrace2 |
| Go | pocketbase | v0.28.1 | 152s | Backend framework, bomtrace2 |
| Rust | oxipng | v9.1.4 | 41s | PNG optimizer, bomtrace2 |
| Rust | dura | v0.2.0 | 175s | Auto-commit daemon, bomtrace2 |
| Java | jsoup | jsoup-1.18.3 | 35s | HTML parser, zero runtime deps, strace |
| Java | checkstyle | checkstyle-10.22.0 | 72s | Static analysis, Maven, strace |
| Java | crawler4j | crawler4j-4.4.0 | 119s | Web crawler, Maven, strace |
| Java | logging-log4j2 | rel/2.24.3 | 136s | Log4j2, Maven multi-module (JDK 17), strace |
| Java | dependency-check | v9.2.0 | 272s | OWASP scanner, Maven multi-module, strace |
| Java | bc-java | r1bcpg81 | 292s | Bouncy Castle crypto, Gradle, strace |
| Java | spring-boot | v3.3.0 | 570s (10m) | Spring framework, Gradle multi-module, strace |

## Aggregate

| Metric | Value |
|--------|-------|
| **Total repos** | 21 |
| **Successful** | 21 (100%) |
| **Total wall-clock time** | ~154 min |
| **Longest build** | node (100 min) |
| **Shortest build** | openosc (6s) |
| **Median build** | ~119s |

## Performance Notes

- **C/C++ builds are ptrace-instrumented** (bomtrace3), which adds
  significant overhead to compilation. node's 100-min build time is
  dominated by V8 engine compilation under ptrace interception.
- **Go and Rust builds use LD_PRELOAD** (bomtrace2), which has much
  lower overhead than ptrace.
- **Java builds use strace** for post-build file access analysis,
  with minimal build overhead.
- All builds ran **sequentially** — no parallelism between repos.
- Docker container resource limits match the host (no CPU/memory caps).
- node consistently saturates all 4 vCPUs during compilation (~400% CPU).

## Changes Since Last Run

- **PR #87**: Root package version detection for all languages
- **dive fix**: Binary output renamed to `dive_bin` to avoid directory
  name conflict; `binary_collector.py` now guards against directories
- **datahub removed**: Polyglot project (Java + Python + Node.js)
  not buildable in current container
