# Consolidated Runtime Report — STANDALONE Mode

> **ALL STANDALONE MODE**

> **All runs in this report used STANDALONE mode.** No other modes are included.

**Generated from:** `output/runtime`

## Interception Method

**Mode: STANDALONE** — builds are intercepted at the syscall level using a tracer prefix (bomtrace3, bomtrace2, or strace).

| Language | Tracer | Mechanism |
|----------|--------|-----------|

| c-cpp | bomtrace3 (ptrace) | ptrace — intercepts compiler/linker syscalls. Preserves parallelism. |

| go | bomtrace2 (LD_PRELOAD) | LD_PRELOAD — interposes on libc calls. **Serializes parallel builds.** |

| java | strace (ptrace) | ptrace — traces openat syscalls. Preserves parallelism. |

| rust | bomtrace2 (LD_PRELOAD) | LD_PRELOAD — interposes on libc calls. **Serializes parallel builds.** |


> **Note:** Baselines are mode-independent — they run clean + build with NO tracer. Overhead = (instrumented build - baseline build) / baseline build. Only the build step is compared (apples-to-apples).


## Executive Summary

| Language | Repo | Baseline Build (s) | Instrumented Build (s) | Overhead | Phase 2 (s) | Total (s) | Contention |
|----------|------|--------------------|----------------------|----------|-------------|-----------|-----------|
| c-cpp | curl | — | 51.5s | — | 13.9s | 83.0s | 3/9 (2.3%) |
| c-cpp | ffmpeg | — | 712.8s | — | 127.7s | 849.5s | 1/9 (0.2%) |
| c-cpp | nmap | — | 34.3s | — | 19.0s | 67.8s | 0/9 (0.0%) |
| c-cpp | node | — | 5832.2s | — | 107.0s | 5942.8s | 0/9 (0.0%) |
| c-cpp | openosc | — | 0.8s | — | 3.7s | 9.4s | 3/9 (9.4%) |
| c-cpp | redis | — | 30.0s | — | 12.1s | 42.3s | 1/8 (0.4%) |
| go | croc | — | 69.6s | — | 35.9s | 105.5s | 2/8 (66.3%) |
| go | dive | — | 96.0s | — | 50.3s | 146.3s | 2/8 (65.9%) |
| go | fzf | — | 45.7s | — | 21.2s | 67.0s | 3/8 (68.8%) |
| go | gdu | — | 108.0s | — | 50.4s | 158.4s | 2/8 (68.4%) |
| go | lazygit | — | 113.8s | — | 43.0s | 156.8s | 1/8 (72.6%) |
| go | pocketbase | — | 143.2s | — | 67.6s | 210.8s | 3/8 (68.2%) |
| java | bc-java | 140.7s | 168.2s | +19.6% | 319.0s | 512.1s | 1/8 (32.8%) |
| java | checkstyle | 41.8s | 36.3s | -13.3% | 23.7s | 65.4s | 0/8 (0.0%) |
| java | crawler4j | 98.9s | 94.7s | -4.2% | 6.2s | 103.0s | 2/8 (92.3%) |
| java | dependency-check | 30.0s | 27.4s | -8.6% | 1068.3s | 1112.8s | 0/8 (0.0%) |
| java | jsoup | 25.1s | 24.6s | -1.9% | 11.2s | 40.2s | 0/8 (0.0%) |
| java | logging-log4j2 | 120.9s | 116.5s | -3.6% | 25.5s | 145.2s | 0/8 (0.0%) |
| java | omnibor-java-testapp | 6.4s | 3.6s | -43.5% | 5.1s | 10.1s | 0/8 (0.0%) |
| java | spring-boot | 56.7s | 63.9s | +12.7% | 2091.9s | 2218.4s | 1/8 (2.9%) |
| rust | dura | — | 169.7s | — | 14.8s | 184.7s | 3/8 (92.0%) |
| rust | oxipng | — | 39.7s | — | 5.3s | 45.3s | 3/8 (88.4%) |
| **ALL** | **22 repos** | **520.5s** | **535.2s** | **+2.8%** | **4122.9s** | **12276.7s** | — |

