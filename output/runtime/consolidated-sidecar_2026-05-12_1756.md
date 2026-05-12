# Consolidated Runtime Report — SIDECAR Mode

> **ALL SIDECAR MODE**

> **All runs in this report used SIDECAR mode.** No other modes are included.

**Generated from:** `output/runtime`

## Interception Method

**Mode: SIDECAR** — builds run unmodified or with lightweight compiler hooks. No ptrace or LD_PRELOAD.

| Language | Tracer | Mechanism |
|----------|--------|-----------|

| java | dep:tree | Build runs unmodified + dep:tree captures dependencies. |


> **Note:** Baselines are mode-independent — they run clean + build with NO tracer. Overhead = (instrumented build - baseline build) / baseline build. Only the build step is compared (apples-to-apples).


## Executive Summary

| Language | Repo | Baseline Build (s) | Instrumented Build (s) | Overhead | Phase 2 (s) | Total (s) | Contention |
|----------|------|--------------------|----------------------|----------|-------------|-----------|-----------|
| java | bc-java | 140.7s | 140.9s | +0.2% | 444.3s | 610.5s | 1/8 (23.1%) |
| java | checkstyle | 41.8s | 40.2s | -3.8% | 33.3s | 84.5s | 0/8 (0.0%) |
| java | crawler4j | 98.9s | 106.2s | +7.4% | 10.4s | 118.9s | 2/8 (89.6%) |
| java | dependency-check | 30.0s | 29.6s | -1.3% | 1054.0s | 1105.0s | 0/8 (0.0%) |
| java | jsoup | 25.1s | 26.8s | +6.6% | 13.5s | 43.9s | 1/8 (1.2%) |
| java | logging-log4j2 | 120.9s | 122.6s | +1.4% | 36.3s | 162.4s | 0/8 (0.0%) |
| java | omnibor-java-testapp | 6.4s | 7.3s | +13.9% | 10.5s | 19.9s | 0/8 (0.0%) |
| java | spring-boot | 56.7s | 55.5s | -2.0% | 2880.5s | 2998.9s | 1/8 (1.9%) |
| **ALL** | **8 repos** | **520.5s** | **529.2s** | **+1.7%** | **4482.8s** | **5144.0s** | — |

> **Reading this table:** Rows showing &ldquo;&mdash;&rdquo; for Baseline and Overhead have old-format baselines that lack per-step timing. These repos must be re-baselined before overhead can be calculated. Rows with a numeric Overhead compare only the build step (baseline build vs. instrumented build). The baseline build and the instrumented build run at different times under different system conditions (cache state, background load, scheduler decisions), so the same build can finish in 4 s one run and 7 s the next. On short builds (&lt;10 s) this variance dominates the percentage. Check the Contention column &mdash; rows with high contention mean the machine&rsquo;s CPU was partly consumed by other processes, inflating ALL timing numbers in that row.


## Per-Language Summary

| Language | Repos | Avg Baseline Build (s) | Avg Instrumented Build (s) | Avg Overhead | Avg Phase 2 (s) | Avg Total (s) |
|----------|-------|------------------|----------------|--------------|-----------------|----------------|
| java | 8 | 65.1s | 66.1s | +1.7% | 560.4s | 643.0s |

## Phase 2 Step Breakdown (All Repos)

This table shows the average wall time per Phase 2 step across all repos.

| Step | Avg Wall (s) | Total Wall (s) | Count |
|------|-------------|----------------|-------|
| ADG Generation | 214.1s | 1713.1s | 8 |
| OmniBOR SBOM | 0.0s | 0.0s | 8 |
| Metadata | 315.9s | 2527.4s | 8 |
| SPDX Generation | 24.3s | 194.4s | 8 |
| Validation | 5.9s | 47.4s | 8 |
| Binary Collection | 0.1s | 0.5s | 8 |

## Contention Hotspots

Steps with contention severity > 0%, sorted by severity.

| Language | Repo | Step | Wall (s) | Expected | Actual | Severity |
|----------|------|------|----------|----------|--------|----------|
| java | spring-boot | Build | 55.5s | 4x | 0.04x | 98% below |
| java | crawler4j | Build | 106.2s | 1x | 0.28x | 60% below |
| java | bc-java | Build | 140.9s | 4x | 2.68x | 4% below |

## Build Step Detail — Baseline vs Instrumented

Compares the build step specifically (the compilation/linking step).

| Language | Repo | Baseline Build (s) | Instrumented Build (s) | Build Overhead | CPU Eff | Expected |
|----------|------|--------------------|----------------------|----------------|---------|----------|
| java | bc-java | 140.7s | 140.9s | +0.2% | 2.68x | 4x |
| java | checkstyle | 41.8s | 40.2s | -3.8% | 1.83x | 1x |
| java | crawler4j | 98.9s | 106.2s | +7.4% | 0.28x | 1x |
| java | dependency-check | 30.0s | 29.6s | -1.3% | 2.10x | 1x |
| java | jsoup | 25.1s | 26.8s | +6.6% | 2.13x | 1x |
| java | logging-log4j2 | 120.9s | 122.6s | +1.4% | 2.62x | 1x |
| java | omnibor-java-testapp | 6.4s | 7.3s | +13.9% | 1.62x | 1x |
| java | spring-boot | 56.7s | 55.5s | -2.0% | 0.04x | 4x |

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
