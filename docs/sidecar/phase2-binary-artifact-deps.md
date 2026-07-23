# Phase 2 Binary Artifact Dependencies — Deep Dive

| | |
|---|---|
| **Date** | 2026-05-08 |
| **Authors** | Ted G. (architect), Cascade AI |
| **Status** | Research — informing Phase 1/Phase 2 implementation |
| **Prerequisite reading** | [Sidecar Async SPDX Architecture](../sidecar/sidecar-async-spdx-architecture.md) |

---

## Table of Contents

1. [Research Question](#1-research-question)
2. [Verdict](#2-verdict)
3. [Per-Step Binary Dependencies](#3-per-step-binary-dependencies)
4. [The Root Cause: Two Operations That Read Binaries](#4-the-root-cause-two-operations-that-read-binaries)
5. [Java Is the Exception](#5-java-is-the-exception)
6. [What Are the Binary Artifacts?](#6-what-are-the-binary-artifacts)
7. [Complete Phase 2 File I/O Audit](#7-complete-phase-2-file-io-audit)
8. [Solution: Corona Artifactory Receives Binaries + Metadata](#8-solution-corona-artifactory-receives-binaries--metadata)
9. [What Corona Needs from CI/CD](#9-what-corona-needs-from-cicd)
10. [Why This Works — No Phase 1 Changes Required](#10-why-this-works--no-phase-1-changes-required)
11. [Regarding bomsh_sbom.py (Step 5a)](#11-regarding-bomsh_sbompy-step-5a)
12. [Implementation Outline](#12-implementation-outline)
13. [Runtime Environment Requirements](#13-runtime-environment-requirements)

---

<a id="1-research-question"></a>

## 1. Research Question

Does SPDX generation (Phase 2) require the actual binary artifacts
produced by the build step (Phase 1) to complete? If so, which steps
need them, for which languages, and what is the proposal to make the
two-phase split work?

---

<a id="2-verdict"></a>

## 2. Verdict

**Yes — C/C++, Rust, and Go require binary artifacts for SPDX
generation. Java does NOT.**

The binary dependencies are the **final build output artifacts**
(executables, shared libraries, JARs) — not intermediate build
artifacts like `.o` object files, `.class` files, or `.a` static
archives. The intermediates are tracked in the bomsh treedb, but
Phase 2 steps only operate on the final outputs listed in
`config.yaml` under `output_binaries`.

---

<a id="3-per-step-binary-dependencies"></a>

## 3. Per-Step Binary Dependencies

Every Phase 2 step was traced across all four language pipelines:

| Phase 2 Step | Binary Required? | How It Uses the Binary | Languages Affected |
|---|---|---|---|
| `SpdxGenerator.generate()` (Step 5a) | **YES** | `bomsh_sbom.py -F <binary_paths>` — hashes binary, maps to OmniBOR docs | C/C++, Rust, Go |
| `MetadataCollector.collect()` (Step 5b) | **YES** | Runs `ldd <binary>` + `readelf -d <binary>` to discover dynamic libs | C/C++, Rust, Go |
| `AdgSpdxGenerator.generate()` (Step 5c) | **Indirectly YES** | Needs `dynamic_libs.json` (output of `ldd`/`readelf` above); also globs `output_binaries` paths | C/C++, Rust, Go |
| `generate_java_adg_spdx()` (Step 5c) | **PATH ONLY** | Globs JAR paths to match treedb entries — checks `exists()` but doesn't read content | Java |
| `JavaSpdxGenerator.generate()` | **NO** | Uses dep:tree + treedb; never reads JAR content | Java |
| `BinaryCollector.collect()` (Step 7) | **YES** | Copies binaries to `output/binaries/` for preservation | All |

---

<a id="4-the-root-cause-two-operations-that-read-binaries"></a>

## 4. The Root Cause: Two Operations That Read Binaries

### 4.1. `ldd` + `readelf` (dynamic library discovery)

In `app/collect_dynamic_libs.py`:

```python
ldd_out = subprocess.check_output(["ldd", binary_path], text=True)
readelf_out = subprocess.check_output(["readelf", "-d", binary_path], text=True)
```

These are Linux tools that **must execute on the actual ELF binary**
to discover dynamic library dependencies (direct NEEDED + transitive).
This produces `dynamic_libs.json` which is consumed by
`AdgSpdxGenerator`.

### 4.2. `bomsh_sbom.py -F <files>` (initial SPDX from ADG)

In `app/pipeline/spdx_generator.py`:

```python
rc = self.runner.run(
    f"{sbom_script} -b {bom_dir} -F {files_arg} "
    f"-O {spdx_dir} -s spdx-json --force_insert",
    ...
)
```

This bomsh script reads the binary to map its content hash to OmniBOR
documents for the initial SPDX.

---

<a id="5-java-is-the-exception"></a>

## 5. Java Is the Exception

Java's `generate_java_adg_spdx()` only needs JAR **paths** (for
treedb key lookup), never reads JAR content. The SPDX dependency content
comes from the treedb + the **Phase 1 dependency capture**
(`maven_deps.json` / `gradle_deps.json`), read via
`app/spdx/dep_capture_reader.py`.

> **Superseded (`tedg-dev/omnibor-analysis#194`):** an earlier version of
> this doc (and `async-spdx-architecture.md`) stated Java Phase 2 re-runs
> `mvn dependency:tree` / `./gradlew dependencies` and therefore requires
> JDK/Gradle/Maven. As built, Java Phase 2 consumes the Phase 1 capture and
> needs **no build tools and no source tree** — like C/C++, it needs only
> Python.

The key contrast this doc draws still holds: unlike C/C++/Rust/Go, Java
Phase 2 does **not** need the actual binary files — and it no longer needs
build tools either.

---

<a id="6-what-are-the-binary-artifacts"></a>

## 6. What Are the Binary Artifacts?

### 6.1. Final Build Outputs, NOT Intermediates

Every `output_binaries` entry in `config.yaml` is a **final
deliverable**:

| Language | Examples | Type |
|---|---|---|
| **C/C++** | `src/.libs/curl`, `src/redis-server`, `nmap`, `ffmpeg` | Final executables |
| **C/C++** | `lib/.libs/libcurl.so`, `libavcodec/libavcodec.so` | Final shared libraries (project output — these *are* the product) |
| **Rust** | `target/release/oxipng`, `target/release/dura` | Final release binaries |
| **Go** | `fzf`, `lazygit`, `croc` | Final static binaries |
| **Java** | `**/target/*.jar`, `**/build/libs/*.jar` | Final packaged JARs |

### 6.2. What They Are NOT

Intermediate build artifacts — `.o` object files, `.class` files,
`.a` static archives, `.rlib` Rust intermediates — are **not** in
`output_binaries`. Those intermediates are tracked in the bomsh treedb
(that's how OmniBOR traces source→object→binary provenance), but the
Phase 2 steps that require binary files only operate on the final
outputs.

### 6.3. Why Only Finals Matter

- **`ldd <binary>`** — only meaningful on final ELF executables/shared
  libraries. You can't `ldd` a `.o` file; it has no dynamic section.
- **`readelf -d <binary>`** — reads the `NEEDED` entries in the
  dynamic section. Only final linked binaries have this.
- **`bomsh_sbom.py -F <files>`** — hashes the final artifacts and
  maps them to OmniBOR documents to produce SPDX.
- **Java JAR glob** — the final packaged JARs, not intermediate
  `.class` files.

### 6.4. Clarification on `.so` Files

The `.so` files in `output_binaries` (e.g., `libcurl.so`,
`libavcodec.so`) are **the project's own output shared libraries** —
they're final deliverables, not system dependencies. The *system*
shared libraries (like `libssl.so`, `libz.so`) that these link against
are discovered dynamically by `ldd`/`readelf` during Phase 2 — those
system libs are NOT in `output_binaries` and don't need to be
persisted by Phase 1.

---

<a id="7-complete-phase-2-file-io-audit"></a>

## 7. Complete Phase 2 File I/O Audit

Every `read_text()`, `open()`, `subprocess.check_output()`,
`exists()`, and `glob()` call in the Phase 2 code path was traced
across all four language pipelines. This section documents every file
Phase 2 reads from disk, organized by category.

### 7.1. Intermediate Build Artifacts — NONE Read

No intermediate build artifact is ever opened or read by Phase 2:

| Artifact Type | Status | Evidence |
|---|---|---|
| **`.o` object files** | NOT read | `AdgParser.parse()` classifies them as `build_intermediate` from treedb JSON. `AdgSpdxGenerator` only passes `classified["project_source"]` to the emitter (`generator.py:152–156`). The `.o` files on disk are never opened. |
| **`.class` files** | NOT read | `AdgParser.get_jar_source_files()` traces JAR→class→source mappings entirely through the treedb JSON dict — it follows `hash_tree` SHA references within the same in-memory dict. Actual `.class` files on disk are never opened. |
| **`.a` static archives** | NOT read | Not referenced anywhere in Phase 2 code. |
| **`.rlib` Rust intermediates** | NOT read | Not referenced anywhere in Phase 2 code. |

### 7.2. Final Output Binaries — Read by Three Operations

| Operation | Code Location | What It Does |
|---|---|---|
| `ldd <binary>` | `collect_dynamic_libs.py:30–31` | Probes ELF dynamic section for shared lib dependencies |
| `readelf -d <binary>` | `collect_dynamic_libs.py:35–36` | Extracts direct NEEDED sonames |
| `bomsh_sbom.py -F <files>` | `spdx_generator.py:362–368` | Hashes binary, maps content hash to OmniBOR documents |
| `shutil.copy2()` | `binary_collector.py:111,132` | Copies final binaries to output directory |
| `jar_path.exists()` / glob | `lang_runners.py:369–374` | JAR path resolution (existence check only — no content read) |

### 7.3. OmniBOR Metadata Files — Read (JSON/text, produced by Phase 1)

| File | Reader | Format |
|---|---|---|
| `bomsh_omnibor_treedb` | `AdgParser.parse()`, `.get_jar_source_files()` | JSON: sha1 → {file_path, hash_tree, build_cmd} |
| `bomsh_omnibor_doc_mapping` | `AdgParser.load_doc_mapping()` | JSON: sha1 → omnibor_doc_id |
| `bomsh_hook_raw_logfile` | `AdgParser.load_raw_logfile_hashes()` | Text: `outfile: <sha1> path: <path>` per line |
| `strace_java_logfile` | `AdgParser.parse_strace_openat_log()` | Text: strace openat output (Java standalone only) |
| `maven_deps.json` / `gradle_deps.json` | `JavaSpdxGenerator` | JSON: dependency tree (Java sidecar only) |

### 7.4. Source Tree Files — Read (text, from git clone)

Phase 2 reads certain source tree files for version detection and
dependency classification. These are part of the git clone — they
exist before the build starts and are NOT build outputs.

| File | Reader | Language | Purpose |
|---|---|---|---|
| `go.mod` | `parse_go_mod()` | Go | Direct vs indirect dep classification |
| `vendor/modules.txt` | `parse_go_modules_txt()` | Go | Module version resolution |
| `/usr/local/go/VERSION` | `detect_go_version()` | Go | Go toolchain version (fallback) |
| `Cargo.lock` | `parse_cargo_lock()` | Rust | Crate version resolution |
| `Cargo.toml` | `parse_cargo_toml()` | Rust | Direct vs transitive dep classification |
| `VERSION`, `RELEASE`, `VERSION.txt` | `VendoredVersionDetector.detect()` | C/C++ | Vendored lib version detection |
| `configure.ac` | `VendoredVersionDetector.detect()` | C/C++ | AC_INIT version extraction |
| `CMakeLists.txt` | `VendoredVersionDetector.detect()` | C/C++ | project(VERSION) extraction |
| `meson.build` | `VendoredVersionDetector.detect()` | C/C++ | project(version:) extraction |
| `*.pc.in` | `VendoredVersionDetector.detect()` | C/C++ | Version: field extraction |
| `*.h` headers | `VendoredVersionDetector.detect()` | C/C++ | `#define VERSION` macro extraction |
| `Makefile`, `Makefile.in` | `VendoredVersionDetector.detect()` | C/C++ | VERSION = x.y.z variables |
| `package.json`, `Cargo.toml`, `pom.xml` | `VendoredVersionDetector.detect()` | Any | Structured version files |
| Root-level files + `include/*.h` + `src/*.h` | `_detect_repo_version()` in `collect_metadata.py` | All | Repo's own version detection |
| `pom.xml` / `build.gradle` | `generate_java_adg_spdx()` (dev/test live fallback only) | Java | **Not read in the enterprise path** — module resolution uses the Phase 1 capture (`dep_capture_reader.py`); these are read only in the co-located dev/test fallback |

### 7.5. System Environment Probes — Executed at Runtime

| Command / File | Code Location | Purpose |
|---|---|---|
| `dpkg-query --search` / `rpm -qf` / `apk info --who-owns` | `collect_metadata.py` via `PackageResolver` | Resolve system files to OS packages |
| `gcc --version` | `collect_metadata.py:195–198` | GCC version for SPDX metadata |
| `/etc/os-release` | `collect_metadata.py:180–190` | Distro identification |
| `ldd <binary>` | `collect_dynamic_libs.py:30–31` | Dynamic lib discovery (also reads binary — see 7.2) |

### 7.6. Audit Summary

**No intermediate build artifacts (`.o`, `.class`, `.a`, `.rlib`) are
required by any language for Phase 2 SPDX generation.** Phase 2 needs
exactly three categories of build-tree files:

1. **Final output binaries** — the same artifacts you would deploy
2. **Source tree** — the git clone (for lock files, version detection,
   module detection)
3. **OmniBOR metadata** — JSON/text files produced by Phase 1

Plus the runtime environment (system packages, `ldd`, `readelf`, etc.)
documented in Section 13.

---

<a id="8-solution-corona-artifactory-receives-binaries--metadata"></a>

## 8. Solution: Corona Artifactory Receives Binaries + Metadata

### 8.1. The Key Insight

The CI/CD pipeline already produces the final binaries as its primary
output — they are the whole point of the build. These binaries are
normally pushed to an artifact registry (Artifactory, Nexus, OCI
registry, S3) as part of the standard CI/CD deploy step.

The solution is straightforward: **the CI/CD pipeline uploads both
the final binaries AND the OmniBOR metadata to Corona's artifact
store.** Corona's Phase 2 agent then has everything it needs to run
the existing SPDX generation code **completely unchanged**.

### 8.2. No Phase 1 Code Changes Required

Because Corona receives the actual binaries alongside the OmniBOR
metadata, every Phase 2 step that depends on binary artifacts works
as-is:

| Phase 2 Step | Why It Works Unchanged |
|---|---|
| `ldd <binary>` + `readelf -d <binary>` | Binary is available locally in Corona's workspace after download from artifactory |
| `bomsh_sbom.py -F <binary_paths>` | Binary paths resolve to the downloaded artifacts |
| `AdgSpdxGenerator.generate()` | `dynamic_libs.json` is produced normally by the preceding `ldd`/`readelf` step |
| `generate_java_adg_spdx()` | JAR files are present; glob patterns match |
| `BinaryCollector.collect()` | Binaries are present for archival |

The existing `analyze.py --phase spdx` code path runs without
modification. The only new work is the **CI/CD upload step** — which
is a CI/CD pipeline configuration change, not an omnibor-analysis
code change.

### 8.3. CI/CD Upload Step

Phase 1 (the CI/CD build stage) adds one post-build step: upload
artifacts to Corona's S3 intake bucket. This is a CI/CD pipeline
configuration, not application code:

```yaml
# CI/CD pipeline — after build + treedb generation
- name: Upload to Corona
  run: |
    aws s3 sync \
      output/omnibor/<lang>/<repo>/<ts>/ \
      s3://corona-sbom-intake/omnibor/{product}/{release}/{build_id}/metadata/

    # Upload final binaries alongside metadata
    aws s3 sync \
      repos/<repo>/ \
      s3://corona-sbom-intake/omnibor/{product}/{release}/{build_id}/repo/ \
      --include "*.jar" --include "*.so" --include "*/curl" \
      --exclude ".git/*" --exclude "*.o" --exclude "*.class"
```

The Corona agent downloads these artifacts into its local workspace
and runs Phase 2 against them.

---

<a id="9-what-corona-needs-from-cicd"></a>

## 9. What Corona Needs from CI/CD

### 9.1. Required Artifacts

| Artifact | Source | Purpose in Phase 2 |
|---|---|---|
| **OmniBOR treedb** | `output/omnibor/<lang>/<repo>/<ts>/metadata/bomsh/bomsh_omnibor_treedb` | Source→object→binary provenance |
| **Raw logfile** (C/C++/Rust/Go) | `output/omnibor/<lang>/<repo>/<ts>/metadata/bomsh/bomsh_hook_raw_logfile` | OmniBOR doc mapping, ExternalRef injection |
| **Strace log** (Java standalone) | `output/omnibor/<lang>/<repo>/<ts>/metadata/bomsh/strace_java_logfile` | Build-time file access evidence |
| **Final binaries** | Per `output_binaries` in config | `ldd`/`readelf`, `bomsh_sbom.py`, binary collection |
| **Source tree** | Cloned repo directory | Dep:tree resolution (Java), `Cargo.lock` (Rust), `vendor/modules.txt` (Go), vendored version detection (C/C++) |
| **`phase1_manifest.json`** | Generated by Phase 1 | Discovery, provenance binding, config snapshot |

### 9.2. What Is NOT Needed

| Artifact | Why Not |
|---|---|
| Intermediate `.o` / `.class` / `.rlib` files | Tracked in treedb; never read directly by Phase 2 |
| Build tools (gcc, javac, rustc, go) | Not needed — except Java dep:tree which requires JDK + Maven/Gradle |
| System headers (`/usr/include/*`) | Tracked in treedb; metadata resolved via `dpkg-query`/`rpm` on the Phase 2 host |
| Build cache / temp files | Ephemeral; no value after treedb is generated |

### 9.3. Upload Size Estimates

| Language | Treedb + Metadata | Binaries | Source Tree | Total |
|---|---|---|---|---|
| **C/C++ (curl)** | ~2 MB | ~5 MB (curl + libcurl.so) | ~20 MB | ~27 MB |
| **C/C++ (ffmpeg)** | ~15 MB | ~50 MB (9 binaries) | ~100 MB | ~165 MB |
| **Rust (oxipng)** | ~1 MB | ~3 MB | ~10 MB | ~14 MB |
| **Go (fzf)** | ~1 MB | ~8 MB (static) | ~5 MB | ~14 MB |
| **Java (spring-boot)** | ~5 MB | ~15 MB (JARs) | ~200 MB | ~220 MB |

These are small by CI/CD artifact standards. The source tree is the
largest component; it can be compressed or Corona can `git clone`
directly from the VCS.

---

<a id="10-why-this-works--no-phase-1-changes-required"></a>

## 10. Why This Works — No Phase 1 Changes Required

The existing Phase 2 code assumes that the build output directory
still exists with binaries in it. In the current single-phase mode,
this is trivially true — everything runs in the same container.

In the Corona model, the same assumption holds because Corona
**reconstitutes the build workspace** from the uploaded artifacts:

```
Corona workspace (after download from artifactory):
  /workspace/repos/<repo>/          ← source tree + final binaries (in-tree)
  /workspace/output/omnibor/<lang>/<repo>/<ts>/
    metadata/bomsh/
      bomsh_omnibor_treedb           ← treedb
      bomsh_hook_raw_logfile         ← raw logfile
    phase1_manifest.json             ← manifest
```

The file paths resolve identically to the build environment. The
existing `analyze.py --phase spdx` code does not know or care that
it's running on a different machine — it just finds the files where
it expects them.

### 10.1. Path Resolution

The `phase1_manifest.json` records the paths used during the build.
Corona can either:

1. **Mirror the path layout** — mount artifacts at the same paths
   (e.g., `/workspace/repos/curl/src/.libs/curl`). Zero code changes.
2. **Remap paths** — future enhancement where Phase 2 reads paths
   from the manifest instead of from `config.yaml`. Requires minor
   code changes but decouples Phase 2 from the build filesystem.

Option 1 is the recommended starting point — it works today with
no code changes.

---

<a id="11-regarding-bomsh_sbompy-step-5a"></a>

## 11. Regarding bomsh_sbom.py (Step 5a)

With binaries available in Corona's workspace, `bomsh_sbom.py` works
as-is. However, for long-term consideration, this step is
**functionally redundant** — `AdgSpdxGenerator` (Step 5c) produces
strictly richer SPDX output:

- Per-binary SBOMs (vs. single combined SPDX)
- CISA Analyzed + Build taxonomy split
- Dynamic lib resolution with PURLs/CPEs
- Vendored dependency version detection
- OmniBOR ExternalRef injection

**Future consideration:** Deprecating `bomsh_sbom.py` from Phase 2
would simplify the pipeline with no loss of SPDX quality. This is
not required for the Corona integration — just a simplification
opportunity.

---

<a id="12-implementation-outline"></a>

## 12. Implementation Outline

```
Phase 1 — CI/CD Build Stage (in-band, ~3–5 min):
  1. Clone + build (instrumented)              ← existing, no changes
  2. Generate treedb / raw logfile              ← existing, no changes
  3. Upload to Corona artifactory:              ← NEW (CI/CD config only)
     - OmniBOR metadata (treedb, raw logfile, doc mapping)
     - Final binaries (output_binaries from config.yaml)
     - Source tree (or Corona clones from VCS)
     - phase1_manifest.json

Phase 2 — Corona Agent (out-of-band, ~2–18 min):
  1. Download artifacts from artifactory        ← Corona agent responsibility
  2. Reconstitute workspace layout              ← Corona agent responsibility
  3. collect_metadata.py (dpkg resolution)       ← existing, unchanged
  4. collect_dynamic_libs.py (ldd/readelf)       ← existing, unchanged (binaries available)
  5. SpdxGenerator.generate() (bomsh_sbom.py)    ← existing, unchanged (binaries available)
  6. AdgSpdxGenerator (analyzed + build SBOMs)   ← existing, unchanged
  7. JavaSpdxGenerator (dep:tree + treedb)       ← existing, unchanged
  8. Validate SPDX                               ← existing, unchanged
  9. HTML visualization                          ← existing, unchanged
  10. Build docs                                 ← existing, unchanged
```

### What This Achieves

- **Zero changes to Phase 1 application code** — the only new work
  is a CI/CD pipeline upload step (infrastructure config)
- **Zero changes to Phase 2 application code** — Corona runs the
  existing `analyze.py --phase spdx` unchanged
- **Binaries are already being pushed** to an artifact store as part
  of normal CI/CD — adding OmniBOR metadata is incremental
- **Phase 2 can run anywhere** Corona deploys an agent: different
  machine, different datacenter, cloud, on-prem
- **The existing single-phase mode (`analyze.py` without `--phase`)
  is unchanged** — backward compatible

---

<a id="13-runtime-environment-requirements"></a>

## 13. Runtime Environment Requirements

Corona's Phase 2 agent must run in a Linux environment with:

| Requirement | Why | Languages Affected |
|---|---|---|
| `ldd` | Dynamic library discovery | C/C++, Rust, Go |
| `readelf` | NEEDED entry extraction | C/C++, Rust, Go |
| `dpkg-query` or `rpm` or `apk` | OS package metadata resolution | All (native binaries) |
| **Compatible dynamic linker** | `ldd` must resolve the same `.so` paths as the build environment | C/C++, Rust, Go |
| Python 3.11+ | omnibor-analysis runtime | All |
| JDK + Maven/Gradle | `mvn dependency:tree` / `./gradlew dependencies` | Java only |

**Critical note on `ldd` compatibility:** `ldd` resolves shared
library paths using the host's dynamic linker (`ld-linux`). For
correct results, the Corona agent's container must have the **same
or equivalent system libraries** as the build container. The
recommended approach is to run the Corona agent in the same Docker
image (e.g., `omnibor-env:standalone`) as the build environment, or
a derivative that includes the same base packages.

If the Corona agent runs on a different OS or architecture than the
build, `ldd` output will differ or fail. This is inherent to dynamic
library resolution — it is host-dependent by design.
