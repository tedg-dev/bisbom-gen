# Runtime Timing Policy

All analysis runs MUST capture granular per-step timing with CPU
monitoring. Baseline (non-instrumented) builds are run once per repo
and stored for comparison.

## Baseline (Non-Instrumented Build Time)

- Run ONCE per repo per language: clean + configure + build WITHOUT
  bomtrace/strace
- Each step (clean, prebuild, build) is timed **separately** —
  exactly mirroring the instrumented path — so the build step can
  be compared apples-to-apples
- Store in `output/runtime/<lang>/<repo>/baseline.json` as a
  ``{"steps": [...], "run_ts": "..."}`` structure
- Repos are pinned to specific versions (for golden file accuracy),
  so baseline is stable
- Re-run baseline only when repo version changes in `config.yaml`
- Each step records CPU metrics (same as instrumented runs)

## CPU Monitoring (Every Timed Step)

- **Primary:** `resource.getrusage(RUSAGE_CHILDREN)` — user+sys CPU
  time (stdlib, always available)
- **Secondary:** `/usr/bin/time -v` wrapper on Linux — captures all
  descendant CPU, max RSS, context switches
- **Load average:** `os.getloadavg()` sampled at start and end of
  each step
- **CPU count:** `os.cpu_count()`
- **Contention threshold:** `cpu_efficiency < expected * 0.70`
  (70% of expected efficiency = flag as contention)
- **Expected efficiency:** `min(parallel_jobs, cpu_count)`

## Per-Step Timing (Every Analysis Run)

### Phase 1 — Build Interception

| Timer | What it measures |
|-------|-----------------|
| `clean_dur` | `clean_cmd` (e.g. `make clean`) |
| `configure_dur` | Pre-build steps (e.g. `./configure`) |
| `build_dur` | Instrumented compilation only (bomtrace/strace + build command) |

### Phase 2 — Post-Build Analysis (no baseline equivalent)

| Timer | What it measures |
|-------|-----------------|
| `adg_dur` | `bomsh_create_bom.py` / `bomsh_create_bom_java.py` (+ dep:tree for Java sidecar) |
| `bisbom_sbom_dur` | `bomsh_sbom.py` → `_bisbom.spdx.json` + metadata patch + HTML viz |
| `metadata_dur` | `collect_metadata.py` + `collect_dynamic_libs.py` |
| `spdx_gen_dur` | `AdgSpdxGenerator` / `JavaSpdxGenerator` → `_analyzed` + `_build` `.spdx.json` + HTML |
| `validate_dur` | JSON schema + semantic validation |
| `collect_dur` | Binary collection to `output/binaries/` |

## Storage

- Per-run: `output/runtime/<lang>/<repo>/<ts>/runtime.json`
- Baseline: `output/runtime/<lang>/<repo>/baseline.json`
- Both use the same datetime-stamp folder convention as SPDX output

## Run Report (runtime.md)

Every run MUST produce a report showing:

1. All per-step durations with CPU efficiency per step
2. Phase 1 total and Phase 2 total
3. Non-instrumented baseline build time (from `baseline.json`)
4. Build overhead (build step only):
   `(instrumented_build - baseline_build) / baseline_build × 100`
   — compares ONLY the build step (the sole difference between
   baseline and instrumented). Pre-build and clean are captured
   but NOT included in overhead calculation.
   Phase 2 has NO baseline comparison (entirely new work).
5. Contention flag per step if CPU efficiency < 70% of expected

## When Running Any Repo

- If `baseline.json` does not exist for the repo, run baseline FIRST
- Always store per-run timing data in `runtime.json`
- Always include baseline comparison in the report
- Always include CPU contention flags