> **Reading this table:** Rows showing &ldquo;&mdash;&rdquo; for Baseline and Overhead have old-format baselines that lack per-step timing. These repos must be re-baselined before overhead can be calculated. Rows with a numeric Overhead compare only the build step (baseline build vs. instrumented build). The baseline build and the instrumented build run at different times under different system conditions (cache state, background load, scheduler decisions), so the same build can finish in 4 s one run and 7 s the next. On short builds (&lt;10 s) this variance dominates the percentage. Check the Contention column &mdash; rows with high contention mean the machine&rsquo;s CPU was partly consumed by other processes, inflating ALL timing numbers in that row.


## Per-Language Summary

| Language | Repos | Avg Baseline Build (s) | Avg Instrumented Build (s) | Avg Overhead | Avg Phase 2 (s) | Avg Total (s) |
|----------|-------|------------------|----------------|--------------|-----------------|----------------|
| c-cpp | 6 | — | — | — | 47.2s | 1165.8s |
| go | 6 | — | — | — | 44.7s | 140.8s |
| java | 8 | 65.1s | 66.9s | +2.8% | 443.9s | 525.9s |
| rust | 2 | — | — | — | 10.1s | 115.0s |

## Phase 2 Step Breakdown (All Repos)

This table shows the average wall time per Phase 2 step across all repos.

| Step | Avg Wall (s) | Total Wall (s) | Count |
|------|-------------|----------------|-------|
| ADG Generation | 37.1s | 815.1s | 22 |
| OmniBOR SBOM | 1.6s | 35.6s | 22 |
| Metadata | 129.0s | 2836.9s | 22 |
| SPDX Generation | 11.3s | 249.3s | 22 |
| Validation | 8.4s | 185.1s | 22 |
| Binary Collection | 0.0s | 0.8s | 22 |

## Contention Hotspots

Steps with contention severity > 0%, sorted by severity.

| Language | Repo | Step | Wall (s) | Expected | Actual | Severity |
|----------|------|------|----------|----------|--------|----------|
| java | spring-boot | Build | 63.9s | 4x | 0.24x | 92% below |
| c-cpp | ffmpeg | Clean | 2.0s | 1x | 0.23x | 67% below |
| java | crawler4j | Build | 94.7s | 1x | 0.33x | 53% below |
| go | fzf | Build | 45.7s | 4x | 1.45x | 48% below |
| go | croc | Build | 69.6s | 4x | 1.61x | 42% below |
| rust | oxipng | Build | 39.7s | 4x | 1.62x | 42% below |
| go | dive | Build | 96.0s | 4x | 1.63x | 42% below |
| go | lazygit | Build | 113.8s | 4x | 1.72x | 39% below |
| rust | dura | Build | 169.7s | 4x | 1.76x | 37% below |
| go | gdu | Build | 108.0s | 4x | 1.81x | 35% below |
| go | pocketbase | Build | 143.2s | 4x | 1.97x | 30% below |
| c-cpp | curl | Validation | 1.1s | 1x | 0.56x | 20% below |
| java | bc-java | Build | 168.2s | 4x | 2.46x | 12% below |

## Build Step Detail — Baseline vs Instrumented

Compares the build step specifically (the compilation/linking step).

