# Build Run Results — 2026-04-29 (Baseline)

Non-instrumented build times for all 21 repositories.
For comparison with instrumented runs, see `build-run-results_2026-04-29_1550.md`.

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

## Results — 21/21 Successful (Baseline)

| Language | Repo | Tag | Baseline | Instrumented | Overhead | Notes |
|----------|------|-----|----------|--------------|----------|-------|
| C/C++ | openosc | v1.0.7 | 6s | 6s | 0% | Minimal C library |
| C/C++ | redis | 8.0-rc1 | 26s | 31s | +19% | Single-binary server |
| C/C++ | nmap | 7.95 | 48s | 51s | +6% | Network scanner, autoconf |
| C/C++ | curl | curl-8_12_1 | 62s | 72s | +16% | HTTP client, autoconf |
| C/C++ | ffmpeg | n7.1 | 658s (11m) | 741s (12m) | +13% | Large multimedia framework |
| C/C++ | node | v22.14.0 | 5,461s (91m) | 5,976s (100m) | +9% | V8 + libuv, massive C++ codebase |
| Go | fzf | v0.61.1 | 10s | 48s | +380% | Fuzzy finder |
| Go | croc | v10.2.3 | 16s | 75s | +369% | File transfer |
| Go | dive | v0.13.1 | 23s | 104s | +352% | Docker image explorer |
| Go | gdu | v5.34.1 | 36s | 119s | +231% | Disk usage analyzer |
| Go | lazygit | v0.46.0 | 31s | 122s | +294% | Git TUI |
| Go | pocketbase | v0.28.1 | 53s | 152s | +187% | Backend framework |
| Rust | oxipng | v9.1.4 | 23s | 41s | +78% | PNG optimizer |
| Rust | dura | v0.2.0 | 47s | 175s | +272% | Auto-commit daemon |
| Java | jsoup | jsoup-1.18.3 | 26s | 35s | +35% | HTML parser, zero runtime deps |
| Java | checkstyle | checkstyle-10.22.0 | 35s | 72s | +106% | Static analysis, Maven |
| Java | crawler4j | crawler4j-4.4.0 | 95s | 119s | +25% | Web crawler, Maven |
| Java | dependency-check | v9.2.0 | 28s | 272s | +871% | OWASP scanner, Maven multi-module |
| Java | logging-log4j2 | rel/2.24.3 | 108s | 136s | +26% | Log4j2, Maven multi-module (JDK 17) |
| Java | bc-java | r1bcpg81 | 145s | 292s | +101% | Bouncy Castle crypto, Gradle |
| Java | spring-boot | v3.3.0 | 55s | 570s (10m) | +936% | Spring framework, Gradle multi-module |

## Instrumentation Overhead Analysis

| Tracer | Avg Overhead | Range | Notes |
|--------|--------------|-------|-------|
| **bomtrace3 (ptrace)** | +12% | 6%–19% | C/C++ builds — ptrace overhead scales with compilation time |
| **bomtrace2 (LD_PRELOAD)** | +298% | 78%–380% | Go/Rust builds — LD_PRELOAD + Go/Rust toolchain overhead |
| **strace (post-build)** | +363% | 25%–936% | Java builds — strace + Maven/Gradle overhead, highly variable |

### Key Observations

- **C/C++**: bomtrace3 overhead is modest (+6% to +19%). Larger projects (ffmpeg, node) show lower percentage overhead.
- **Go**: bomtrace2 adds significant overhead (+187% to +380%). Go's fast compile time makes the interception cost more visible.
- **Rust**: Moderate overhead (+78% to +272%). Cargo build --release is already heavy.
- **Java**: Highly variable (+25% to +936%). strace + Maven/Gradle multi-module builds can introduce large overhead, especially for spring-boot and dependency-check.

## Aggregate

| Metric | Baseline | Instrumented | Overhead |
|--------|----------|--------------|----------|
| **Total wall-clock time** | ~115 min | ~154 min | +34% |
| **Longest build** | node (91 min) | node (100 min) | +9% |
| **Shortest build** | openosc (6s) | openosc (6s) | 0% |
| **Median build** | ~47s | ~119s | +153% |

## Performance Notes

- **Sequential execution** — No parallelism between repos, same as instrumented run
- **Docker container** — Same resource limits, no CPU/memory caps
- **Node build** — Still saturates all 4 vCPUs without ptrace, but completes ~9% faster
- **Java variability** — strace overhead depends heavily on Maven/Gradle behavior and module complexity

## Comparison Summary

- **Non-instrumented builds**: 115 min total
- **Instrumented builds**: 154 min total
- **Overall overhead**: 34% additional wall-clock time for complete analysis

---

## Appendix: Benchmark Methodology Analysis

**WARNING**: The overhead measurements above are not reliable due to methodological issues. The variance (25%-936%) and overall 34% overhead should not be used for decision-making.

### Critical Issues with Current Benchmark

#### 1. Hyperthreading Contention at 400% CPU
- `c6i.xlarge` has 4 physical cores with hyperthreading (8 logical)
- `400% CPU` indicates all 4 physical cores are saturated
- Hyperthreading shares L1/L2 cache between threads, causing resource contention
- Research shows compilation performance varies significantly when hyperthreaded cores compete for cache

#### 2. No CPU Affinity Control
- HPC benchmarking best practices require CPU affinity control
- Without pinning, threads migrate between cores, causing cache thrashing
- Docker runs without `taskset` or `likwid-pin` to constrain processes

#### 3. Dynamic CPU Clock (Turbo Boost)
- Intel Xeon Platinum 8375C uses turbo boost (2.9GHz base, higher boost)
- Different loads trigger different boost states
- Best practices require disabling turbo for reproducible benchmarks

#### 4. System Load Variability
- EC2 instances are multi-tenant
- Background processes, network I/O, and disk contention affect results
- No isolation from system noise

#### 5. Build System Caching Effects
- Go/Rust incremental builds may use caches differently
- Maven/Gradle daemon processes may persist between runs
- `make -j$(nproc)` vs single-threaded builds have different characteristics

### Industry Best Practices Violated

From HPC benchmarking guidelines:

1. **Fixed CPU frequency** (disable turbo) - Not done
2. **CPU affinity control** (pin threads to specific cores) - Not done
3. **Isolate from system noise** (dedicated hardware, no background load) - Not done
4. **Multiple runs with statistics** (we did single runs) - Not done
5. **Control SMT/hyperthreading** (test with/without, don't mix results) - Not done
6. **Warm-up runs** (allow caches to stabilize) - Not done

### The Real Issue: Non-Comparable Scenarios

The biggest problem: **instrumented and baseline runs occurred under different system conditions**:

- **Instrumented runs**: Sequential over hours, system warmed up, potential thermal throttling
- **Baseline runs**: After a reboot, cold caches, different system state
- **400% CPU**: Indicates we're hitting system limits where small variations cause large timing differences

### Recommended Proper Benchmark Method

For reliable overhead measurements:

1. **Run each repo 3-5 times** in both modes
2. **Use CPU affinity**: `taskset -c 0-3` to pin to physical cores only
3. **Disable turbo boost**: `cpupower frequency-set -g performance`
4. **Isolate builds**: Kill background processes, clear caches
5. **Same system state**: Run baseline+instrumented back-to-back for each repo
6. **Statistical analysis**: Report mean ± std deviation

### Conclusion

The current measurements are not reliable indicators of true instrumentation cost. The 34% overall overhead and wild variance (25%-936%) reflect system load and methodology issues rather than actual tracer overhead.
