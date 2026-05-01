# Sidecar Design — Devil's Advocate Review

| | |
|---|---|
| **Date** | 2026-05-01 |
| **Scope** | Critical review of `sidecar-refactoring-plan.md` and `sidecar-implementation-design.md` |
| **Purpose** | Identify contradictions, gaps, overstated claims, missing alternatives, and weaknesses before external review |
| **Method** | Adversarial analysis — challenge every assertion, surface unstated assumptions, propose counter-arguments |

---

## Table of Contents

1. [Contradictions Between Documents](#1-contradictions-between-documents)
2. [Overstated or Unsupported Claims](#2-overstated-or-unsupported-claims)
3. [Missing Technical Issues](#3-missing-technical-issues)
4. [Alternative Approaches Not Considered](#4-alternative-approaches-not-considered)
5. [Effort Estimate Concerns](#5-effort-estimate-concerns)
6. [Architecture and Design Weaknesses](#6-architecture-and-design-weaknesses)
7. [Reviewer Likely Challenges](#7-reviewer-likely-challenges)
8. [Recommendations](#8-recommendations)

---

<a id="1-contradictions-between-documents"></a>

## 1. Contradictions Between Documents

### C1. SPDX Output Identity Claim vs. Reality

**Implementation design (Section 1):**
> "Both modes must produce identical SPDX output from identical source code."

**Problem:** This is **physically impossible** and the design itself
contradicts it in multiple places:

- Section 15.2 (Testing Strategy) says "File-level hashes may differ
  (different compiler binary)" — acknowledging non-identical output.
- Sidecar mode uses the customer's compiler (e.g., GCC 13 on RHEL 9),
  while standalone uses the container's compiler (GCC 11 on Ubuntu 22.04).
  Different compilers produce different binaries with different SHA-256
  hashes. The SPDX `checksums` field WILL differ.
- The package resolver produces `pkg:rpm/rhel/` PURLs on RHEL vs.
  `pkg:deb/ubuntu/` on Ubuntu. These are structurally different SBOMs.
- System library versions differ between distros. The SPDX `DYNAMIC_LINK`
  relationships will reference different library versions.

**Fix:** Replace "identical SPDX output" with **"structurally equivalent
SPDX output"** — same package count (within tolerance), same relationship
types, same dependency graph shape. Define equivalence criteria explicitly:
- Same number of `DESCRIBES` relationships
- Same direct dependency names (versions may differ)
- Same relationship type distribution (STATIC_LINK, DYNAMIC_LINK, etc.)
- Package count within ±5% (allowing for distro-specific system libs)

**Severity:** High — a reviewer will immediately flag this as an
impossible claim that undermines credibility.

### C2. Priority Numbering Conflicts

**Refactoring plan (Section 6):** Rust is labeled "Priority 1 (tied with
Go)" but is action item #7 in the priority list. Go is action item #6.

**Implementation design (Section 6.5):** Rust ROI says "Priority 1 (tied
with Go)."

**Implementation design (Section 12):** Phase 3 puts Go and Rust at
Weeks 8–12, while Phase 1 is Java and Phase 2 is C/C++.

**Problem:** The documents say Rust/Go are "Priority 1" in their ROI
sections but "Priority 3/4" in the implementation schedule. This
creates confusion — "Priority 1" means different things in different
contexts (technical ROI vs. enterprise adoption order).

**Fix:** Clearly distinguish **technical priority** (which language
benefits most from sidecar) from **implementation priority** (which
language ships first for business reasons). Use different terms:
"Highest Technical ROI" vs. "Phase 1 Pilot."

### C3. Java Pilot — Already Sidecar-Ready vs. Needs Optimization

**Refactoring plan (Section 4.4):** "Java is **already the closest to
true sidecar mode**."

**Implementation design (Section 8.2):** "Java is **already
sidecar-compatible** — the strace+Maven/Gradle approach works..."

**But then Section 8.3:** "Replace strace with Maven dep:tree" —
which is listed as a multi-week optimization in Phase 1.

**Problem:** If Java is "already sidecar-ready," why is Phase 1
(4 weeks) entirely devoted to making Java work? The answer is that
Java sidecar works technically but fails on enterprise infrastructure:
no RPM resolver, no `SYS_PTRACE` removal. But the documents don't
clearly separate "works in demo" from "works in enterprise production."

**Fix:** Define sidecar readiness levels:
- **L1: Demo-ready** — works in our container on Ubuntu (Java today)
- **L2: Enterprise-ready** — works on customer's RHEL without
  `SYS_PTRACE` (Java after Phase 1)
- **L3: Production-hardened** — ARM64, wrapper chaining, golden file
  validated (future)

### C4. `InterceptionStrategy` Interface Size

**Implementation design (Section 4.5):** Shows `InterceptionStrategy` with
2 abstract methods: `instrument_command()`, `generate_adg()`.

**Implementation design (Section 2, P4):** "The `InterceptionStrategy`
interface has two methods."

**But the class diagram (Section 3.3):** Shows 3 methods:
`instrument_command()`, `generate_adg()`, `get_env_vars()`.

**Problem:** The interface description and the class diagram disagree.

**Fix:** Reconcile — either the diagram is wrong (remove `get_env_vars()`)
or the ABC definition is incomplete (add it). Given that
`instrument_command()` already returns `(cmd, env_vars)`, the separate
`get_env_vars()` method appears redundant and should be removed from
the diagram.

### C5. Go Overhead Numbers Inconsistent

**Refactoring plan (Section 4.2):** "Expected overhead: 10–15% (with
`-a`), ~30% without cache integration."

**Implementation design (Section 7.5):** "150–400% → 10–15% (Phase A),
~30–50% less with Phase B."

**Problem:** Phase A uses `-a` (full rebuild). How can `-a` produce only
10–15% overhead when the refactoring plan says `-a` adds "100–200%
overhead on top of a normal cached build"? The 10–15% figure appears to
be the overhead of the *wrapper itself* on top of a full rebuild, not the
total overhead compared to a normal cached build.

A reviewer will calculate: normal cached build = 1x. With `-a`: 2–3x.
With `-a` + wrapper: 2.1–3.15x. That's **110–215% overhead** vs. a cached
build, not 10–15%.

**Fix:** Clarify the baseline. The 10–15% is overhead **vs. a full
rebuild without wrappers** (i.e., vs. `go build -a`). The **total
overhead vs. a normal cached build** is 100–215%. State both numbers
explicitly.

### C6. `raw_logfile` Path Duplicated Across Modes

**Implementation design (Section 4.2 config):** Both standalone and
sidecar modes use `raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1`.

**Problem:** If both modes use the same temp file path, running standalone
and sidecar builds on the same machine (e.g., during testing) would
overwrite each other's data. This is a minor issue but a reviewer might
flag it as poor isolation.

**Fix:** Use mode-specific paths or make the path configurable per-run
(e.g., include a run timestamp or mode prefix).

---

<a id="2-overstated-or-unsupported-claims"></a>

## 2. Overstated or Unsupported Claims

### O1. "3–5% Overhead" for C/C++ Wrappers

**Claim (refactoring plan Section 4.1):** "Expected overhead: 3–5% (wrapper)."

**Challenge:** This number appears to be an *estimate*, not a measurement.
No benchmark data is cited. The overhead depends heavily on:

- **Hash algorithm speed** — SHA-256 of a 100MB binary takes ~200ms even
  with hardware acceleration
- **I/O for raw logfile writes** — atomic append to a shared logfile
  under `make -j64` creates contention
- **Process startup** — even a C wrapper has fork+exec overhead
- **Dependency file parsing** — reading `-MD` output adds I/O

ccache reports 1–5% overhead for cache hits and 10–20% for cache misses.
Since OmniBOR always hashes (no cache), the wrapper overhead is closer to
ccache's miss path: **5–15%** is more defensible.

**Fix:** Either cite benchmark data or widen the range to "5–15%" with a
note that actual overhead depends on binary size and I/O throughput.
Alternatively, acknowledge this is an estimate and commit to benchmarking
during implementation.

### O2. "~50ms Python Startup Overhead" Stated as Fact

**Claim (refactoring plan Section 5.1):** "The ~50ms Python process startup
overhead per invocation dominates non-ptrace overhead."

**Challenge:** Python startup time varies significantly:
- Python 3.11+: ~25ms on modern hardware with `site` imported
- Python 3.13+: ~15ms with lazy imports
- In a Docker container with many installed packages: ~80ms
- With `PYTHONDONTWRITEBYTECODE=1` and minimal imports: ~20ms

The "~50ms" figure is plausible but should cite a measurement environment.
On fast hardware with Python 3.13, the actual startup may be 15–25ms, which
reduces the urgency of rewriting wrappers in compiled languages.

**Fix:** State the measurement conditions or cite a source. The argument
for compiled wrappers is still strong (even 20ms × 1000 invocations =
20 seconds), but the specific number should be defensible.

### O3. "No `-a` Problem" for Rust Overstated

**Claim (refactoring plan Section 4.3):** "No `-a` problem — `cargo build
--release` does a full build by default (incremental compilation is
disabled in release mode)."

**Challenge:** This is **partially incorrect**:
- `cargo build --release` does NOT force a full rebuild. It uses the
  Cargo build cache. If nothing changed, it recompiles nothing.
- What's true is that **incremental compilation** is disabled for release
  builds (debug info, incremental artifacts). But the build cache (reuse of
  already-compiled crates) still works.
- This means `RUSTC_WRAPPER` will NOT see crates that are already cached.
  If a team does `cargo build --release` twice, the second run skips all
  compilation, and the wrapper sees nothing.

The difference vs. Go is that Rust's `Cargo.lock` provides full
dependency information (versions, checksums) without needing to trace.
So the SBOM is still complete from metadata — the wrapper is only needed
for first-party code hashing.

**Fix:** Correct the statement. Rust DOES have a build cache. The reason
it's less problematic than Go is that `Cargo.lock` provides complete
dependency metadata, not that the cache doesn't exist.

### O4. "Zero Overhead" for Python

**Claim (implementation design Section 9):** "Expected overhead: Zero."

**Challenge:** Reading `pip freeze`, parsing `RECORD` files, running
`pipdeptree --json`, and generating SPDX JSON is not "zero overhead."
It's zero *build* overhead (the build itself is not instrumented), but
the SBOM generation step takes time — likely 5–30 seconds depending on
the number of packages.

**Fix:** "Zero build overhead" or "Zero impact on build time" — but
acknowledge that SBOM generation itself has a runtime cost.

### O5. strace `--seccomp-bpf` "~97% Overhead Reduction"

**Claim (refactoring plan Section 3):** "Paul Chaignon...introduced
`--seccomp-bpf` in strace 5.3, demonstrating ~97% overhead reduction on
Linux kernel builds."

**Challenge:** The 97% figure is from a *specific workload* (Linux kernel
build, which makes millions of syscalls, mostly non-`openat`). For a
Maven build that makes far fewer syscalls, the overhead reduction is
smaller. The Java pipeline already uses `--seccomp-bpf`, so the remaining
overhead (5–17%) is *after* this optimization.

The claim isn't wrong — it's just potentially misleading if a reviewer
thinks it applies to OmniBOR's use case specifically.

**Fix:** Add "(on syscall-heavy workloads like Linux kernel builds)" to
the claim. Note that Java's 5–17% overhead is already *with*
`--seccomp-bpf` applied.

---

<a id="3-missing-technical-issues"></a>

## 3. Missing Technical Issues

### M1. Raw Logfile Concurrency Under `make -j`

Neither document addresses **concurrent writes** to the raw logfile.

When `make -j64` runs 64 compiler invocations in parallel, 64 wrapper
processes all append to the same `raw_logfile`. Without file locking or
per-process logfiles, records will interleave and corrupt each other.

**Options:**
- **File locking** — `flock()` on the logfile. Adds serialization overhead.
- **Per-process logfiles** — each wrapper writes to
  `raw_logfile.$PID`. `bomsh_create_bom.py` merges them post-build.
  Better parallelism but more complexity.
- **Atomic append** — if records are ≤PIPE_BUF (4KB on Linux), `write()`
  to a file opened with `O_APPEND` is atomic. Records must be kept small.

This is a critical implementation detail that affects correctness.
bomtrace3 doesn't have this problem because it runs in a single process.
The wrapper architecture introduces it.

**Recommendation:** Document the concurrency strategy. Atomic `O_APPEND`
writes with records ≤4KB is the simplest correct approach.

### M2. Wrapper Self-Discovery via PATH

Both documents say the wrapper "discovers the real compiler on `PATH`
(skipping itself)." But the algorithm for "skipping itself" is not defined.

**Problem:** If the wrapper is installed as `/opt/omnibor/gcc` and `PATH`
is `/opt/omnibor:/usr/bin`, the wrapper must:
1. Search PATH for `gcc`
2. Skip any entry that resolves to itself
3. Return the next match

This is non-trivial if:
- The wrapper is a symlink (must resolve symlinks before comparing)
- Multiple wrappers exist (e.g., ccache also installs as `gcc`)
- The real compiler has a different name (`gcc-12` vs. `gcc`)

ccache solves this by: (a) compiling the known compiler path at install
time, or (b) searching PATH and comparing inodes.

**Recommendation:** Define the discovery algorithm explicitly. Cite how
ccache handles it (inode comparison after symlink resolution).

### M3. Java: `mvn dependency:tree` May Not Match Actual Build

**Claim:** Maven `dependency:tree` provides the "complete dependency graph."

**Problem:** `mvn dependency:tree` resolves dependencies according to
Maven's dependency mediation rules (nearest-wins). But the actual
dependencies included in the built JAR depend on:

- **Maven profiles** — `<profiles>` can add/remove dependencies. If
  `dependency:tree` is run without the same profiles as the build,
  the graph differs.
- **Shade/assembly plugins** — These can include, exclude, or relocate
  dependencies. `dependency:tree` shows the *declared* graph, not what's
  in the JAR.
- **Optional dependencies** — `dependency:tree` includes optional
  dependencies by default, but they may not be on the runtime classpath.
- **Dependency conflicts** — If two transitive deps request different
  versions of the same library, Maven picks one. The `dependency:tree`
  output may not match what `javac` actually sees.

The CycloneDX Maven Plugin works around this by running *during* the
build (as a Maven plugin), not after. It has access to the resolved
classpath at build time.

**Recommendation:** Acknowledge that `dependency:tree` is an
*approximation* of the actual classpath. For exact results, consider
running a Maven plugin during the build (like CycloneDX does) or
validating `dependency:tree` output against the strace log.

### M4. `OMNIBOR_DELEGATE` Environment Variable for Wrapper Chaining

The implementation design introduces `OMNIBOR_DELEGATE` for wrapper
chaining, but no document specifies:

- What happens if `OMNIBOR_DELEGATE` contains a program that doesn't
  exist?
- What if the delegate itself is a wrapper that modifies the command
  line (ccache strips `-g`, distcc changes the target)?
- How does the wrapper know when the delegate finished and the real
  compiler started? (For hashing the output, the wrapper needs to
  wait for the *final* compiler, not the cache wrapper.)

**Recommendation:** Specify the wrapper chaining protocol in detail.
The simplest approach: the OmniBOR wrapper always hashes the output
*after* the entire chain completes, regardless of which tool in the
chain produced it.

### M5. No Rollback Strategy

Neither document describes what happens if sidecar mode fails mid-build:

- If the wrapper crashes after the compiler succeeds, the binary is
  built but the SBOM is incomplete. Is the build considered successful?
- If `bomsh_create_bom.py` fails to parse the wrapper's raw logfile,
  does the pipeline fail the build or produce a partial SBOM?
- If the package resolver can't identify a system library (new distro,
  edge case), does the SBOM omit it or include it as `NOASSERTION`?

**Recommendation:** Define failure modes explicitly:
- **Wrapper crash:** Build succeeds, SBOM generation fails → pipeline
  reports error but does not fail the customer's build
- **Parse failure:** Partial SBOM with explicit gaps → `NOASSERTION`
  for unparsed components
- **Resolver failure:** `NOASSERTION` for the specific package, not a
  pipeline failure

### M6. No Consideration of Build Reproducibility Impact

The wrapper adds overhead (I/O, hashing). If the build uses
`SOURCE_DATE_EPOCH` or other reproducibility mechanisms, does the
wrapper affect them?

- The wrapper should not modify any compiler flags or environment
  variables (other than `CC=` itself).
- The wrapper should not add timestamps to the raw logfile that could
  leak into the build output.
- The wrapper MUST use `exec` to invoke the real compiler so the
  process environment is identical to a non-wrapped build.

**Recommendation:** Add a statement that the wrapper MUST NOT modify
the build environment beyond its own tracing side-effects.

### M7. Sidecar Image Size Not Addressed

The refactoring plan discusses a sidecar image that excludes compilers.
But it doesn't estimate the image size. The current standalone image is
likely 2–5GB (GCC + Go + Rust + Java + Python). The sidecar image
would be much smaller, but still includes:

- Python runtime (~300MB with pip packages)
- bomsh scripts
- bomtrace3 (for fallback mode)
- strace
- Analysis pipeline scripts

**Recommendation:** Estimate the sidecar image size. If it's >500MB,
enterprise teams may push back. Consider a minimal sidecar
(analysis-only, no bomtrace3) vs. a full sidecar (with ptrace fallback).

---

<a id="4-alternative-approaches-not-considered"></a>

## 4. Alternative Approaches Not Considered

### A1. LD_PRELOAD Instead of CC= Wrappers

An alternative to `CC=` wrappers is `LD_PRELOAD` interception:

```c
// Intercept execve() in userspace via LD_PRELOAD
int execve(const char *filename, char *const argv[], ...) {
    log_invocation(filename, argv);
    return real_execve(filename, argv, envp);
}
```

**Pros vs. CC= wrappers:**
- Works with **any** build system, including Bazel, Nix, Yocto
- Doesn't require the build system to respect `CC=`
- Single interception point for all tools

**Cons vs. CC= wrappers:**
- `LD_PRELOAD` doesn't work with statically-linked binaries
- Some security-hardened environments strip `LD_PRELOAD`
- More complex to implement correctly (thread safety, signal handling)
- Not a widely used pattern for SBOM tools (less industry validation)

**Assessment:** `LD_PRELOAD` is a legitimate alternative that solves
the hermetic build problem. It should be mentioned in the design as a
potential future interception mechanism alongside eBPF — it's simpler
than eBPF and more portable, while solving the same problem
(build-system-agnostic interception).

### A2. Build Event Protocol (Bazel) as First-Class Strategy

The B.7 section mentions Bazel's BEP as a mitigation but treats it as
a future item. For enterprise teams using Bazel (which is common at
Google, Stripe, Uber, Pinterest, and many others), this is a
significant gap.

Bazel's `--build_event_json_file=bep.json` provides:
- Every action's input and output files
- The exact command lines used
- SHA-256 hashes of all artifacts (Bazel computes them for its CAS)

This is **better data than wrappers provide** — Bazel has already done
the hashing. A `BazelStrategy` that reads BEP would be lower overhead
than ptrace AND provide richer data.

**Assessment:** If any pilot team uses Bazel, this should be elevated
to Phase 2, not Phase 5. It's 2–3 weeks of work (BEP JSON parser +
strategy class) and covers a significant enterprise segment.

### A3. SPDX 3.0 Consideration

Both documents target SPDX 2.3. SPDX 3.0 was released in April 2024
and has a fundamentally different data model (profiles, elements,
relationships are different). Enterprise teams may already be planning
for SPDX 3.0 compliance.

The implementation design mentions SPDX 3.0 in Phase 5 but doesn't
assess the migration risk. Key differences:

- SPDX 3.0 uses JSON-LD, not flat JSON
- Package elements have different required fields
- Relationship types are reorganized
- Build profiles are new in 3.0

**Assessment:** The design should state explicitly that SPDX 2.3 is
the target for the initial implementation, with SPDX 3.0 as a
documented extension point. The `SpdxEmitter` interface should be
designed to support both versions via the strategy pattern (already
acknowledged in Phase 5).

### A4. Syft/Trivy as Alternative to Custom Python Pipeline

For Python SBOM generation, Syft and Trivy already parse `dist-info/`,
`requirements.txt`, and `Pipfile.lock`. Building a custom
`PythonSpdxGenerator` duplicates existing open-source tooling.

**Options:**
1. **Custom implementation** (current plan): Full control, tighter
   integration with OmniBOR's data model. 3.5 weeks effort.
2. **Syft integration**: Run `syft dir:/path/to/venv -o spdx-json`.
   Produces SPDX 2.3 directly. ~0.5 weeks to integrate. But less
   control over output format and relationship types.
3. **Hybrid**: Use Syft for initial Python SBOM, then enrich with
   OmniBOR-specific metadata (build provenance, file hashes from
   RECORD).

**Assessment:** Option 3 is worth evaluating. It could reduce Python
implementation from 3.5 weeks to 1–2 weeks while still providing
OmniBOR-specific value-add. The documents should acknowledge this
alternative and explain why custom implementation was chosen (if
it was chosen for a reason beyond "not considered").

### A5. Filesystem Overlay Instead of Wrappers

Instead of `CC=` wrappers, use a FUSE filesystem or overlayfs that
intercepts file system operations:

```bash
omnibor-fs mount /opt/omnibor/overlay
# All file writes within the overlay are logged
make -j$(nproc)
omnibor-fs umount /opt/omnibor/overlay
```

**Pros:** Build-system-agnostic, no `CC=` needed, captures ALL file I/O.
**Cons:** FUSE has significant overhead (~20–30%), requires FUSE kernel
module, complex implementation.

**Assessment:** Mention as a theoretical alternative but correctly
deprioritize it due to overhead and complexity.

---

<a id="5-effort-estimate-concerns"></a>

## 5. Effort Estimate Concerns

### E1. Infrastructure Underestimated

**Claim:** Package resolver = 3–4 days. Config schema = 2 days.

**Challenge:** The package resolver must handle:
- `dpkg-query` output parsing (multiple formats across Debian versions)
- `rpm -qf` output parsing (different across RHEL 7/8/9)
- `apk info --who-owns` output parsing
- Auto-detection via `/etc/os-release`
- Edge cases: virtual packages, diversion, alternatives
- Integration with `metadata_collector.py` (replace existing dpkg calls)
- Integration with `resolver.py` (replace hardcoded PURLs)
- Unit tests with mocked subprocess output for all three distros
- Integration tests on actual RHEL and Alpine systems

3–4 days is aggressive. **1.5–2 weeks** is more realistic for
production-quality resolver with tests. The existing `metadata_collector.py`
must be refactored, not just extended.

### E2. Upstream Wrapper Timelines Uncontrollable

All C/C++, Go, and Rust timelines depend on upstream bomsh delivering
wrapper binaries. The documents estimate 2–3 weeks per wrapper set, but:

- The bomsh project is a separate team with its own priorities
- The raw logfile format compatibility requirement adds integration risk
- No mock/stub wrappers are planned for parallel development

**Recommendation:** Define a mock wrapper interface immediately so
omnibor-analysis can develop and test strategies against mock wrappers
while upstream work proceeds. This is mentioned in R1 mitigation but
not in the implementation plan.

### E3. Python 3.5 Weeks May Be Optimistic

The Python pipeline estimate (3.5 weeks) includes:
- `python_parser.py` (RECORD, METADATA, requirements): 3–4 days
- `python_generator.py` (SPDX generation): 4–5 days
- Pipeline + config: 2 days
- C extension strace: 2 days
- Unit tests: 3 days
- Integration tests: 2 days

This totals 16–18 days = 3.2–3.6 weeks. But it doesn't account for:
- Edge cases in RECORD parsing (missing hashes, editable installs)
- `pyproject.toml` vs. `setup.cfg` vs. `setup.py` variations
- `pipdeptree` not being installed in the target venv
- C extension identification (how to distinguish C extensions from
  pure Python packages?)
- Handling of namespace packages, conditional dependencies

**4–5 weeks** is more realistic.

---

<a id="6-architecture-and-design-weaknesses"></a>

## 6. Architecture and Design Weaknesses

### D1. Strategy Pattern May Be Over-Engineered

The documents propose 8+ strategy classes:
- `PtraceStrategy`
- `CcWrapperStrategy`
- `GoToolexecStrategy`
- `RustcWrapperStrategy`
- `StraceStrategy`
- `MetadataOnlyStrategy`
- `MavenDepTreeStrategy`
- `GoHybridStrategy`
- `RustcWorkspaceWrapperStrategy`

**Counter-argument:** The actual behavior difference between strategies is
small — most just set environment variables or modify command strings.
A simpler approach might be a **configuration-driven command transformer**
without the full strategy class hierarchy:

```yaml
# Instead of strategy classes, just configure the transformation:
omnibor:
  sidecar:
    cmd_prefix: ""
    env:
      CC: /opt/omnibor/gcc-wrapper
      CXX: /opt/omnibor/g++-wrapper
    post_build: bomsh_create_bom.py -r {raw_logfile}
```

**Rebuttal:** The strategy pattern IS justified because `generate_adg()`
differs significantly across strategies (wrapper ADG vs. metadata-only
ADG vs. strace ADG). It's not just command transformation — it's also
post-build processing. The `GoHybridStrategy` merges `go.sum` metadata
with wrapper output, which can't be expressed as config.

**Verdict:** Keep the strategy pattern, but **don't create subclasses for
minor variations**. `RustcWorkspaceWrapperStrategy` should be a config
option on `RustcWrapperStrategy`, not a separate class:

```python
class RustcWrapperStrategy(InterceptionStrategy):
    def __init__(self, config):
        self.env_var = (
            "RUSTC_WORKSPACE_WRAPPER"
            if config.get("workspace_only")
            else "RUSTC_WRAPPER"
        )
```

### D2. Config Schema Complexity

The proposed config has three layers of override:
1. Global `mode: standalone/sidecar`
2. Per-language `omnibor_go.sidecar`
3. Per-repo `repos.my-project.interception`

**Problem:** Three layers of configuration create ambiguity. What wins?
If `mode: sidecar` but `repos.curl.interception: ptrace` and the language
config has no sidecar section, which fallback applies?

The `resolve_omnibor_cfg()` function handles two layers but doesn't
address the per-repo override. The strategy resolution order
("per-repo > global > default") is stated but not implemented in the
code example.

**Recommendation:** Implement and test the three-layer resolution
*before* committing to the schema. Consider simplifying to two layers
(global mode + per-repo override) and eliminating the per-language
mode split, which adds complexity without clear benefit.

### D3. `GoToolexecStrategy.instrument_command()` Uses String Replace

```python
def instrument_command(self, build_cmd, repo_dir):
    return build_cmd.replace(
        "go build", f"go build -toolexec={self.toolexec}"
    ), {}
```

**Problem:** String replacement is fragile:
- `build_cmd = "CGO_ENABLED=1 go build -v ."` — replacement works
  but only by luck (the first "go build" match).
- `build_cmd = "echo starting && go build ."` — replacement works.
- `build_cmd = "go build -v && go build -race"` — replaces BOTH
  occurrences when only the first should be instrumented.
- `build_cmd = "GO_BUILD_FLAGS='-v' go build ."` — doesn't match
  "go build" because it's preceded by another "go build" string (in
  the env var name — unlikely but shows fragility).

**Recommendation:** Use a more robust command parser, or require that
`build_steps` in config contain exactly one build command per entry
(which the documents seem to assume but don't enforce).

### D4. Dual-Mode Docker Image May Not Be the Right Delivery

The documents propose a Docker image as the enterprise delivery mechanism.
But many enterprise CI/CD environments:

- **Don't allow arbitrary Docker images** (security policy)
- **Use their own base images** (hardened, scanned, approved)
- **Can't run Docker-in-Docker** (nested containers in CI)

A **tarball or RPM/DEB package** of the OmniBOR tools (wrappers +
analysis scripts) may be simpler for enterprise deployment:

```bash
# Enterprise install:
yum install omnibor-tools-1.0.rpm
# Now CC=/opt/omnibor/gcc-wrapper works
```

The enterprise integration guide already discusses this (Tiered approach:
tarball → RPM → container). The implementation design should reference
this and not assume Docker is the only delivery mechanism.

### D5. No Versioning or Compatibility Story

What happens when:
- The wrapper binary version is 1.0 but `bomsh_create_bom.py` is 2.0?
- The raw logfile format changes?
- The config schema adds new required fields?

Neither document discusses version compatibility between components.
In an enterprise deployment, the sidecar tools may be installed months
before `bomsh_create_bom.py` is updated.

**Recommendation:** Define a version compatibility matrix and a
raw logfile format version number. The raw logfile should include a
header line with the format version.

---

<a id="7-reviewer-likely-challenges"></a>

## 7. Reviewer Likely Challenges

These are the questions a critical reviewer will ask, organized by
likely pushback intensity.

### High Pushback

1. **"Why not just use Syft/Trivy/SPDX-SBOM-Generator?"**
   These existing tools already generate SBOMs for most languages.
   The documents don't articulate why OmniBOR's build-time tracing
   produces *better* SBOMs than static analysis tools.

   **Answer:** Static tools analyze metadata files (go.mod, Cargo.lock,
   pom.xml). OmniBOR traces the *actual build* — it knows exactly which
   files were compiled into the binary, including vendored code that
   doesn't appear in any manifest file. This is critical for C/C++ where
   there is no package manifest. OmniBOR captures the ground truth;
   Syft captures declared intent. **Add this comparison explicitly to
   Section 1 of both documents.**

2. **"The Go `-a` overhead is unacceptable for large monorepos."**
   100–200% overhead on a 30-minute Go build means 60–90 minutes.
   Enterprise Go teams building large services will reject this.

   **Answer:** Phase B (go.sum for third-party) reduces this
   significantly. Phase C (Go #41145) eliminates it. But Phase B
   itself is complex and estimated at 2–3 weeks. Be transparent about
   this limitation and the mitigation timeline.

3. **"What about Windows and macOS?"**
   The entire design is Linux-only. Enterprise teams building for
   Windows/macOS need SBOMs too. Neither document addresses this.

   **Answer:** The wrapper approach (`CC=`, `RUSTC_WRAPPER`, `-toolexec`)
   works on any OS — these are not Linux-specific. However, the
   analysis pipeline (bomsh scripts, strace for Java) IS Linux-specific.
   Add a note that sidecar mode wrappers are cross-platform but the
   analysis pipeline currently requires Linux.

### Medium Pushback

4. **"Upstream bomsh is a single point of failure."**
   The entire sidecar architecture depends on upstream bomsh delivering
   wrapper binaries. If bomsh priorities shift, the project is blocked.

   **Answer:** Define fallback: if upstream wrappers are delayed, write
   minimal "shim" wrappers in omnibor-analysis that produce compatible
   raw logfiles. The shim can be replaced by upstream wrappers later.

5. **"The config schema is too complex."**
   Three layers of override, YAML config that's hundreds of lines,
   backward compatibility with flat format — this is hard to maintain.

   **Answer:** The config complexity matches the problem complexity
   (5 languages × 2 modes × per-repo overrides). But consider providing
   a `omnibor config validate` CLI command that checks config correctness.

6. **"Where is the security analysis?"**
   The wrappers intercept every compiler invocation and have access
   to all source code. In an enterprise environment, this is a
   security-sensitive position. Neither document discusses:
   - Wrapper binary integrity (how does the team verify the wrapper
     isn't tampered with?)
   - Raw logfile access control (the logfile contains full command
     lines with potentially sensitive paths)
   - SBOM data classification (the SBOM reveals the internal
     dependency graph, which may be considered confidential)

   **Recommendation:** Add a brief security considerations section.

### Low Pushback (But Should Be Addressed)

7. **"Testing strategy doesn't include performance regression tests."**
   The testing strategy covers correctness (golden files) but not
   performance. How do you ensure wrapper overhead doesn't regress
   from 5% to 50% due to a bug?

8. **"No observability or telemetry."**
   How does an enterprise team know if OmniBOR is working correctly?
   Is there a health check? Dashboard? Log format for monitoring?

---

<a id="8-recommendations"></a>

## 8. Recommendations

### Fixes Required Before Review

| # | Issue | Fix | Severity |
|---|-------|-----|----------|
| 1 | "Identical SPDX output" claim (C1) | Replace with "structurally equivalent" + define criteria | **Critical** |
| 2 | Go overhead numbers (C5) | Clarify baseline (vs. full rebuild, not cached) | **High** |
| 3 | Rust "no `-a` problem" (O3) | Correct: Rust has build cache; metadata compensates | **High** |
| 4 | Raw logfile concurrency (M1) | Define concurrency strategy (O_APPEND atomic writes) | **High** |
| 5 | Wrapper self-discovery (M2) | Define PATH search algorithm; cite ccache approach | **Medium** |
| 6 | Maven dep:tree accuracy (M3) | Acknowledge as approximation; recommend validation | **Medium** |
| 7 | Priority numbering confusion (C2) | Distinguish "Technical ROI" from "Pilot Priority" | **Medium** |
| 8 | No rollback strategy (M5) | Define failure modes: wrapper crash, parse failure, etc. | **Medium** |
| 9 | Missing Syft/Trivy comparison (7.1) | Add value proposition: build-time tracing vs. static analysis | **High** |
| 10 | C/C++ overhead range (O1) | Widen to "5–15%" or cite benchmarks | **Low** |
| 11 | Add security considerations section (7.6) | Wrapper integrity, logfile ACLs, SBOM confidentiality | **Medium** |

### Items to Acknowledge (Not Fix)

Some issues should be **acknowledged** in the document rather than fixed,
because they represent known limitations with planned mitigations:

- Go `-a` overhead → acknowledged with Phase B/C mitigation plan
- Windows/macOS → wrappers work cross-platform; analysis pipeline is
  Linux-only (known scope boundary)
- Upstream bomsh dependency → mitigate with mock wrappers for parallel
  development
- Config complexity → matches problem complexity; consider validation CLI
- Bazel/Nix/Yocto → ptrace fallback with future dedicated strategies

### Items That Strengthen the Documents

The documents are already strong in these areas (keep them):

- **Industry validation table** (Section 3 of refactoring plan) — excellent;
  every strategy is mapped to real-world precedent
- **Pre-onboarding questionnaire** (B.7.5) — proactive risk identification
- **Phased implementation with parallel tracks** — realistic timeline
- **Dependency graph** (Section 6) — clear visualization of critical path
- **Backward compatibility principle** (P1) — addresses the #1 concern of
  any refactoring proposal
- **Adversarial build scenarios** (B.1–B.7) — comprehensive coverage of
  edge cases

---

*Document created: 2026-05-01 09:59 HST*
