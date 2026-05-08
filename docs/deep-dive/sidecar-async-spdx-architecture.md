# Sidecar Async SPDX Architecture

| | |
|---|---|
| **Date** | 2026-05-05 |
| **Authors** | Ted G. (architect), Cascade AI |
| **Status** | Design — pending review and approval |
| **Prerequisite reading** | [Sidecar Implementation Design](sidecar-implementation-design.md), [Sidecar Refactoring Plan](sidecar-refactoring-plan.md), [CI/CD Integration Guide](../architecture/ci-cd-integration.md) |

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Design Principles](#2-design-principles)
3. [Current Architecture — Why It Blocks CI/CD](#3-current-architecture--why-it-blocks-cicd)
4. [Target Architecture — Two-Phase Pipeline](#4-target-architecture--two-phase-pipeline)
5. [Phase 1: Build Interception (In-Band)](#5-phase-1-build-interception-in-band)
6. [Phase 2: SPDX Generation (Out-of-Band)](#6-phase-2-spdx-generation-out-of-band)
7. [CI/CD Integration Patterns](#7-cicd-integration-patterns)
8. [Artifact Contract Between Phases](#8-artifact-contract-between-phases)
9. [Artifact Provenance and Integrity](#9-artifact-provenance-and-integrity)
10. [Implementation Plan](#10-implementation-plan)
11. [Performance Budget](#11-performance-budget)
12. [Risk Register](#12-risk-register)
13. [Success Criteria](#13-success-criteria)

**Appendices**

- [Appendix A: Corona Integration — Centralized SBOM Construction](#appendix-a-corona-integration--centralized-sbom-construction)

---

<a id="1-problem-statement"></a>

## 1. Problem Statement

### The Fundamental Requirement

The sidecar solution MUST minimize its impact on the CI/CD pipeline
execution time. Build interception is inherently in-band (it wraps the
build), but SPDX generation is not. Today, both run in a single
sequential process, forcing the CI/CD pipeline to wait for the entire
SPDX generation to complete before proceeding.

### Measured Impact (spring-boot, sidecar mode, 2026-05-05)

| Phase | Duration | Blocking? |
|-------|----------|-----------|
| Gradle build (instrumented) | ~3 min | **Yes** — must wrap the build |
| `bomsh_create_bom_java.py` (treedb) | ~2 min | **Yes** — runs during/after build |
| Gradle `dependencies` (dep:tree) | ~10 min | No — post-build metadata |
| `dpkg-query` per class file (metadata) | ~5 min | No — post-build enrichment |
| SPDX JSON generation | ~1 min | No — pure computation |
| HTML visualization | ~30 sec | No — pure computation |
| **Total** | **~23 min** | **Only ~5 min is in-band** |

**78% of the pipeline time is out-of-band work that does not need to
block the CI/CD pipeline.** The build itself takes ~3 minutes. The
OmniBOR sidecar adds ~2 minutes of in-band overhead (treedb generation).
The remaining ~18 minutes (dep:tree resolution, metadata collection,
SPDX generation, visualization) can run asynchronously after the build
completes.

### Why This Matters

In a CI/CD pipeline, the build step is on the critical path. Every
minute added to the build step delays:

- Developer feedback loops (PR checks)
- Deployment velocity (time-to-production)
- CI/CD runner costs (compute time is billed)

Enterprise teams evaluate OmniBOR adoption on this metric: **how much
does it slow down my pipeline?** The answer must be "minutes, not tens
of minutes" — and ideally "seconds of overhead on the build step itself."

---

<a id="2-design-principles"></a>

## 2. Design Principles

### P1. Minimize Build Step Impact

The CI/CD build step should see **<5% overhead** from OmniBOR. Only
the absolute minimum work runs in-band with the build:

- Wrapping compiler/build tool invocations (wrappers, `-toolexec`, etc.)
- Capturing the raw logfile / treedb

Everything else is out-of-band.

### P2. Artifact-Based Decoupling

Phase 1 (build) and Phase 2 (SPDX) communicate exclusively through
well-defined artifacts (treedb, raw logfile, `gradle_deps.json`). There
is no in-process coupling. Phase 2 can run in a different container, on
a different machine, or minutes/hours later.

### P3. CI/CD Pipeline as First-Class Citizen

The architecture is designed around CI/CD pipeline stages, not around
a single monolithic script. Each phase maps to a CI/CD stage that can
run independently, with its own resource allocation, timeout, and
retry policy.

### P4. Backward Compatibility

The existing single-phase `analyze.py` continues to work unchanged.
The two-phase mode is opt-in via `--phase build` / `--phase spdx` flags.
Teams that prefer the simpler single-phase approach can keep using it.

### P5. Fail-Safe for Phase 2 — Ephemeral Build Environments

CI/CD build environments are **ephemeral**. The container, VM, or
pod that ran the build is typically destroyed seconds after the
build step completes. Any artifact not actively pushed to durable
storage is lost forever.

This means Phase 1 MUST, as its **final act before exiting**:

1. Push all build metadata (treedb, raw logfile, manifest) to
   durable storage (artifact registry, S3, OCI registry)
2. Compute and record cryptographic digests (SHA-256) and OmniBOR
   GitOIDs for every artifact, including the output binaries
3. Sign the manifest (or publish a signed attestation) that binds
   the build metadata to the specific binaries produced

If Phase 2 fails, it can be retried from the durably stored artifacts
at any time — minutes, hours, or days later. Phase 2 failure MUST NOT
be treated as a build failure. But Phase 1 failure to persist artifacts
IS a build failure, because the metadata is irrecoverable.

### P6. Artifact Provenance — Binding SBOMs to Binaries

The SPDX documents generated in Phase 2 must be **cryptographically
bound** to the exact binaries produced in Phase 1. Without this
binding, an SBOM is just a document with no proof it describes the
artifact it claims to describe.

OmniBOR GitOIDs provide the foundation: each binary has a
content-addressable identifier (SHA-256 gitoid) that is immutable
and verifiable. The Phase 1 manifest records these GitOIDs. The
Phase 2 SPDX documents reference them via `ExternalRef` entries.
A consumer can verify the chain:

1. Compute the GitOID of the binary they received
2. Look up the SPDX document that references that GitOID
3. Verify the SPDX document's signature traces back to the
   Phase 1 manifest
4. Verify the Phase 1 manifest was signed by the CI/CD system

This is the **SLSA provenance** model applied to SBOM generation.

---

<a id="3-current-architecture--why-it-blocks-cicd"></a>

## 3. Current Architecture — Why It Blocks CI/CD

### Current Pipeline (Single-Phase, Sequential)

The current `analyze.py` runs everything in one process, sequentially:

| Step | What | Duration | In-Band? |
|------|------|----------|----------|
| 1. Clone | `git clone --branch <tag>` | 10–60s | Build prep |
| 2. Clean | `./gradlew clean` | 5–30s | Build prep |
| 3. Build | `./gradlew build` (with wrappers or strace) | 1–10 min | **Yes** |
| 4. Treedb | `bomsh_create_bom_java.py` | 1–5 min | **Yes** |
| 5. Dep:tree | `./gradlew dependencies` per submodule | 5–15 min | No |
| 6. Metadata | `dpkg-query --search` per file | 2–10 min | No |
| 7. SPDX | `JavaSpdxGenerator.generate()` | 30–120s | No |
| 8. Validate | JSON schema + semantic checks | 5–10s | No |
| 9. Visualize | D3.js HTML generation | 10–30s | No |
| 10. Docs | Build log, runtime metrics | 5s | No |

**Steps 5–10 do not require the build environment.** They only need
the artifacts produced by steps 3–4 (treedb, built JARs, source tree).
Yet they all run sequentially in the same process, blocking the CI/CD
pipeline.

### Current CI/CD Integration (from `ci-cd-integration.md`)

The current documented CI/CD integration runs the entire pipeline in
the Build stage:

```yaml
# CURRENT: Everything runs in the Build stage
stages:
  - name: Build
    run: |
      docker run --rm \
        -v $WORKSPACE:/workspace/repos/spring-boot \
        -v $WORKSPACE/output:/workspace/output \
        omnibor-env:sidecar \
        python3 /workspace/app/analyze.py \
          --repo spring-boot --skip-clone --mode sidecar
      # ^^^ This blocks for ~23 minutes
```

The Build stage is blocked for the entire 23 minutes. Downstream stages
(Test, Deploy) cannot start until SPDX generation completes.

---

<a id="4-target-architecture--two-phase-pipeline"></a>

## 4. Target Architecture — Two-Phase Pipeline

### Split the Pipeline at the Artifact Boundary

The natural split point is between step 4 (treedb) and step 5
(dep:tree). Steps 1–4 require the build environment. Steps 5–10
only need the treedb artifact and the source/build tree.

| Phase | Steps | Runs | Blocks CI/CD? |
|-------|-------|------|---------------|
| **Phase 1: Build** | Clone, Clean, Build, Treedb | In the CI/CD build stage | **Yes** — but only ~5 min |
| **Phase 2: SPDX** | Dep:tree, Metadata, SPDX, Validate, Visualize, Docs | As a parallel/downstream CI stage | **No** |

### How Phase 2 Runs in Parallel with CI/CD

The key insight is that CI/CD systems natively support **parallel
stages** and **downstream triggers**. Phase 2 can run as:

1. **A parallel CI stage** — starts immediately after Phase 1 completes,
   runs concurrently with Test/Deploy stages
2. **A downstream/triggered pipeline** — a separate pipeline triggered
   by Phase 1 completion, running on a different runner
3. **An async job** — dispatched to a queue (SQS, Kafka, GitHub Actions
   workflow dispatch) that processes SPDX generation asynchronously
4. **A scheduled batch** — a nightly/periodic job that generates SBOMs
   from all treedb artifacts produced during the day

All four patterns are industry-standard CI/CD practices. The architecture
supports all of them because Phase 1 and Phase 2 communicate only
through artifacts.

### Industry Precedent

<table>
<tr>
  <th style="min-width:120px">Tool</th>
  <th>Build-Time</th>
  <th>Post-Build</th>
  <th>Pattern</th>
</tr>
<tr>
  <td><strong>Coverity</strong></td>
  <td><code>cov-build make</code> captures intermediate representation</td>
  <td><code>cov-analyze</code> runs separately, often on a dedicated server</td>
  <td>Two-phase: capture + analyze</td>
</tr>
<tr>
  <td><strong>SonarQube</strong></td>
  <td>Build produces compilation database</td>
  <td><code>sonar-scanner</code> runs as a separate CI stage</td>
  <td>Parallel stage</td>
</tr>
<tr>
  <td><strong>Snyk</strong></td>
  <td>Build produces lockfiles/manifests</td>
  <td><code>snyk test</code> runs post-build in parallel with deploy</td>
  <td>Parallel stage</td>
</tr>
<tr>
  <td><strong>FOSSA</strong></td>
  <td>Build produces dependency manifests</td>
  <td>FOSSA CLI analyzes asynchronously</td>
  <td>Async analysis</td>
</tr>
<tr>
  <td><strong>Black Duck</strong></td>
  <td><code>detect</code> scans during build</td>
  <td>Full analysis runs on Black Duck server</td>
  <td>Server-side async</td>
</tr>
<tr>
  <td><strong>CycloneDX</strong></td>
  <td>Maven plugin runs during build</td>
  <td>SBOM enrichment/validation runs post-build</td>
  <td>Two-phase</td>
</tr>
</table>

The two-phase pattern (capture in-band, analyze out-of-band) is the
**industry standard** for security and compliance tooling in CI/CD.
Every major tool in this space uses it.

### Per-Language Phase Split

All four supported languages follow the same two-phase pattern, but
differ in their interception mechanism and artifact types:

<table>
<tr>
  <th style="min-width:100px">Language</th>
  <th>Phase 1 (In-Band)</th>
  <th>Interception Mechanism</th>
  <th>Phase 1 Artifact</th>
  <th>Phase 2 (Out-of-Band)</th>
</tr>
<tr>
  <td><strong>C/C++</strong></td>
  <td>apt validation, instrumented build, <code>bomsh_create_bom.py</code></td>
  <td><strong>Standalone:</strong> bomtrace3 (ptrace)<br><strong>Sidecar:</strong> <code>CC=</code>/<code>CXX=</code>/<code>AR=</code>/<code>LD=</code> wrappers</td>
  <td><code>bomsh_hook_raw_logfile</code> &rarr; treedb</td>
  <td>SPDX generation, metadata collection, per-binary ADG SPDX, validation, binary collection</td>
</tr>
<tr>
  <td><strong>Rust</strong></td>
  <td>Instrumented build, <code>bomsh_create_bom.py</code></td>
  <td><strong>Standalone:</strong> bomtrace2 (ptrace)<br><strong>Sidecar:</strong> <code>RUSTC_WRAPPER</code> env var</td>
  <td><code>bomsh_hook_raw_logfile</code> &rarr; treedb</td>
  <td>SPDX generation, metadata collection, per-binary ADG SPDX, validation, binary collection</td>
</tr>
<tr>
  <td><strong>Go</strong></td>
  <td>Instrumented build (<code>-a</code> flag), <code>bomsh_create_bom.py</code></td>
  <td><strong>Standalone:</strong> bomtrace2 (ptrace, Go-specific conf)<br><strong>Sidecar:</strong> <code>-toolexec</code> flag</td>
  <td><code>bomsh_hook_raw_logfile</code> &rarr; treedb</td>
  <td>SPDX generation, metadata collection, per-binary ADG SPDX, validation, binary collection</td>
</tr>
<tr>
  <td><strong>Java</strong></td>
  <td>Instrumented build, treedb generation</td>
  <td><strong>Standalone:</strong> strace + <code>bomsh_create_bom_java.py</code><br><strong>Sidecar:</strong> Maven/Gradle dep:tree (no strace)</td>
  <td><code>bomsh_omnibor_treedb</code> + strace log</td>
  <td>Dep:tree resolution, metadata collection, SPDX generation, per-JAR ADG SPDX (analyzed + build), validation, binary collection</td>
</tr>
</table>

**Common Phase 2 steps across all languages:**

- `pipeline.spdx_gen.generate()` &mdash; SPDX JSON from treedb/ADG
- `pipeline.metadata_collector.collect()` &mdash; OS package metadata via `dpkg-query`/`rpm`
- `pipeline.adg_spdx.generate()` &mdash; per-binary ADG SPDX documents
- `pipeline.spdx_validator.validate()` &mdash; JSON schema + semantic checks
- `pipeline.binary_collector.collect()` &mdash; archive output binaries
- `pipeline.docs.write_build_doc()` / `write_runtime_doc()` &mdash; build logs and metrics

The split point is identical for all languages: after the instrumented
build and treedb/raw logfile generation (Step 4 in each runner), all
remaining steps (5a&ndash;7 in each runner) are out-of-band.

---

<a id="5-phase-1-build-interception-in-band"></a>

## 5. Phase 1: Build Interception (In-Band)

### What Runs (Per Language)

| Language | Build Step | ADG/Treedb Step | Output Artifact |
|:---------|:----------|:----------------|:----------------|
| **C/C++** | `bomtrace3 make` or `CC=wrapper make` | `bomsh_create_bom.py -r <raw_logfile> -b <bom_dir>` | `bomsh_hook_raw_logfile`, treedb |
| **Rust** | `bomtrace2 cargo build --release` or `RUSTC_WRAPPER=wrapper cargo build --release` | `bomsh_create_bom.py -r <raw_logfile> -b <bom_dir>` | `bomsh_hook_raw_logfile`, treedb |
| **Go** | `bomtrace2 go build -a` or `go build -a -toolexec=wrapper` | `bomsh_create_bom.py -r <raw_logfile> -b <bom_dir>` | `bomsh_hook_raw_logfile`, treedb |
| **Java** | `strace <opts> ./gradlew build` or `./gradlew build` (sidecar) | `bomsh_create_bom_java.py -r <repo_dir> -j <treedb>` | `bomsh_omnibor_treedb`, strace log |

### What Does NOT Run (All Languages)

- No SPDX JSON generation (`spdx_gen.generate()` / `spdx_gen.generate_java()`)
- No metadata collection (`metadata_collector.collect()`)
- No per-binary ADG SPDX (`adg_spdx.generate()` / `generate_java_adg_spdx()`)
- No SPDX validation (`spdx_validator.validate()`)
- No binary collection (`binary_collector.collect()`)
- No build/runtime documentation (`docs.write_build_doc()` / `write_runtime_doc()`)
- No HTML visualization
- No dep:tree resolution (Java: `./gradlew dependencies`)
- No `dpkg-query --search` (metadata enrichment)

### CLI Interface

```bash
# Phase 1: Build interception only (any language)
python3 analyze.py --repo curl --phase build                        # C/C++
python3 analyze.py --repo oxipng --phase build                      # Rust
python3 analyze.py --repo fzf --phase build                         # Go
python3 analyze.py --repo spring-boot --mode sidecar --phase build  # Java

# Output (C/C++ example):
#   output/omnibor/c-cpp/curl/<ts>/metadata/bomsh/bomsh_hook_raw_logfile
#   output/omnibor/c-cpp/curl/<ts>/phase1_manifest.json

# Output (Java example):
#   output/omnibor/java/spring-boot/<ts>/metadata/bomsh/bomsh_omnibor_treedb
#   output/omnibor/java/spring-boot/<ts>/phase1_manifest.json
```

### Phase 1 Manifest

Phase 1 produces a manifest file that Phase 2 consumes. This is the
contract between the two phases:

```json
{
  "phase": 1,
  "version": "1.0",
  "repo_name": "spring-boot",
  "language": "java",
  "mode": "sidecar",
  "timestamp": "2026-05-05_2302",
  "build_success": true,
  "artifacts": {
    "treedb": "output/omnibor/java/spring-boot/2026-05-05_2302/metadata/bomsh/bomsh_omnibor_treedb",
    "repo_dir": "/workspace/repos/spring-boot",
    "build_dir": "/workspace/repos/spring-boot/spring-boot-project/spring-boot/build"
  },
  "config_snapshot": {
    "output_binaries": ["spring-boot-project/spring-boot/build/libs/spring-boot-*.jar"],
    "build_steps": ["./gradlew :spring-boot-project:spring-boot:build -x test -x check --no-daemon -q"]
  },
  "durations": {
    "build_sec": 180.5,
    "treedb_sec": 120.3
  }
}
```

### Performance Target

**Phase 1 adds <5% wall-clock time to the build step.** For a 3-minute
Gradle build, the treedb generation adds ~2 minutes. This is the
**only** OmniBOR overhead visible to the CI/CD pipeline.

For C/C++ with compiler wrappers, the overhead is even lower: the
wrapper runs inline with each compiler invocation (3–5% per-file
overhead) and the treedb is generated from the raw logfile in seconds.

---

<a id="6-phase-2-spdx-generation-out-of-band"></a>

## 6. Phase 2: SPDX Generation (Out-of-Band)

### What Runs (Per Language)

**Common steps (all languages):**

| Step | Input | Output |
|------|-------|--------|
| Metadata | Treedb + OS package DB | Component metadata (package names, versions) |
| SPDX | Treedb + metadata | `*_analyzed.spdx.json`, `*_build.spdx.json` |
| ADG SPDX | Treedb + per-binary file mapping | Per-binary `*_analyzed.spdx.json`, `*_build.spdx.json` |
| Validate | SPDX JSON files | Validation report |
| Binaries | Build output directory | Archived binaries in `output/binaries/` |
| Docs | All of the above | `build.md`, `runtime.md` |

**Language-specific Phase 2 steps:**

| Language | Extra Steps | Why |
|----------|------------|-----|
| **C/C++** | `apt-cache` dependency validation (pre-build, but can be cached) | Validates system library availability |
| **Rust** | Cargo registry path resolution for crate detection | Maps `.rlib` files to crate names via `/.cargo/registry/src/` paths |
| **Go** | `vendor/modules.txt` parsing for module version extraction | Maps Go packages to modules; requires `go mod vendor` pre-build step |
| **Java** | Gradle/Maven dep:tree resolution (`./gradlew dependencies` per submodule) | Extracts the full dependency graph not captured by treedb alone |

### CLI Interface

```bash
# Phase 2: SPDX generation from Phase 1 artifacts (any language)
python3 analyze.py --repo curl --phase spdx \
  --manifest output/omnibor/c-cpp/curl/<ts>/phase1_manifest.json        # C/C++

python3 analyze.py --repo oxipng --phase spdx \
  --manifest output/omnibor/rust/oxipng/<ts>/phase1_manifest.json       # Rust

python3 analyze.py --repo fzf --phase spdx \
  --manifest output/omnibor/go/fzf/<ts>/phase1_manifest.json            # Go

python3 analyze.py --repo spring-boot --mode sidecar --phase spdx \
  --manifest output/omnibor/java/spring-boot/<ts>/phase1_manifest.json  # Java
```

### Where Phase 2 Runs

Phase 2 has no dependency on the build environment. It needs:

- Python 3.11+ with the `app/` package
- The treedb/raw logfile artifact from Phase 1
- Access to the source tree (for Go module parsing, Java dep:tree)
- The OS package database (for `dpkg-query`/`rpm` metadata collection)

**Language-specific Phase 2 requirements:**

| Language | Extra Requirement | Why |
|----------|------------------|-----|
| **C/C++** | None beyond common | SPDX from treedb + system lib metadata |
| **Rust** | Source tree with `Cargo.lock` | Crate version extraction |
| **Go** | Source tree with `vendor/modules.txt` | Module version extraction |
| **Java** | JDK + Gradle/Maven in container | Dep:tree resolution requires build toolchain |

**Note:** Java is the only language where Phase 2 requires build tools
(JDK, Gradle, Maven) because dep:tree resolution invokes the build
system. For C/C++, Rust, and Go, Phase 2 needs only Python and the
OS package database.

This means Phase 2 can run:

| Location | Requirements | Use Case |
|----------|-------------|----------|
| **Same container** | Already has everything | Simplest &mdash; run as next CI stage |
| **Sidecar container** | Mount the Phase 1 artifacts volume | Standard sidecar pattern |
| **Dedicated SBOM server** | Pull artifacts from CI artifact store | Enterprise: centralized SBOM generation |
| **Developer laptop** | rsync the treedb locally | Debugging, ad-hoc analysis |
| **Scheduled CI job** | Artifacts stored in S3/Artifactory | Batch processing |

### Performance Characteristics (Per Language)

Phase 2 is **CPU-bound and parallelizable**. The expensive operations
vary by language:

| Language | Expensive Phase 2 Operation | Current Duration | Optimization |
|----------|----------------------------|-----------------|-------------|
| **C/C++** | `dpkg-query --search` per system lib | 30s&ndash;2 min | Batch queries, reverse index |
| **Rust** | SPDX generation from treedb | 30s&ndash;1 min | Already fast |
| **Go** | SPDX generation + `vendor/modules.txt` parsing | 30s&ndash;1 min | Already fast |
| **Java** | `./gradlew dependencies` per submodule | 5&ndash;15 min | Parallel submodule resolution |
| **Java** | `dpkg-query --search` per `.class` file | 2&ndash;10 min | Batch queries, reverse index |
| **All** | SPDX JSON emission | 30s&ndash;2 min | Already fast |
| **All** | HTML visualization | 10&ndash;30s | Already fast |

**Key optimization for Phase 2:** The `dpkg-query` bottleneck (affects
C/C++ and Java most heavily) can be eliminated by batch-querying all
files at once instead of one-at-a-time:

```bash
# Current (slow): one query per file
dpkg-query --search /path/to/file1.class
dpkg-query --search /path/to/file2.class
# ... repeated 113,524 times for Java

# Optimized (fast): build reverse index once
dpkg -L <package> | sort > /tmp/dpkg_index.txt
# Or: batch query
dpkg -S /path/to/file1.class /path/to/file2.class ...
```

**Estimated Phase 2 durations after optimization:**

| Language | Current Phase 2 | Optimized Phase 2 |
|----------|----------------|-------------------|
| **C/C++** | ~5 min | ~2 min |
| **Rust** | ~3 min | ~2 min |
| **Go** | ~3 min | ~2 min |
| **Java** | ~18 min | ~5&ndash;8 min |

---

<a id="7-cicd-integration-patterns"></a>

## 7. CI/CD Integration Patterns

### Pattern A: Parallel Stage (Recommended)

The simplest and most common pattern. Phase 2 runs as a CI stage that
starts after the Build stage, in parallel with Test and Deploy stages.

**GitHub Actions:**

```yaml
name: Build with SBOM

on: [push]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build with OmniBOR interception (Phase 1)
        run: |
          docker run --rm \
            -v ${{ github.workspace }}:/workspace/repos/spring-boot \
            -v ${{ github.workspace }}/omnibor-output:/workspace/output \
            omnibor-env:sidecar \
            python3 /workspace/app/analyze.py \
              --repo spring-boot --skip-clone --mode sidecar --phase build

      - name: Upload treedb artifact
        uses: actions/upload-artifact@v4
        with:
          name: omnibor-treedb
          path: omnibor-output/omnibor/

  test:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Run tests
        run: make test
      # Test starts immediately after build — NOT blocked by SPDX

  generate-sbom:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Download treedb artifact
        uses: actions/download-artifact@v4
        with:
          name: omnibor-treedb
          path: omnibor-output/omnibor/

      - name: Generate SPDX (Phase 2)
        run: |
          docker run --rm \
            -v ${{ github.workspace }}:/workspace/repos/spring-boot \
            -v ${{ github.workspace }}/omnibor-output:/workspace/output \
            omnibor-env:sidecar \
            python3 /workspace/app/analyze.py \
              --repo spring-boot --mode sidecar --phase spdx \
              --manifest /workspace/output/omnibor/java/spring-boot/*/phase1_manifest.json

      - name: Upload SPDX artifacts
        uses: actions/upload-artifact@v4
        with:
          name: spdx-sbom
          path: omnibor-output/spdx/

  deploy:
    needs: [build, test]
    runs-on: ubuntu-latest
    steps:
      - name: Deploy
        run: deploy.sh
      # Deploy does NOT wait for SBOM generation
```

**Pipeline timeline:**

| Time | build | test | generate-sbom | deploy |
|------|-------|------|---------------|--------|
| 0:00 | Building... | | | |
| 3:00 | Treedb... | | | |
| 5:00 | Done | Starting... | Starting... | |
| 8:00 | | Testing... | dep:tree... | |
| 12:00 | | Done | Metadata... | Starting... |
| 15:00 | | | SPDX gen... | Deploying... |
| 18:00 | | | Done | Done |

**Build + Deploy critical path: 15 min** (down from 23 min).
SBOM is available 3 minutes after deploy, not blocking it.

**Jenkins:**

```groovy
pipeline {
    agent { label 'linux' }

    stages {
        stage('Build') {
            steps {
                sh """
                    docker run --rm \\
                        -v \${WORKSPACE}:/workspace/repos/spring-boot \\
                        -v \${WORKSPACE}/omnibor-output:/workspace/output \\
                        omnibor-env:sidecar \\
                        python3 /workspace/app/analyze.py \\
                            --repo spring-boot --skip-clone \\
                            --mode sidecar --phase build
                """
            }
        }

        stage('Parallel') {
            parallel {
                stage('Test') {
                    steps {
                        sh 'make test'
                    }
                }
                stage('Generate SBOM') {
                    steps {
                        sh """
                            docker run --rm \\
                                -v \${WORKSPACE}:/workspace/repos/spring-boot \\
                                -v \${WORKSPACE}/omnibor-output:/workspace/output \\
                                omnibor-env:sidecar \\
                                python3 /workspace/app/analyze.py \\
                                    --repo spring-boot --mode sidecar \\
                                    --phase spdx \\
                                    --manifest /workspace/output/omnibor/java/spring-boot/*/phase1_manifest.json
                        """
                    }
                }
            }
        }

        stage('Deploy') {
            steps {
                deploy()
            }
        }

        stage('Publish SBOM') {
            steps {
                archiveArtifacts artifacts: 'omnibor-output/spdx/**/*.spdx.json'
            }
        }
    }
}
```

### Pattern B: Downstream Pipeline (Enterprise)

For enterprise teams that want centralized SBOM management:

```yaml
# Pipeline A: Team's build pipeline (unchanged except Phase 1)
build:
  script:
    - make build
    - omnibor-intercept --phase build  # Adds ~2 min
    - upload-artifact omnibor-treedb

# Pipeline B: Central SBOM pipeline (triggered by Pipeline A)
generate-sbom:
  trigger:
    project: security/sbom-generator
    branch: main
  variables:
    TREEDB_ARTIFACT: $CI_PROJECT_DIR/omnibor-treedb
```

### Pattern C: Async Queue (Large Scale)

For organizations generating SBOMs across hundreds of repos:

```yaml
# Build pipeline: fast, minimal overhead
build:
  script:
    - make build
    - omnibor-intercept --phase build
    - aws sqs send-message --queue-url $SBOM_QUEUE \
        --message-body '{"repo": "spring-boot", "treedb": "s3://..."}'

# SBOM worker: processes queue, generates SBOMs
# Runs on dedicated infrastructure, not CI runners
```

### Pattern D: Single-Phase (Backward Compatible)

The existing behavior. No `--phase` flag means run everything:

```bash
# EXISTING: unchanged behavior, runs everything sequentially
python3 analyze.py --repo spring-boot --mode sidecar
```

This is the default for teams that prefer simplicity over speed, or
for evaluation/demo use.

---

<a id="8-artifact-contract-between-phases"></a>

## 8. Artifact Contract Between Phases

### Phase 1 Output (Phase 2 Input)

**Common artifacts (all languages):**

| Artifact | Format | Required | Purpose |
|----------|--------|----------|----------|
| `phase1_manifest.json` | JSON (our schema) | **Yes** | Metadata for Phase 2 discovery |
| Source tree | Directory | **Yes** | Dep:tree, module parsing, crate detection |

**Per-language artifacts:**

| Language | Primary Artifact | Format | Purpose |
|----------|-----------------|--------|----------|
| **C/C++** | `bomsh_hook_raw_logfile` &rarr; treedb | bomsh binary format | Source-to-object file mapping |
| **Rust** | `bomsh_hook_raw_logfile` &rarr; treedb | bomsh binary format | Source-to-rlib/binary mapping |
| **Go** | `bomsh_hook_raw_logfile` &rarr; treedb | bomsh binary format | Source-to-binary mapping |
| **Java** | `bomsh_omnibor_treedb` + strace log | JSON (bomsh format) | JAR-to-class-to-source mapping |
| **All** | Built binaries | ELF, JAR, etc. | Binary artifact references for SPDX |

### Phase 1 Manifest Schema (v1.0)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["phase", "version", "repo_name", "language", "timestamp",
               "build_success", "artifacts"],
  "properties": {
    "phase": {"const": 1},
    "version": {"type": "string", "pattern": "^\\d+\\.\\d+$"},
    "repo_name": {"type": "string"},
    "language": {"enum": ["c-cpp", "java", "go", "rust", "python"]},
    "mode": {"enum": ["standalone", "sidecar"]},
    "timestamp": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}_\\d{4}$"},
    "build_success": {"type": "boolean"},
    "artifacts": {
      "type": "object",
      "required": ["treedb"],
      "properties": {
        "treedb": {"type": "string"},
        "treedb_sha256": {"type": "string"},
        "repo_dir": {"type": "string"},
        "build_dir": {"type": "string"},
        "raw_logfile": {"type": "string"},
        "raw_logfile_sha256": {"type": "string"},
        "storage_uri": {"type": "string",
          "description": "Durable storage location (s3://, oci://, etc.)"}
      }
    },
    "binaries": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["path", "sha256", "gitoid"],
        "properties": {
          "path": {"type": "string"},
          "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
          "gitoid": {"type": "string",
            "description": "OmniBOR GitOID (gitoid:blob:sha256:<hex>)"}
        }
      },
      "description": "Every binary/JAR produced by the build, with digests"
    },
    "config_snapshot": {
      "type": "object",
      "properties": {
        "output_binaries": {"type": "array", "items": {"type": "string"}},
        "build_steps": {"type": "array", "items": {"type": "string"}}
      }
    },
    "durations": {
      "type": "object",
      "properties": {
        "build_sec": {"type": "number"},
        "treedb_sec": {"type": "number"}
      }
    }
  }
}
```

### Artifact Storage — Durable, Not Ephemeral

CI/CD build environments are ephemeral. Phase 1 artifacts MUST be
pushed to durable storage before the build container is destroyed.
This is a **hard requirement**, not optional.

**Phase 1 must persist (at minimum):**

| Artifact | Why |
|----------|-----|
| `phase1_manifest.json` | Phase 2 discovery; provenance record |
| Treedb / raw logfile | Phase 2 input; cannot be regenerated after build |
| Output binaries (or their SHA-256 digests) | Provenance binding |
| Source commit SHA | Reproducibility |

**Storage options (durable):**

| CI System | Durable Storage | Retention |
|-----------|----------------|----------|
| GitHub Actions | `actions/upload-artifact@v4` | 90 days default; configurable |
| Jenkins | `archiveArtifacts` &rarr; Jenkins controller storage | Tied to build record retention |
| GitLab CI | `artifacts:` with `expire_in:` | Configurable per-job |
| Generic | S3/GCS bucket, Artifactory, OCI registry | Policy-driven |
| Enterprise | Dedicated SBOM artifact store (e.g., Dependency-Track, GUAC) | Permanent |

**Critical: the CI artifact store is the bridge between Phase 1 and
Phase 2.** If the artifact store loses the treedb, the SBOM cannot
be generated for that build. Organizations should treat OmniBOR
build metadata with the same retention policy as their binaries.

The `phase1_manifest.json` contains relative paths. Phase 2 resolves
them relative to the output directory root. When artifacts are stored
in a remote registry, the `storage_uri` field in the manifest provides
the retrieval location.

---

<a id="9-artifact-provenance-and-integrity"></a>

## 9. Artifact Provenance and Integrity

### The Problem: Ephemeral Builds, Permanent SBOMs

In a typical CI/CD pipeline:

1. A build container starts, compiles code, produces binaries
2. The container is destroyed (seconds after the build step)
3. The binaries are pushed to an artifact registry
4. The build metadata (logs, intermediate files) is **gone**

If Phase 2 (SPDX generation) runs after the build container is
destroyed, it needs the treedb and build metadata that no longer
exist. And when the SPDX is eventually generated, there must be a
**cryptographic proof** that it describes the specific binaries from
that specific build — not some other build, not a tampered artifact.

### Solution: GitOID-Based Provenance Chain

OmniBOR already provides the cryptographic foundation: **GitOIDs**
are content-addressable identifiers (SHA-256 over the artifact
content). Every binary produced by the build has a unique GitOID
that changes if even one byte changes.

The provenance chain works as follows:

<table>
<tr>
  <th>Step</th>
  <th>Actor</th>
  <th>Action</th>
  <th>Produces</th>
</tr>
<tr>
  <td>1</td>
  <td>Phase 1 (build)</td>
  <td>Compute SHA-256 and GitOID of every output binary</td>
  <td><code>binaries[]</code> in manifest</td>
</tr>
<tr>
  <td>2</td>
  <td>Phase 1 (build)</td>
  <td>Compute SHA-256 of treedb and raw logfile</td>
  <td><code>artifacts.*_sha256</code> in manifest</td>
</tr>
<tr>
  <td>3</td>
  <td>Phase 1 (build)</td>
  <td>Sign <code>phase1_manifest.json</code> (or produce SLSA provenance attestation)</td>
  <td>Signed manifest or <code>.jsonl</code> attestation</td>
</tr>
<tr>
  <td>4</td>
  <td>Phase 1 (build)</td>
  <td>Push manifest + treedb + binaries to durable storage</td>
  <td>Artifacts in registry</td>
</tr>
<tr>
  <td>5</td>
  <td>Phase 2 (SPDX)</td>
  <td>Download manifest + treedb from storage</td>
  <td>Local copies</td>
</tr>
<tr>
  <td>6</td>
  <td>Phase 2 (SPDX)</td>
  <td>Verify treedb SHA-256 matches manifest</td>
  <td>Integrity check</td>
</tr>
<tr>
  <td>7</td>
  <td>Phase 2 (SPDX)</td>
  <td>Generate SPDX with <code>ExternalRef</code> entries containing binary GitOIDs</td>
  <td>SPDX documents</td>
</tr>
<tr>
  <td>8</td>
  <td>Phase 2 (SPDX)</td>
  <td>Sign SPDX documents (or produce attestation)</td>
  <td>Signed SBOMs</td>
</tr>
<tr>
  <td>9</td>
  <td>Consumer</td>
  <td>Verify binary GitOID matches SPDX <code>ExternalRef</code></td>
  <td>Trust chain</td>
</tr>
</table>

### SPDX ExternalRef Binding

The generated SPDX documents bind to the build artifacts via
`externalRefs` on the root package:

```json
{
  "SPDXID": "SPDXRef-Package-curl-8.11.1",
  "externalRefs": [
    {
      "referenceCategory": "PERSISTENT_ID",
      "referenceType": "gitoid",
      "referenceLocator": "gitoid:blob:sha256:a1b2c3d4..."
    },
    {
      "referenceCategory": "SECURITY",
      "referenceType": "cpe23Type",
      "referenceLocator": "cpe:2.3:a:haxx:curl:8.11.1:*:*:*:*:*:*:*"
    }
  ]
}
```

A consumer who receives `curl` version 8.11.1 can:

1. Compute `gitoid:blob:sha256:<hash>` of the received binary
2. Query the SBOM store for an SPDX document with a matching
   `ExternalRef` GitOID
3. Verify the SPDX document's provenance chain back to the CI/CD
   build that produced it

### Industry Standards Alignment

| Standard | How We Align |
|----------|-------------|
| **SLSA v1.0** | Phase 1 manifest is a build provenance attestation; signed by CI/CD identity |
| **in-toto** | Phase 1 = build step attestation; Phase 2 = SBOM generation step attestation |
| **Sigstore/cosign** | Keyless signing of manifests and SPDX documents using CI/CD OIDC identity |
| **OmniBOR** | GitOIDs as the content-addressable identifier binding SBOMs to binaries |
| **SPDX 2.3** | `ExternalRef` with `gitoid` reference type for artifact binding |
| **CISA SBOM Sharing** | SBOMs must be "associated with" specific software versions — GitOID provides this |

### Signing Strategy

**Recommended: Sigstore keyless signing with CI/CD OIDC identity.**

In GitHub Actions, the workflow identity (repo, workflow, ref) is
available as an OIDC token. Sigstore/cosign uses this token to sign
artifacts without managing long-lived keys:

```yaml
# Phase 1: sign the manifest
- name: Sign Phase 1 manifest
  uses: sigstore/cosign-installer@v3
- run: cosign sign-blob --yes phase1_manifest.json

# Phase 2: sign the SPDX documents
- name: Sign SPDX
  run: cosign sign-blob --yes curl_analyzed.spdx.json
```

For Jenkins/GitLab, use cosign with a KMS-backed key or a
project-specific signing key stored in the CI secret store.

**Minimum viable (no signing infrastructure):** SHA-256 digests in
the manifest provide tamper detection. The manifest itself is stored
in the CI artifact store, which has its own access controls. This is
sufficient for internal use but not for external distribution.

### Retention Policy

Build metadata (treedb, manifest) must be retained **at least as long
as the binaries they describe**. If a binary is distributed to
customers for 5 years, the SBOM (and the build metadata that produced
it) must be retrievable for 5 years.

| Artifact | Minimum Retention | Rationale |
|----------|------------------|-----------|
| Output binaries | Matches release lifecycle | Distribution to customers |
| `phase1_manifest.json` | Same as binaries | Provenance record |
| Treedb / raw logfile | Same as binaries | Enables SBOM regeneration |
| Signed SPDX documents | Same as binaries | Compliance, vulnerability response |
| Source commit SHA | Permanent (in git) | Reproducibility |

---

<a id="10-implementation-plan"></a>

## 10. Implementation Plan

### Implementation Week 1: Infrastructure + All-Language Phase Split

| Work Item | File(s) | Effort | Description |
|:----------|:--------|:------:|:------------|
| `--phase` CLI argument | `runners.py` | 0.5 days | Add `--phase {build,spdx}` to argparse; route to phase-specific runners |
| Phase 1 manifest writer | `pipeline/manifest.py` (new) | 1 day | Generate `phase1_manifest.json` with language-aware artifact paths |
| Phase 2 manifest reader | `pipeline/manifest.py` | 0.5 days | Read and validate `phase1_manifest.json`; resolve per-language artifacts |
| All-language phase split | `lang_runners.py` | 2 days | Extract phase1/phase2 functions for C/C++, Rust, Go, Java |
| Default mode (no `--phase`) | `runners.py` | 0.5 days | Run both phases sequentially (backward compat); calls phase1 then phase2 |

### Implementation Week 2: Tests + Backward Compatibility

| Work Item | File(s) | Effort | Description |
|:----------|:--------|:------:|:------------|
| Unit tests: manifest | `tests/test_manifest.py` | 1 day | Manifest schema validation, per-language artifact path generation |
| Unit tests: phase routing | `tests/test_runners.py` | 0.5 days | `--phase build`, `--phase spdx`, no `--phase` dispatch correctly for all 4 languages |
| Integration tests | `tests/` | 1.5 days | End-to-end: Phase 1 then Phase 2 produces identical output to single-phase for each language (curl, oxipng, fzf, spring-boot) |
| Golden file regression | `tests/` | 0.5 days | Verify two-phase output matches golden files byte-for-byte |
| Docs step split | `runners.py` | 0.5 days | Move `write_build_doc()` / `write_runtime_doc()` into Phase 2 for all languages |

### Implementation Week 3: Phase 2 Optimizations

| Work Item | File(s) | Effort | Description |
|:----------|:--------|:------:|:------------|
| Batch `dpkg-query` | `metadata_collector.py` | 2 days | Replace per-file queries with batch reverse index (benefits C/C++ and Java) |
| Parallel Gradle dep:tree | `gradle_dep_tree_parser.py` | 1 day | Run submodule dep:tree in parallel (Java-specific) |
| CI/CD examples | `docs/architecture/ci-cd-integration.md` | 1 day | Update with Phase 1/2 patterns for all languages |
| Performance benchmarks | `tests/benchmarks/` | 1 day | Measure Phase 1 vs. total overhead per language |

### Total Effort: ~3 weeks

The phase split is implemented for **all four languages simultaneously**
in Week 1 because they share the same structural pattern (steps 4 vs.
steps 5&ndash;7 in each runner). The per-language phase1/phase2
functions are straightforward extractions from the existing monolithic
runners.

This work is **independent of** and **complementary to** the existing
sidecar implementation design. It can be implemented before, during,
or after the per-language wrapper work.

---

<a id="11-performance-budget"></a>

## 11. Performance Budget

### Phase 1 (In-Band) Target Per Language

| Language | Build Overhead | Treedb Overhead | Total Phase 1 Overhead |
|----------|---------------|-----------------|----------------------|
| **Java (sidecar)** | 0% (unmodified build) | ~60% of build time | **<2x build time** |
| **C/C++ (wrapper)** | 3–5% per compilation unit | Seconds (raw logfile already written) | **<5% total** |
| **Go (-toolexec)** | 10–15% per compilation unit | Seconds (raw logfile already written) | **<15% total** |
| **Rust (RUSTC_WRAPPER)** | 5–10% per compilation unit | Seconds (raw logfile already written) | **<10% total** |

### Phase 2 (Out-of-Band) Target Per Language

| Language | Current Phase 2 | Optimized Phase 2 | Key Optimization |
|----------|----------------|-------------------|------------------|
| **C/C++** | ~5 min | ~2 min | Batch `dpkg-query` |
| **Rust** | ~3 min | ~2 min | Already fast; minor metadata caching |
| **Go** | ~3 min | ~2 min | Already fast; `modules.txt` parsing is instant |
| **Java** | ~18 min | ~5&ndash;8 min | Parallel dep:tree + batch `dpkg-query` |

### CI/CD Pipeline Impact (Per Language)

| Language | Current Total | Phase 1 (In-Band) | Phase 2 (Out-of-Band) | Deploy Blocked? |
|----------|--------------|-------------------|-----------------------|-----------------|
| **C/C++ (curl)** | ~8 min | ~3 min | ~2 min (parallel) | **No** |
| **Rust (oxipng)** | ~5 min | ~2 min | ~2 min (parallel) | **No** |
| **Go (fzf)** | ~6 min | ~3 min | ~2 min (parallel) | **No** |
| **Java (spring-boot)** | ~23 min | ~5 min | ~5&ndash;8 min (parallel) | **No** |

---

<a id="12-risk-register"></a>

## 12. Risk Register

<table>
<tr>
  <th style="min-width:30px">#</th>
  <th>Risk</th>
  <th>Impact</th>
  <th style="min-width:100px">Likelihood</th>
  <th>Mitigation</th>
</tr>
<tr>
  <td>R1</td>
  <td>Phase 2 needs access to source tree for dep:tree</td>
  <td>Artifact storage grows if source must be preserved</td>
  <td>Medium</td>
  <td>dep:tree resolution can run in same workspace; for remote Phase 2, archive only the build metadata (treedb + <code>build.gradle</code>) not the full source</td>
</tr>
<tr>
  <td>R2</td>
  <td>Phase 1 manifest format changes break Phase 2</td>
  <td>Phase 2 cannot read old manifests</td>
  <td>Low</td>
  <td>Version field in manifest; Phase 2 validates version before processing</td>
</tr>
<tr>
  <td>R3</td>
  <td>Teams forget to run Phase 2</td>
  <td>SBOMs never generated</td>
  <td>Medium</td>
  <td>Default mode (no <code>--phase</code>) runs both; Phase 2 can be a required CI gate for compliance teams</td>
</tr>
<tr>
  <td>R4</td>
  <td>Dep:tree resolution requires JDK/Gradle</td>
  <td>Phase 2 container must include build tools for Java</td>
  <td>Medium</td>
  <td>For Java, dep:tree runs in the same container that has JDK. For C/C++/Go/Rust, Phase 2 needs only Python</td>
</tr>
<tr>
  <td>R5</td>
  <td>Treedb artifact size for large projects</td>
  <td>Network transfer time for large treedb files</td>
  <td>Low</td>
  <td>spring-boot treedb is 74 MB; compress for CI artifact upload</td>
</tr>
<tr>
  <td>R6</td>
  <td>Build container destroyed before artifact push completes</td>
  <td>Treedb lost; SBOM cannot be generated for that build</td>
  <td><strong>High</strong></td>
  <td>Phase 1 artifact push is the <strong>last step</strong> before exit; fail the build if push fails; use CI-native artifact upload which runs in the runner, not the container</td>
</tr>
<tr>
  <td>R7</td>
  <td>Artifact store retention shorter than binary lifecycle</td>
  <td>SBOM cannot be regenerated after retention expires</td>
  <td>Medium</td>
  <td>Document minimum retention policy; default to &ldquo;same as binary retention&rdquo;; alert on expiring artifacts</td>
</tr>
<tr>
  <td>R8</td>
  <td>GitOID mismatch between Phase 1 manifest and actual binary</td>
  <td>SBOM references wrong artifact; provenance chain broken</td>
  <td>Low</td>
  <td>Phase 2 verifies SHA-256 of treedb before processing; SPDX generation computes GitOID from actual binary, not from manifest</td>
</tr>
<tr>
  <td>R9</td>
  <td>No signing infrastructure available</td>
  <td>Manifest and SPDX documents are unsigned; tamper-detectable but not tamper-proof</td>
  <td>Medium</td>
  <td>SHA-256 digests provide minimum viable integrity; Sigstore/cosign is zero-infrastructure (keyless); document signing as a graduated adoption path</td>
</tr>
</table>

---

<a id="13-success-criteria"></a>

## 13. Success Criteria

### Functional (All Languages)

- [ ] `analyze.py --repo curl --phase build` produces raw logfile/treedb + manifest (C/C++)
- [ ] `analyze.py --repo oxipng --phase build` produces raw logfile/treedb + manifest (Rust)
- [ ] `analyze.py --repo fzf --phase build` produces raw logfile/treedb + manifest (Go)
- [ ] `analyze.py --repo spring-boot --phase build` produces treedb + manifest (Java)
- [ ] `analyze.py --phase spdx --manifest <path>` produces identical SPDX output to single-phase mode for **each language**
- [ ] `analyze.py` (no `--phase`) produces identical output to current behavior for **each language**
- [ ] Phase 2 can run in a separate container from Phase 1
- [ ] Phase 2 failure does not affect Phase 1 exit code

### Artifact Provenance

- [ ] Phase 1 manifest includes SHA-256 and GitOID for every output binary
- [ ] Phase 1 manifest includes SHA-256 for treedb and raw logfile
- [ ] Phase 2 verifies treedb SHA-256 before processing
- [ ] Generated SPDX documents include `ExternalRef` with binary GitOIDs
- [ ] Phase 1 artifacts are pushed to durable storage before build container exits
- [ ] Phase 2 can retrieve artifacts from durable storage and produce valid SPDX
- [ ] (Stretch) Phase 1 manifest is signed with Sigstore/cosign
- [ ] (Stretch) SPDX documents are signed with Sigstore/cosign

### Performance (Per Language)

- [ ] Phase 1 adds **<5%** overhead for C/C++ (bomtrace3 or CC= wrappers)
- [ ] Phase 1 adds **<10%** overhead for Rust (bomtrace2 or RUSTC_WRAPPER)
- [ ] Phase 1 adds **<15%** overhead for Go (bomtrace2 or -toolexec)
- [ ] Phase 1 completes in **<2x** the uninstrumented build time for Java
- [ ] Phase 2 completes in **<3 minutes** for C/C++, Rust, Go
- [ ] Phase 2 completes in **<8 minutes** for Java (with batch metadata optimization)

### CI/CD

- [ ] GitHub Actions example runs with Phase 1 and Phase 2 as separate jobs
- [ ] Jenkins example runs with Phase 2 in a parallel stage
- [ ] Deploy stage is NOT blocked by Phase 2 for **any language**

### Backward Compatibility

- [ ] All existing tests pass with no changes (all 4 languages)
- [ ] Single-phase mode produces byte-identical output to current behavior for each language
- [ ] Golden file regression tests pass in both single-phase and two-phase modes for each language

---

*Document created: 2026-05-05 13:55 HST*
*Updated: 2026-05-05 14:15 HST — expanded all sections to cover C/C++, Rust, Go, Java (was Java-only)*
*Updated: 2026-05-05 14:20 HST — added Section 9 (Artifact Provenance and Integrity): ephemeral build environments, GitOID-based provenance chain, SPDX ExternalRef binding, SLSA/Sigstore alignment, retention policy, durable storage requirements*
*Updated: 2026-05-05 14:35 HST — added Appendix A (Corona centralized SBOM construction)*

---

<a id="appendix-a-corona-integration--centralized-sbom-construction"></a>

## Appendix A: Corona Integration — Centralized SBOM Construction

### Background: Corona as the Enterprise SBOM System

Corona is the centralized SBOM management system that:

- Ingests SBOMs from multiple sources (Black Duck binary scan,
  Syft manifest scan, proprietary tools, SPDX 2.3 imports)
- Manages the full SBOM lifecycle within a **Product → Release →
  Image** (PRI) data model
- Tracks vulnerabilities against ingested SBOMs
- Provides a single pane of glass for SBOM compliance across
  products

### Current State: Syft SBOMs Uploaded to Corona

There may be CI/CD pipelines that generate Syft-based SPDX SBOMs and upload them to Corona out-of-band:

| Step | Where | What |
|------|-------|------|
| 1. Build | CI/CD pipeline | Normal build step |
| 2. Syft scan | CI/CD pipeline (post-build) | `syft <image> -o spdx-json` |
| 3. Upload | CI/CD pipeline | Push SPDX JSON to Corona S3 bucket |
| 4. Ingest | Corona agent/daemon | Reads from S3, processes, stores in PRI model |

The OmniBOR build-intercepted SBOM can follow the **exact same upload path**, with Corona handling Phase 2 construction instead of the CI/CD pipeline.

### Proposed Architecture: Corona as Phase 2 Executor

Instead of running Phase 2 (SPDX generation) in the CI/CD pipeline
or in a parallel CI stage, delegate Phase 2 entirely to Corona.
The CI/CD pipeline only runs Phase 1 (build interception) and
uploads the raw build metadata to Corona.

| Step | Where | What | Duration |
|------|-------|------|----------|
| 1. Build + intercept | CI/CD pipeline | Phase 1: instrumented build + treedb | ~3–5 min |
| 2. Upload metadata | CI/CD pipeline | Push `phase1_manifest.json` + treedb to Corona S3 bucket | Seconds |
| 3. CI/CD continues | CI/CD pipeline | Test, deploy — **zero SBOM delay** | — |
| 4. Ingest metadata | Corona agent | New daemon reads Phase 1 artifacts from S3 | Async |
| 5. Construct SPDX | Corona agent | Runs Phase 2: dep:tree, metadata, SPDX generation | ~5–18 min |
| 6. Store SBOM | Corona | Stores SPDX at correct Product/Release/Image location | Immediate |

**Key advantage:** The CI/CD pipeline sees **zero SPDX generation
overhead**. Phase 1 adds only the build interception time (~3–5 min
for Java, <5% for C/C++). The upload to S3 takes seconds. Everything
else happens asynchronously in Corona.

### Corona Data Model Mapping

The `phase1_manifest.json` must include enough information for the
Corona agent to place the resulting SBOM in the correct PRI location:

| Manifest Field | Corona PRI Field | Source |
|---------------|-----------------|--------|
| `repo_name` | Image name (or derived from it) | `config.yaml` |
| `config_snapshot.product` (new) | **Product** | CI/CD environment or `config.yaml` |
| `config_snapshot.release` (new) | **Release** | Git tag, branch, or CI/CD variable |
| `config_snapshot.image_id` (new) | **Image** (SBOM) | Build ID, commit SHA, or GitOID |
| `language` | Metadata/classification | `config.yaml` |
| `binaries[].gitoid` | Artifact binding | Computed by Phase 1 |

The Corona agent uses these fields to:

1. Create or look up the Product in Corona
2. Create or look up the Release under that Product
3. Create a new Image (SBOM) under that Release
4. Populate the Image with the generated SPDX content

### Corona Agent: New OmniBOR Daemon

A new daemon/agent within Corona handles the OmniBOR-specific
processing:

| Responsibility | Detail |
|---------------|--------|
| **S3 bucket watch** | Monitors the designated S3 prefix for new `phase1_manifest.json` uploads |
| **Artifact retrieval** | Downloads treedb, raw logfile, and source metadata from S3 |
| **Integrity verification** | Verifies SHA-256 digests of treedb against manifest |
| **SPDX construction** | Runs the `omnibor-analysis` Phase 2 pipeline (Python) |
| **PRI placement** | Stores the resulting SPDX at the correct Product/Release/Image |
| **Status reporting** | Updates a status record so CI/CD can optionally poll for completion |
| **Error handling** | Logs failures, retries transient errors, alerts on persistent failures |

The daemon runs the same `analyze.py --phase spdx --manifest <path>`
command that the CI/CD integration would use. The code is identical;
only the execution context differs (Corona server vs. CI runner).

### Advantages Over CI/CD-Based Phase 2

<table>
<tr>
  <th>Aspect</th>
  <th>CI/CD Phase 2</th>
  <th>Corona Phase 2</th>
</tr>
<tr>
  <td><strong>CI/CD pipeline impact</strong></td>
  <td>Phase 2 runs as parallel CI stage (still uses CI compute)</td>
  <td><strong>Zero</strong> &mdash; only S3 upload (seconds)</td>
</tr>
<tr>
  <td><strong>Compute cost</strong></td>
  <td>Billed CI runner minutes</td>
  <td>Corona server (already provisioned)</td>
</tr>
<tr>
  <td><strong>SBOM storage</strong></td>
  <td>CI artifacts (ephemeral, retention-limited)</td>
  <td>Corona (permanent, PRI-organized)</td>
</tr>
<tr>
  <td><strong>Vulnerability tracking</strong></td>
  <td>Separate step to import SPDX into Corona</td>
  <td><strong>Automatic</strong> &mdash; SBOM is already in Corona</td>
</tr>
<tr>
  <td><strong>Multi-source correlation</strong></td>
  <td>Manual: correlate OmniBOR SBOM with Black Duck scan</td>
  <td><strong>Native</strong> &mdash; Corona has both SBOMs for the same Image</td>
</tr>
<tr>
  <td><strong>Retry on failure</strong></td>
  <td>Must re-run CI job</td>
  <td>Corona agent retries autonomously</td>
</tr>
<tr>
  <td><strong>Visibility</strong></td>
  <td>Scattered across CI logs</td>
  <td>Centralized in Corona dashboard</td>
</tr>
</table>

### Multi-Source SBOM Correlation in Corona

The most compelling advantage is that Corona already holds Black Duck
binary scan SBOMs for the same products. With OmniBOR build-intercepted
SBOMs stored alongside them in the same PRI location, Corona can:

1. **Compare** the OmniBOR SBOM (source-level, build-traced) against
   the Black Duck SBOM (binary-scanned) for the same Image
2. **Identify gaps** — components detected by one method but not the
   other
3. **Increase confidence** — components confirmed by both methods have
   higher assurance
4. **Automate vulnerability enrichment** — Corona's existing vuln
   matching runs automatically on newly ingested OmniBOR SBOMs

This is the `run-comparison` workflow that `omnibor-analysis` already
supports, but executed server-side in Corona rather than ad-hoc locally.

### Implementation Considerations

<table>
<tr>
  <th style="min-width:180px">Item</th>
  <th>Detail</th>
</tr>
<tr>
  <td><strong>S3 bucket structure</strong></td>
  <td><code>s3://corona-sbom-intake/omnibor/{product}/{release}/{build_id}/</code></td>
</tr>
<tr>
  <td><strong>Authentication</strong></td>
  <td>CI/CD uses existing AWS credentials; Corona agent uses IAM role</td>
</tr>
<tr>
  <td><strong>Manifest extensions</strong></td>
  <td>Add <code>product</code>, <code>release</code>, <code>image_id</code> fields to <code>phase1_manifest.json</code></td>
</tr>
<tr>
  <td><strong>Corona agent runtime</strong></td>
  <td>Python 3.11+, <code>omnibor-analysis</code> package installed; for Java repos, also needs JDK/Gradle</td>
</tr>
<tr>
  <td><strong>Source tree access</strong></td>
  <td>Corona agent needs the source tree for dep:tree (Java) and module parsing (Go, Rust). Options:<br>(a) CI uploads source tarball<br>(b) Corona agent does <code>git clone</code> at the pinned commit<br>(c) for non-Java, source tree is not needed if <code>vendor/modules.txt</code> and <code>Cargo.lock</code> are included in the upload</td>
</tr>
<tr>
  <td><strong>Status callback</strong></td>
  <td>Optional: Corona posts a status check back to the PR/commit so developers know when the SBOM is ready</td>
</tr>
<tr>
  <td><strong>Deduplication</strong></td>
  <td>Corona agent checks if an SBOM already exists for this Product/Release/Image before constructing a new one</td>
</tr>
</table>

### Graduated Adoption Path

<table>
<tr>
  <th style="min-width:80px">Stage</th>
  <th>What Changes</th>
  <th>Risk</th>
</tr>
<tr>
  <td><strong>Stage 1</strong></td>
  <td>CI/CD runs full pipeline (current). Manually upload SPDX to Corona.</td>
  <td>None &mdash; current state</td>
</tr>
<tr>
  <td><strong>Stage 2</strong></td>
  <td>CI/CD runs Phase 1 + Phase 2. Uploads finished SPDX to Corona S3. Corona agent ingests the pre-built SPDX.</td>
  <td>Low &mdash; Corona agent is a simple file mover</td>
</tr>
<tr>
  <td><strong>Stage 3</strong></td>
  <td>CI/CD runs Phase 1 only. Uploads raw metadata to Corona S3. Corona agent runs Phase 2 and constructs the SPDX.</td>
  <td>Medium &mdash; Corona agent needs <code>omnibor-analysis</code> runtime</td>
</tr>
<tr>
  <td><strong>Stage 4</strong></td>
  <td>Corona agent triggers Phase 1 on a dedicated build cluster (no CI/CD involvement for SBOM).</td>
  <td>High &mdash; requires separate build infrastructure</td>
</tr>
</table>

Stage 2 is the **lowest-risk starting point** — Corona already ingests
pre-built SBOMs from Syft. Adding OmniBOR SBOMs follows the same
path. Stage 3 is the target architecture where Corona owns the entire
Phase 2 lifecycle.

### Relationship to Main Architecture

This appendix describes **Pattern E** — an alternative to the four
CI/CD integration patterns in Section 7. It is not mutually exclusive;
teams can choose:

- **Patterns A–D** (Section 7) for standalone or self-hosted deployments
- **Pattern E** (this appendix) for enterprise deployments with Corona

The Phase 1 code, manifest schema, and artifact contract are
**identical** regardless of which pattern is used. Only the Phase 2
execution context differs.