| Language | Repo | Baseline Build (s) | Instrumented Build (s) | Build Overhead | CPU Eff | Expected |
|----------|------|--------------------|----------------------|----------------|---------|----------|
| c-cpp | curl | — | 51.5s | — | 3.57x | 4x |
| c-cpp | ffmpeg | — | 712.8s | — | 0.99x | 1x |
| c-cpp | nmap | — | 34.3s | — | 3.83x | 4x |
| c-cpp | node | — | 5832.2s | — | 3.87x | 4x |
| c-cpp | openosc | — | 0.8s | — | 1.52x | 4x |
| c-cpp | redis | — | 30.0s | — | 3.39x | 4x |
| go | croc | — | 69.6s | — | 1.61x | 4x |
| go | dive | — | 96.0s | — | 1.63x | 4x |
| go | fzf | — | 45.7s | — | 1.45x | 4x |
| go | gdu | — | 108.0s | — | 1.81x | 4x |
| go | lazygit | — | 113.8s | — | 1.72x | 4x |
| go | pocketbase | — | 143.2s | — | 1.97x | 4x |
| java | bc-java | 140.7s | 168.2s | +19.6% | 2.46x | 4x |
| java | checkstyle | 41.8s | 36.3s | -13.3% | 1.90x | 1x |
| java | crawler4j | 98.9s | 94.7s | -4.2% | 0.33x | 1x |
| java | dependency-check | 30.0s | 27.4s | -8.6% | 2.03x | 1x |
| java | jsoup | 25.1s | 24.6s | -1.9% | 2.09x | 1x |
| java | logging-log4j2 | 120.9s | 116.5s | -3.6% | 2.57x | 1x |
| java | omnibor-java-testapp | 6.4s | 3.6s | -43.5% | 2.82x | 1x |
| java | spring-boot | 56.7s | 63.9s | +12.7% | 0.24x | 4x |
| rust | dura | — | 169.7s | — | 1.76x | 4x |
| rust | oxipng | — | 39.7s | — | 1.62x | 4x |

## Appendix: Definitions

<table>
<tr><th style="width:200px">Term</th><th>Definition</th></tr>
<tr><td><strong>Wall time</strong></td><td>Wall-clock time &mdash; the real elapsed time from start to finish, as measured by a clock on the wall. The standard term in performance measurement (used by <code>/usr/bin/time</code>, <code>perf</code>, etc.). How long you actually waited.</td></tr>
<tr><td><strong>CPU time</strong></td><td>Total CPU consumed across all cores (user + system). A 4-core machine running at full utilization for 10 seconds produces 40 seconds of CPU time.</td></tr>
<tr><td><strong>CPU efficiency</strong></td><td>CPU time / wall time. Measures how well the build utilizes available cores. An efficiency of 3.57x means 3.57 cores were busy on average.</td></tr>
<tr><td><strong>Expected parallelism</strong></td><td>The number of cores the build tool is expected to use. Inferred from the build command: <code>make -jN</code> = N, <code>go build</code> / <code>cargo build</code> = cpu_count, <code>mvn</code> = 1 (sequential).</td></tr>
<tr><td><strong>Contention</strong></td><td>Shows <code>F/T (P%)</code> where F = number of steps where the build could not get the CPU cores it needed (another process was consuming them), T = total steps, and P% = fraction of total wall time affected. A step is flagged when its actual CPU utilization falls below 70% of the cores the build tool requested (e.g. <code>make&nbsp;-j4</code> expected 4 cores but only achieved 1.5). <strong>When contention is high, ALL timing numbers in that row are inflated </strong> &mdash; the build waited for CPU that was unavailable, so wall times are longer than they would be on an idle machine. Overhead percentages for rows with significant contention should be interpreted with caution.</td></tr>
<tr><td><strong>Baseline (s)</strong></td><td>Non-instrumented build wall-clock seconds. The build runs without any tracer (no bomtrace, no strace) to establish a reference.</td></tr>
<tr><td><strong>Phase 1 (s)</strong></td><td>Instrumented build Phase 1 wall-clock seconds. Includes clean + pre-build + instrumented build (with tracer).</td></tr>
<tr><td><strong>Phase 2 (s)</strong></td><td>Post-build analysis wall-clock seconds. Includes ADG generation, OmniBOR SBOM, metadata collection, SPDX generation, validation, and binary collection.</td></tr>
<tr><td><strong>Overhead</strong></td><td><code>(Instrumented Build - Baseline Build) / Baseline Build &times; 100</code>. The percentage increase in the build step only, caused by the instrumentation tracer.</td></tr>
</table>
