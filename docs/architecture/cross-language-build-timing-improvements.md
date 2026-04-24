# Cross-Language Build Timing Improvements

| | |
|---|---|
| **Audience** | OmniBOR/bomsh maintainers, engineering teams evaluating multi-language SBOM pipelines |
| **Companion docs** | [Performance Optimization Proposal](omnibor-performance-optimization-proposal.md) (C/C++ focused), [Build-Time Overhead Deep-Dive](build-time-overhead-deep-dive.md), [Source Reference](omnibor-interception-source-reference.md) |
| **Last updated** | April 2026 |

---

## Table of Contents

1. [Context: C/C++ Strategies as a Baseline](#1-context)
2. [Current Interception Mechanisms by Language](#2-current-mechanisms)
3. [Java: Applying the C/C++ Strategies](#3-java)
4. [Go: Applying the C/C++ Strategies](#4-go)
5. [Rust: Applying the C/C++ Strategies](#5-rust)
6. [Python: Initial Design Considerations](#6-python)
7. [Cross-Language Strategy Matrix](#7-matrix)
8. [Recommended Priority by Language](#8-priority)

---

<a id="1-context"></a>

## 1. Context: C/C++ Strategies as a Baseline

The [Performance Optimization Proposal](omnibor-performance-optimization-proposal.md)
defines six strategies to reduce C/C++ build interception overhead from ~40% to
~7% (Path A) or ~2% (Path B). This document evaluates how each strategy applies
to Java, Go, Rust, and Python.

**C/C++ Path A strategies (incremental, cumulative):**

| # | Strategy | Target | C/C++ Impact |
|---|----------|--------|-------------|
| 1 | Out-of-Band Pre-Hash Cache | SHA-256 hashing | 11 percentage points reduction |
| 2 | seccomp-bpf Syscall Filter | ptrace context switches | 11 percentage points reduction |
| 3 | Async Tracer + Hash Worker Thread | Serialized hashing | 6 percentage points reduction |
| 4 | Deferred Post-Build Hashing | Build-time I/O | 5 percentage points reduction |

**C/C++ Path B strategies (replace ptrace entirely):**

| # | Strategy | Target | C/C++ Impact |
|---|----------|--------|-------------|
| 5 | Compiler Wrapper (CC=) | ptrace overhead | 35 percentage points reduction |
| 6 | eBPF-Based Tracing | ptrace overhead | 37 percentage points reduction |

**Supporting infrastructure:**

| Component | Purpose |
|-----------|---------|
| Git-Aware Hash Daemon (`bomsh_hashd`) | Always-hot cache that pre-computes hashes on git events |
| [Central Hash Store](cache-store-options.md#central-hash-store-integration) | Cross-team hash sharing and cold-cache pre-warming |

---

<a id="2-current-mechanisms"></a>

## 2. Current Interception Mechanisms by Language

Each language uses a different tracer and hook mechanism. This determines which
strategies are directly applicable, which need adaptation, and which are
irrelevant.

| Aspect | C/C++ | Java | Go | Rust |
|--------|-------|------|----|------|
| **Tracer** | `bomtrace3` (modified strace) | `strace` (stock) | `bomtrace2 -c bomtrace_go.conf` | `bomtrace2` (no conf file) |
| **Hook** | C code in `bomsh_hook.c` (in-process) | Post-build Python (`bomsh_create_bom_java.py`) | Python per-event (`bomsh_hook2.py`) | Python per-event (`bomsh_hook2.py`) |
| **Syscalls traced** | All (execve, open, read, write, stat, mmap, ...) | openat only (`--seccomp-bpf -e trace=openat`) | execve + openat (via `syscalls=openat` in conf) | execve only (no conf = default) |
| **Build method** | `builder.build()` — `bomtrace3 make -j$(nproc)` | `builder.build_java()` — `strace {opts} -o {log} mvn package` | `builder.build()` — `bomtrace2 -c ... go build -a` | `builder.build()` — `bomtrace2 cargo build --release` |
| **ADG generation** | `bomsh_create_bom.py -r {raw_logfile} -b {bom_dir}` | `bomsh_create_bom_java.py -r {repo_dir} -j {treedb}` (workspace scan) | `bomsh_create_bom.py -r {raw_logfile} -b {bom_dir}` | `bomsh_create_bom.py -r {raw_logfile} -b {bom_dir}` |
| **SPDX generation** | `bomsh_sbom.py` → `AdgSpdxGenerator` | `JavaSpdxGenerator` + `mvn dependency:tree` | `bomsh_sbom.py` → `AdgSpdxGenerator` | `bomsh_sbom.py` → `AdgSpdxGenerator` |
| **Process count** | High (1 per `.c` file) | Low (1 javac per module) | Medium (1 per package) | Medium (1 per crate) |
| **Cache bypass** | No (`make clean` optional) | No | Yes (`-a` mandatory) | No (release = clean build) |
| **Measured overhead** | 20–60% | 5–17% | 150–400% | 100–250% |
| **Diagram** | [c-cpp-build-interception.drawio](c-cpp-build-interception.drawio) | [java-build-interception.drawio](java-build-interception.drawio) | [go-build-interception.drawio](go-build-interception.drawio) | [rust-build-interception.drawio](rust-build-interception.drawio) |

**Source code references:**
- Config: `app/config.yaml` — tracer definitions at lines 295–315
- Builder: `app/pipeline/builder.py` — `build()` (lines 25–111, shared by C/C++/Go/Rust), `build_java()` (lines 113–198)
- Runners: `app/pipeline/runners.py` — `_run_c_cpp_pipeline()`, `_run_rust_pipeline()`, `_run_java_pipeline()`, `_run_go_pipeline()`
- Go config: `docker/bomtrace_go.conf` — `syscalls=openat` enables openat tracing
- No Rust-specific conf exists — Rust uses `bomtrace2` defaults (`execve` only)

**Key observations from source code:**

- **Java** is fundamentally different: it uses a dedicated `build_java()` method
  and a separate `bomsh_create_bom_java.py` that **scans the workspace** (given
  `-r {repo_dir}`) rather than parsing a raw logfile. The strace captures
  `openat` events to a log file, but the post-build script doesn't consume that
  log — it independently walks the filesystem. Java SPDX comes from
  `JavaSpdxGenerator` + `mvn dependency:tree`, not `bomsh_sbom.py`.

- **Rust** uses plain `bomtrace2` with no config file, meaning it traces only
  `execve` (not `openat`). File inputs are extracted from `rustc` command-line
  parsing in `bomsh_hook2.py` → `get_all_subfiles_in_rustc_cmdline()`.

- **Go** is the only language that adds `openat` tracing (via
  `bomtrace_go.conf syscalls=openat`) because Go's compile/link tools use
  `openat` for all file I/O and don't expose file lists in their `argv`.

- Java already has the lowest overhead because it uses the exact techniques
  Strategies 2 and 4 propose for C/C++: seccomp-bpf filtering and deferred
  post-build hashing. Go has the highest overhead because of the mandatory
  `-a` flag (cache bypass), which is a problem no C/C++ strategy addresses.

---

<a id="3-java"></a>

## 3. Java: Applying the C/C++ Strategies

**Current overhead: 5–17%** — already the lowest of all four languages.

**Current mechanism (from [java-build-interception.drawio](java-build-interception.drawio)
and `app/pipeline/builder.py` `build_java()`):**

```
strace -f -s99999 --seccomp-bpf -e trace=openat -qqq -o /tmp/strace_java_logfile \
    mvn package -DskipTests -q
                                                          (config.yaml line 313)
    ↓
bomsh_create_bom_java.py -r {repo_dir} -j {treedb_file}  (scans workspace, NOT strace log)
    ↓
JavaSpdxGenerator + mvn dependency:tree → SPDX 2.3 JSON  (app/spdx/java_generator.py)
```

**Important detail:** The strace wrapper captures `openat` events to a log file,
but `bomsh_create_bom_java.py` is passed `-r {repo_dir}` (the repo directory) —
not the strace log path. It scans the workspace independently to find
`.java` → `.class` → `.jar` relationships. This means the strace layer adds
overhead (~5-17%) but the post-build script doesn't directly consume its output.

### Strategy-by-Strategy Applicability

| C/C++ Strategy | Java Applicability | Notes |
|---------------|-------------------|-------|
| **1. Pre-Hash Cache** | **Applicable** — targets `bomsh_create_bom_java.py` post-build scan | The post-build script hashes every `.java`, `.class`, and `.jar` file by walking the workspace. A pre-hash cache eliminates redundant hashing of unchanged source files across builds. For dependency-check (2,000+ files), this could reduce post-build scan from ~20–30s to ~5s. |
| **2. seccomp-bpf** | **Already implemented** | Java's strace invocation already uses `--seccomp-bpf -e trace=openat`. This is the exact approach Strategy 2 proposes for C/C++. Java is the proof-of-concept that seccomp-bpf filtering works. |
| **3. Async Hash Worker** | **Low value** | Hashing in Java builds happens post-build (not during tracing), so there is no build-time hashing to parallelize. Could marginally speed up the post-build scan via multithreaded file hashing. |
| **4. Deferred Post-Build** | **Already implemented** | Java's entire approach is deferred post-build hashing. `bomsh_create_bom_java.py` runs after Maven/Gradle completes. This is the exact pattern Strategy 4 proposes for C/C++. |
| **5. Compiler Wrapper** | **Possible but low value** | Maven plugin or Gradle task could replace strace entirely by emitting file access logs from inside the build tool. Overhead is already <17%, so the ROI is minimal. |
| **6. eBPF** | **Overkill** | Overhead is already minimal. eBPF tracing would add complexity for negligible gain. |
| **Hash Daemon** | **Applicable** | The daemon could pre-compute hashes for `.java` source files before Maven starts. Most useful for large multi-module projects. |

### Java-Specific Optimization: Maven Dependency Plugin

The highest-impact Java-specific improvement is not from the C/C++ strategy
list at all. It is replacing strace with Maven's own dependency metadata:

```bash
mvn dependency:tree -DoutputType=dot -DoutputFile=deps.dot
```

This provides the complete dependency graph without any tracing overhead.
Combined with `bomsh_create_bom_java.py` for source-to-class mapping, this
reduces overhead from 5–17% to **<2%**.

**Source reference:** `bomsh_create_bom_java.py` post-build scan logic
([Section 6](omnibor-interception-source-reference.md#6-bomsh_create_bompy-logfile--adg--treedb))
and `omnibor-analysis/app/pipeline/runners.py` → `_run_java_pipeline()`.

### Gap: strace Data Is Collected but Not Consumed

From the source code, `build_java()` wraps Maven with strace and writes
`openat` events to `/tmp/strace_java_logfile`. But `bomsh_create_bom_java.py`
is invoked with `-r {repo_dir}` — it scans the workspace filesystem, not the
strace log. **We are paying 5–17% overhead to collect strace data and then
discarding it.**

This is an **accuracy gap**, not a performance opportunity. The strace log
contains runtime evidence of which files were actually accessed during the
build. This data could improve SBOM accuracy in several ways:

1. **Actual vs. present:** The workspace scan finds every `.java`/`.class`/
   `.jar` file in the repo — including test artifacts, IDE-generated files,
   and stale outputs from prior builds. The strace log shows only what
   Maven/javac actually opened during *this* build. Consuming it would let
   us distinguish "files that exist" from "files that participated in the
   build."

2. **Maven repository access:** When `javac` opens a JAR from
   `~/.m2/repository/` to resolve a class, that `openat` event links the
   build to that specific dependency artifact and version on disk. This
   provides file-level evidence that a dependency was actually used, not
   just declared in `pom.xml`.

3. **Plugin-injected dependencies:** Maven plugins (shade, assembly, etc.)
   may pull in files that aren't in the declared `pom.xml` dependency tree.
   These appear as `openat` events in the strace log but would be invisible
   to both the workspace scan and `mvn dependency:tree`.

4. **Build reproducibility evidence:** The strace log is a complete record
   of every file read/written during the build. It could be archived as
   provenance metadata alongside the SPDX SBOM for auditing.

**Resolution (implemented):**

This gap is now fixed. The pipeline consumes the strace `openat` log
following the same pattern as C/C++ (which uses `bomsh_create_bom.py -r
{raw_logfile}` to consume tracer output). Changes:

1. **`builder.py` `build_java()`** — archives the strace log to
   `metadata/bomsh/strace_java_logfile` alongside the treedb (mirrors
   how C/C++ archives the raw logfile).

2. **`parser.py` `AdgParser.parse_strace_openat_log()`** — new method
   that parses the archived strace log and returns the set of file paths
   that were successfully opened during the build (excludes `ENOENT`).

3. **`runners.py` `_generate_java_adg_spdx()`** — calls
   `parser.parse_strace_openat_log()` and passes the accessed-files set
   to `JavaSpdxGenerator`.

4. **`java_generator.py` `JavaSpdxGenerator`** — accepts
   `strace_accessed` parameter. When present, filters workspace-scan
   source files to only those verified by the strace `openat` log.
   Files not opened during the build are excluded from the SPDX.

**Remaining future work:**

- Cross-reference `~/.m2/repository/` `openat` events with `mvn
  dependency:tree` to verify which declared dependencies were actually
  accessed during compilation.
- Detect plugin-injected dependencies (shade, assembly) that appear in
  `openat` events but not in `pom.xml`.

### Java Summary

| Strategy | Applicable? | Est. Impact | Priority |
|----------|------------|-------------|----------|
| **Consume strace log** | **Implemented** | **Improved SBOM accuracy** — filters to files actually accessed during build | **Done** |
| Pre-Hash Cache | Yes | 5–15s post-build reduction | Low (overhead already minimal) |
| seccomp-bpf | Already done (in strace) | — | — |
| Deferred Hashing | Already done | — | — |
| Maven dep:tree | Yes (Java-specific) | Reduces to <2% | Medium |
| Parallel post-build scan | Yes | 20–30% post-build reduction | Low |

---

<a id="4-go"></a>

## 4. Go: Applying the C/C++ Strategies

**Current overhead: 150–400%** — the highest of all four languages.

**Current mechanism (from [go-build-interception.drawio](go-build-interception.drawio)):**

```
bomtrace2 go build -a → ptrace intercepts execve + openat
    → bomsh_hook2.py (per-event, Python) → raw logfile
    → bomsh_create_bom.py → treedb + ADG → SPDX
```

**Root cause of high overhead:**

1. **`-a` flag** (60–70% of overhead) — disables Go's build cache, forcing full
   recompilation of all packages on every build
2. **Python hook startup** (15–20%) — `bomsh_hook2.py` spawns a new Python
   process per traced event (~50ms startup × hundreds of events)
3. **openat tracing** (10–15%) — every `compile` invocation opens dozens of
   `.go` files, each triggering a ptrace stop
4. **SHA-256 hashing** (5–10%) — gitoid computation in Python

### Strategy-by-Strategy Applicability

| C/C++ Strategy | Go Applicability | Notes |
|---------------|-----------------|-------|
| **1. Pre-Hash Cache** | **Highly applicable** | Go dependencies are downloaded to `$GOPATH/pkg/mod/` and never change. A pre-hash cache would eliminate hashing for all third-party module files. For lazygit (~50 deps), this avoids hashing hundreds of `.go` files that are identical across builds. |
| **2. seccomp-bpf** | **Partially applicable** | bomtrace2 already traces only `execve` + `openat` (configured via `bomtrace_go.conf` `syscalls=openat`). Adding seccomp-bpf would formalize this filtering at the kernel level and eliminate userspace filtering overhead, but the gain is modest since bomtrace2 is already selective. |
| **3. Async Hash Worker** | **Applicable** | `bomsh_hook2.py` currently computes hashes synchronously during the ptrace event loop. Moving hashing to a background thread/process would allow traced processes to resume faster. |
| **4. Deferred Post-Build** | **Highly applicable** | Instead of hashing during each ptrace event, record file paths only and hash everything post-build. This would eliminate the Python startup overhead (the dominant non-`-a` cost). |
| **5. `-toolexec` Wrapper** | **★ Highest impact — Go-specific equivalent** | Go's `-toolexec` flag allows a custom program to wrap every `compile` and `link` invocation. This **eliminates ptrace entirely**. See dedicated section below. |
| **6. eBPF** | **Applicable but `-toolexec` is better** | eBPF would eliminate ptrace but still require the `-a` flag. `-toolexec` is simpler and Go-specific. |
| **Hash Daemon** | **Highly applicable** | The daemon could pre-hash the entire `$GOPATH/pkg/mod/` tree once and keep it warm. Go module files are immutable, making this a perfect cache target. |

### Go-Specific: `-toolexec` Wrapper (Equivalent to Strategy 5)

This is the single highest-impact optimization for Go. Go's stable
`-toolexec` flag replaces ptrace entirely:

```bash
# Current (ptrace-based):
bomtrace2 -c /opt/bomsh/bomtrace_go.conf go build -a -o binary .

# Proposed (wrapper-based):
go build -a -toolexec="/opt/bomsh/bin/bomsh_go_wrapper" -o binary .
```

The wrapper receives every `compile` and `link` invocation as command-line
arguments, records inputs/outputs, executes the real tool, and hashes the
results.

| Attribute | Current (bomtrace2) | With `-toolexec` |
|-----------|-------------------|-----------------|
| **Mechanism** | ptrace + Python hook per event | Go invokes wrapper directly |
| **Per-invocation cost** | ~50ms (Python startup) + ptrace overhead | ~2–5ms (compiled wrapper, no ptrace) |
| **fzf (11 modules)** | 47.5s (164% overhead) | ~20–22s (est. 10–15% overhead) |
| **lazygit (63 modules)** | 115.8s (190% overhead) | ~45–50s (est. 10–15% overhead) |

**Source reference:** `bomsh_hook2.py` Go functions
`get_all_subfiles_in_golang_compile_cmdline()` and
`get_all_subfiles_in_golang_link_cmdline()`
([Section 7](omnibor-interception-source-reference.md#7-bomtrace2-and-bomsh_hook2py-gorust-support)).

### Go-Specific: The `-a` Flag Problem

Even with `-toolexec`, the `-a` flag is still required to ensure all packages
are compiled (not served from cache). Without it, Go skips unchanged packages
and bomtrace/the wrapper sees no events for cached packages.

**Long-term fix: Go Cache Integration.** Instead of `-a`, read Go's build
cache metadata (`$GOPATH/pkg/mod/cache/download/`) to obtain hashes for cached
packages. This would allow `go build` without `-a`, using the cache normally,
while still producing a complete SBOM.

| Approach | Overhead vs. Cached Build | Complexity |
|----------|--------------------------|------------|
| Current (`-a` + bomtrace2) | 850–2,200% | Low (working today) |
| `-toolexec` + `-a` | ~100–200% | Medium |
| `-toolexec` + cache integration | ~10–30% | High |

### Go Summary

| Strategy | Applicable? | Est. Impact | Priority |
|----------|------------|-------------|----------|
| Pre-Hash Cache | Yes | 20–30% hash reduction | Medium |
| seccomp-bpf (formalize) | Marginal | 5–10% | Low |
| Deferred Post-Build | Yes | 15–20% (eliminates Python startup) | Medium |
| **`-toolexec` Wrapper** | **Yes — highest impact** | **85–90% overhead reduction** | **High** |
| Hash Daemon | Yes | Warm cache for `$GOPATH/pkg/mod/` | Medium |
| Go Cache Integration | Future | Eliminates `-a` penalty | Long-term |

---

<a id="5-rust"></a>

## 5. Rust: Applying the C/C++ Strategies

**Current overhead: 100–250%.**

**Current mechanism (from [rust-build-interception.drawio](rust-build-interception.drawio)
and `app/config.yaml` line 300–304):**

```
bomtrace2 cargo build --release    (no -c flag = default config, execve only)
    ↓
ptrace intercepts execve syscalls → bomsh_hook2.py per event
    │  └─ get_all_subfiles_in_rustc_cmdline(argv) parses rustc args
    │     to extract .rs input files and output .rlib/binary
    ↓
bomsh_create_bom.py -r {raw_logfile} -b {bom_dir} → treedb + ADG
    ↓
bomsh_sbom.py → AdgSpdxGenerator → SPDX 2.3 JSON
```

**Important detail:** Rust uses plain `bomtrace2` with **no config file**
(unlike Go which uses `bomtrace2 -c bomtrace_go.conf`). This means Rust only
traces `execve` syscalls — not `openat`. File inputs come from parsing the
`rustc` command line, not from tracing file opens. There is no
`docker/bomtrace_rust.conf`.

**Root cause of overhead:**

1. **ptrace on rustc** (35–45%) — each crate invokes `rustc` once, making
   thousands of syscalls per invocation; ptrace stops on every `execve`
2. **Python hook startup** (25–35%) — `bomsh_hook2.py` spawns a new Python
   process per `execve` event (~50ms startup)
3. **SHA-256 of `.rlib` archives** (15–20%) — compiled crate archives can be
   1–20 MB each
4. **Crate graph serialization** (5–10%) — matching traced events to
   `Cargo.lock` dependency edges

### Strategy-by-Strategy Applicability

| C/C++ Strategy | Rust Applicability | Notes |
|---------------|-------------------|-------|
| **1. Pre-Hash Cache** | **Highly applicable** | Third-party crates (from `~/.cargo/registry/`) are immutable once downloaded. A pre-hash cache eliminates re-hashing for all third-party `.rlib` files. For dura (92 crates), ~85 are third-party. |
| **2. seccomp-bpf** | **Significant — not yet implemented** | Rust's `bomtrace2` has no seccomp-bpf and no conf file. ptrace stops on ALL syscalls during `rustc` even though only `execve` is consumed. Adding kernel-level seccomp-bpf filtering would eliminate thousands of unnecessary context switches per crate. Est. 15–25% overhead reduction. |
| **3. Async Hash Worker** | **Applicable** | `bomsh_hook2.py` hashes `.rlib` files synchronously. Large archives (libgit2 = ~15 MB) could be hashed in a background thread. |
| **4. Deferred Post-Build** | **Highly applicable** | Record file paths during tracing, hash everything post-build. Eliminates Python startup overhead per event. |
| **5. `RUSTC_WRAPPER`** | **★ Highest impact — Rust-specific equivalent** | Cargo's `RUSTC_WRAPPER` env var allows a custom program to wrap every `rustc` invocation. This **eliminates ptrace entirely**. See dedicated section below. |
| **6. eBPF** | **Applicable but `RUSTC_WRAPPER` is better** | Same reasoning as Go — a language-native wrapper mechanism is simpler than a generic kernel tracer. |
| **Hash Daemon** | **Highly applicable** | The daemon could pre-hash `~/.cargo/registry/src/` (all downloaded crate source) and keep `.rlib` hashes warm across builds. |

### Rust-Specific: `RUSTC_WRAPPER` (Equivalent to Strategy 5)

Cargo's stable [`RUSTC_WRAPPER`](https://doc.rust-lang.org/cargo/reference/environment-variables.html)
environment variable is the Rust equivalent of Go's `-toolexec`:

```bash
# Current (ptrace-based):
bomtrace2 cargo build --release

# Proposed (wrapper-based):
RUSTC_WRAPPER=/opt/bomsh/bin/bomsh_rustc_wrapper cargo build --release
```

The wrapper receives the full `rustc` command line, records input `.rs` files
and output `.rlib`/binary from the arguments, executes `rustc`, and hashes
the results.

| Attribute | Current (bomtrace2) | With `RUSTC_WRAPPER` |
|-----------|-------------------|---------------------|
| **Mechanism** | ptrace + Python hook per event | Cargo invokes wrapper directly |
| **Per-crate cost** | ~50ms (Python startup) + ptrace | ~2–5ms (compiled wrapper) |
| **oxipng (44 crates)** | 36.5s (143% overhead) | ~17–18s (est. 5–10% overhead) |
| **dura (92 crates)** | 156.1s (184% overhead) | ~60–65s (est. 5–10% overhead) |

**Advantage over Go:** Rust does not require a `-a` flag. `cargo build --release`
already does a full clean build (incremental compilation is disabled in release
mode). This means `RUSTC_WRAPPER` eliminates ptrace AND there is no cache bypass
penalty — making the improvement even more dramatic than Go's `-toolexec`.

**Source reference:** `bomsh_hook2.py` function
`get_all_subfiles_in_rustc_cmdline()`
([Section 7](omnibor-interception-source-reference.md#7-bomtrace2-and-bomsh_hook2py-gorust-support))
already parses `rustc` command lines. The wrapper would reuse this logic in a
compiled language (Go or Rust) for lower startup cost.

### Rust-Specific: `Cargo.lock` Graph

`Cargo.lock` contains exact versions and SHA-256 checksums for all crate
dependencies:

```toml
[[package]]
name = "zopfli"
version = "0.8.1"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "e5019f391bac5cf..."
```

For third-party crates, the SPDX dependency graph can be derived from
`Cargo.lock` without tracing the build at all. Only first-party crate
compilation needs tracing for source-file-level detail. For oxipng, 40 of 44
crates are third-party — only 4 need live tracing.

### Rust Summary

| Strategy | Applicable? | Est. Impact | Priority |
|----------|------------|-------------|----------|
| Pre-Hash Cache | Yes | 15–20% hash reduction | Medium |
| seccomp-bpf (not yet implemented) | Yes — significant | 15–25% (eliminate thousands of unnecessary ptrace stops) | Medium-High |
| Deferred Post-Build | Yes | 25–35% (eliminates Python startup) | Medium |
| **`RUSTC_WRAPPER`** | **Yes — highest impact** | **85–95% overhead reduction** | **High** |
| `Cargo.lock` graph | Yes | 30–40% (skip third-party tracing) | Medium |
| Hash Daemon | Yes | Warm cache for `~/.cargo/registry/` | Medium |

---

<a id="6-python"></a>

## 6. Python: Initial Design Considerations

**Status:** Early stages. No `.drawio` diagram yet. Python support in
OmniBOR/bomsh is not yet implemented.

### Why Python Is Different

Python's build and dependency model is fundamentally different from compiled
languages:

| Aspect | C/C++, Go, Rust | Java | Python |
|--------|----------------|------|--------|
| **Compilation** | Source → binary (native code) | Source → bytecode (JVM) | Source → bytecode (optional, `.pyc`) |
| **Dependency resolution** | Build-time (linker) | Build-time (Maven/Gradle) | Install-time (`pip install`) |
| **SBOM target** | Final binary + linked libs | JAR/WAR + bundled deps | Installed packages in virtualenv |
| **Build tracer useful?** | Yes (captures linker inputs) | Partially (strace captures file access) | **Limited** — `pip install` downloads pre-built wheels, no compilation for most packages |

### Interception Strategy Options for Python

#### Option A: `pip` Metadata (No Tracing Needed)

Python's package metadata is fully declarative:

```bash
pip freeze > requirements.txt       # Exact installed versions
pip show <package>                  # Metadata including dependencies
pipdeptree --json                   # Full dependency tree as JSON
```

**Impact:** Zero build overhead. The dependency graph is already available from
pip's installed metadata (`importlib.metadata` API). No tracing, no ptrace, no
strace.

**Limitation:** Only captures declared `install_requires` dependencies, not
runtime-discovered imports (e.g., `importlib.import_module(name)`).

#### Option B: `pip install` Tracing (strace for Network + File I/O)

Trace `pip install` with strace to capture which packages are downloaded and
extracted:

```bash
strace -f --seccomp-bpf -e trace=openat,connect pip install -r requirements.txt
```

**Impact:** Captures the full file-level view of what pip installs. Useful for
detecting vendored or bundled dependencies that aren't in `install_requires`.

**Overhead:** Minimal (same as Java's approach — openat-only tracing with
seccomp-bpf).

#### Option C: Import-Time Analysis (Runtime Tracing)

Instrument the Python runtime to capture actual imports:

```python
import sys
_original_import = __builtins__.__import__
def _tracing_import(name, *args, **kwargs):
    log_import(name)
    return _original_import(name, *args, **kwargs)
__builtins__.__import__ = _tracing_import
```

**Impact:** Captures runtime dependency graph including dynamic imports. This is
the Python equivalent of tracing `execve` — it shows what actually executes,
not just what's declared.

**Overhead:** Negligible — import hooks add microseconds per import, and Python
applications typically import 50–200 modules at startup.

### Python Strategy Mapping

| C/C++ Strategy | Python Equivalent | Notes |
|---------------|-------------------|-------|
| Pre-Hash Cache | Pre-hash `site-packages/` | Virtualenv packages are immutable after install. Cache all hashes once. |
| seccomp-bpf | openat tracing of `pip install` | Same approach as Java, if strace-based tracing is chosen. |
| Compiler Wrapper | Import hook or pip plugin | Python-native instrumentation, no ptrace needed. |
| Hash Daemon | Watch `site-packages/` for changes | Pre-compute hashes on `pip install` events. |

### Python Recommendation

**Start with Option A (pip metadata)** — it provides a complete SBOM with zero
overhead. Add Option B (strace) or Option C (import hooks) only if
runtime-discovered dependencies need to be captured.

---

<a id="7-matrix"></a>

## 7. Cross-Language Strategy Matrix

This matrix shows the applicability and estimated impact of each optimization
strategy across all five supported languages.

### Strategy 1: Pre-Hash Cache

| Language | Applicable? | Target Files | Est. Impact |
|----------|------------|-------------|-------------|
| C/C++ | Yes | System headers, project source | 11pp overhead reduction |
| Java | Yes | `.java`, `.class`, `.jar` in post-build scan | 5–15s post-build reduction |
| Go | Yes | `$GOPATH/pkg/mod/` (immutable third-party) | 20–30% hash time reduction |
| Rust | Yes | `~/.cargo/registry/src/` (immutable third-party) | 15–20% hash time reduction |
| Python | Yes | `site-packages/` (immutable after install) | Negligible (hashing is not a bottleneck) |

### Strategy 2: seccomp-bpf Syscall Filter

| Language | Applicable? | Current State | Est. Impact |
|----------|------------|--------------|-------------|
| C/C++ | Yes — highest impact | `bomtrace3` traces ALL syscalls | 11pp overhead reduction |
| Java | **Already done** | `strace --seccomp-bpf -e trace=openat` | — |
| Go | Moderate | `bomtrace2 -c bomtrace_go.conf` filters to execve + openat at userspace level, no kernel seccomp | 5–10% |
| Rust | **Significant** | `bomtrace2` (no conf) — ptrace stops on ALL syscalls during rustc, only execve is consumed | 15–25% |
| Python | N/A if using pip metadata | — | — |

### Strategy 5 Equivalent: Language-Native Wrapper

| Language | Mechanism | Replaces | Est. Impact |
|----------|-----------|----------|-------------|
| C/C++ | `CC=/opt/bomsh/wrapper` | bomtrace3 (ptrace) | 35pp overhead reduction |
| Java | Maven plugin / Gradle task | strace | Minimal (overhead already <17%) |
| Go | `go build -toolexec=wrapper` | bomtrace2 (ptrace) | **85–90% overhead reduction** |
| Rust | `RUSTC_WRAPPER=wrapper` | bomtrace2 (ptrace) | **85–95% overhead reduction** |
| Python | pip plugin / import hook | N/A (no current tracer) | N/A |

### Strategy 7: Git-Aware Hash Daemon + Central Hash Store

| Language | Applicable? | Watch Target | Pre-Warm Source |
|----------|------------|-------------|----------------|
| C/C++ | Yes | Repo source + system headers | [Central Hash DB](cache-store-options.md#central-hash-store-integration) |
| Java | Yes | Repo source + `~/.m2/repository/` | Central Hash DB |
| Go | Yes | Repo source + `$GOPATH/pkg/mod/` | Central Hash DB + `go.sum` |
| Rust | Yes | Repo source + `~/.cargo/registry/` | Central Hash DB + `Cargo.lock` checksums |
| Python | Low value | `site-packages/` | pip metadata (no hashing needed) |

---

<a id="8-priority"></a>

## 8. Recommended Priority by Language

### High Priority (biggest ROI)

| Language | Strategy | Why |
|----------|----------|-----|
| **Go** | `-toolexec` wrapper | Reduces overhead from 150–400% to ~10–15%. Single biggest improvement across all languages. |
| **Rust** | `RUSTC_WRAPPER` | Reduces overhead from 100–250% to ~5–10%. No `-a` flag penalty makes this even more effective than Go. |
| **C/C++** | Pre-Hash Cache + seccomp-bpf (Strategies 1+2) | Reduces overhead from 40% to ~18%. Already detailed in [main proposal](omnibor-performance-optimization-proposal.md). |

### Medium Priority (meaningful but not urgent)

| Language | Strategy | Why |
|----------|----------|-----|
| **Go** | Pre-Hash Cache for `$GOPATH/pkg/mod/` | Third-party Go modules are immutable — perfect cache targets. |
| **Rust** | `Cargo.lock` graph derivation | 90%+ of crates are third-party with known checksums. Skip tracing them entirely. |
| **Go** | Deferred post-build hashing | Eliminates Python startup per ptrace event. Useful even with `-toolexec`. |
| **All** | Hash Daemon + Central Hash Store | Cross-team sharing and cold-cache pre-warming ([Architecture A+B](cache-store-options.md#central-hash-store-integration)). |

### Low Priority (already good enough)

| Language | Strategy | Why |
|----------|----------|-----|
| **Java** | Any | Overhead is already 5–17%. Maven dep:tree could reduce to <2% but the ROI is small. |
| **Python** | pip metadata extraction | Zero overhead by design. Start here when Python support begins. |

### Implementation Roadmap

| Phase | Timeframe | Deliverables |
|-------|-----------|-------------|
| **Phase 1** | Near-term | Go `-toolexec` wrapper, Rust `RUSTC_WRAPPER` — both are compiled tools (~500 lines each) reusing `bomsh_hook2.py` parsing logic |
| **Phase 2** | Near-term | C/C++ Strategies 1+2 from [main proposal](omnibor-performance-optimization-proposal.md) |
| **Phase 3** | Medium-term | Hash Daemon + Central Hash Store for all languages |
| **Phase 4** | Medium-term | Python SBOM support (pip metadata, optional strace) |
| **Phase 5** | Long-term | Go cache integration (eliminate `-a` flag) |

---

## References

1. **C/C++ Performance Optimization Proposal:** [omnibor-performance-optimization-proposal.md](omnibor-performance-optimization-proposal.md)
2. **Build-Time Overhead Deep-Dive:** [build-time-overhead-deep-dive.md](build-time-overhead-deep-dive.md)
3. **Source Code Reference:** [omnibor-interception-source-reference.md](omnibor-interception-source-reference.md)
4. **Cache Store Options (incl. Central Hash Store):** [cache-store-options.md](cache-store-options.md)
5. **Cross-Platform Applicability:** [cross-platform-applicability.md](cross-platform-applicability.md)
6. **Go `-toolexec` documentation:** https://pkg.go.dev/cmd/go#hdr-Compile_packages_and_dependencies
7. **Cargo `RUSTC_WRAPPER`:** https://doc.rust-lang.org/cargo/reference/environment-variables.html
8. **Java build interception diagram:** [java-build-interception.drawio](java-build-interception.drawio)
9. **Go build interception diagram:** [go-build-interception.drawio](go-build-interception.drawio)
10. **Rust build interception diagram:** [rust-build-interception.drawio](rust-build-interception.drawio)
11. **C/C++ build interception diagram:** [c-cpp-build-interception.drawio](c-cpp-build-interception.drawio)
12. **pipdeptree — Python dependency tree:** https://github.com/tox-dev/pipdeptree
13. **ccache remote storage (two-tier cache precedent):** https://ccache.dev/manual/4.9.html#_remote_storage_backends
