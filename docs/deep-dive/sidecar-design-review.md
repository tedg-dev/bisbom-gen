# Sidecar Design — Devil's Advocate Review

| | |
|---|---|
| **Date** | 2026-05-01 |
| **Scope** | Critical review of `sidecar-refactoring-plan.md` and `sidecar-implementation-design.md` |
| **Purpose** | Identify contradictions, gaps, overstated claims, missing alternatives, and weaknesses before external review |
| **Method** | Adversarial analysis — challenge every assertion, surface unstated assumptions, propose counter-arguments |

---

## Table of Contents

1. [Missing Technical Design Decisions](#1-missing-technical-design-decisions)
2. [Architecture and Design Weaknesses](#2-architecture-and-design-weaknesses)
3. [Alternative Approaches Not Considered](#3-alternative-approaches-not-considered)
4. [Unvalidated Performance Claims](#4-unvalidated-performance-claims)
5. [Effort Estimate Concerns](#5-effort-estimate-concerns)
6. [Reviewer Likely Challenges](#6-reviewer-likely-challenges)
7. [Recommendations](#7-recommendations)
8. [Appendix: Editorial Notes](#8-appendix-editorial-notes)

---

<a id="1-missing-technical-design-decisions"></a>

## 1. Missing Technical Design Decisions

These are gaps in the design that require decisions before implementation
can proceed. Each represents a real technical problem that the documents
either don't address or address insufficiently.

### M1. Raw Logfile Concurrency Under `make -j` ✓

**Resolved.** Section 10.3 (Wrapper Implementation Requirements) of the
implementation design specifies `O_APPEND` mode with records ≤`PIPE_BUF`
(4096 bytes) for atomic appends. If a record exceeds `PIPE_BUF`, the
wrapper uses `flock()` or per-process files (`raw_logfile.$PID`).

### M2. Wrapper Self-Discovery via PATH ✓

**Resolved.** Section 10.3 defines the algorithm: `/proc/self/exe`
(or `realpath(argv[0])`), search `PATH`, resolve symlinks, compare
inodes, return first candidate whose inode differs from the wrapper's.

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

**Resolved.** Section 5.3 of the implementation design now includes
an accuracy caveat documenting shade plugin, profile activation, and
optional dependency limitations. The pipeline logs a warning when
shade/assembly plugins are detected. dep:tree remains the best
available metadata source (matches CycloneDX Maven Plugin's approach).

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

### M5. Failure Mode Strategy ✓

**Resolved.** Design principle P7 (Failure Isolation) in the
implementation design defines four failure scenarios (wrapper crash,
parse failure, resolver failure, compiler not found) with explicit
behavior for each. Key rule: wrappers MUST NOT break the customer's
build.

### M6. Build Reproducibility Impact ✓

**Resolved.** P7 states: "The wrapper MUST NOT modify the build
environment beyond its own tracing side-effects. It MUST NOT alter
compiler flags, timestamps, or environment variables."

### M7. Sidecar Image Size ✅

**Resolved.** Section 3.1 of the implementation design now includes a
component-by-component size estimate (~270 MB total), well under the
500 MB enterprise acceptance threshold.

### M8. Sidecar Readiness Levels ✅

**Resolved.** Three readiness levels (L1: Demo-ready, L2: Enterprise-ready,
L3: Production-hardened) are now defined in
[sidecar-implementation-design.md](sidecar-implementation-design.md),
Section 3.1, with per-language current status. Sidecar image size estimate
(~270 MB) is also documented there.

### M9. Go Overhead Baseline ✅

**Resolved.** Section 7.5 of the implementation design now explicitly
states that 10–15% is the wrapper's marginal cost on top of a forced
rebuild, with total overhead vs. cached build at 100–215%.

### M10. Rust Build Cache Interaction ✅

**Resolved.** Section 8.5 of the implementation design now documents
that Rust has a build cache, `RUSTC_WRAPPER` misses cached crates, and
`Cargo.lock` metadata compensates. The refactoring plan (Section 4.4)
no longer claims "no `-a` problem."

---

<a id="2-architecture-and-design-weaknesses"></a>

## 2. Architecture and Design Weaknesses

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
- `build_cmd = "go build -v && go build -race"` — replaces BOTH
  occurrences when only the first should be instrumented.

**Recommendation:** Use a more robust command parser, or require that
`build_steps` in config contain exactly one build command per entry
(which the documents seem to assume but don't enforce).

### D4. Delivery Model — Docker Is Not the Only Option

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

### D5. Standalone Mode Toolchain Mismatch — Who Builds for Whom?

**Challenge:** The standalone image bundles fixed toolchain versions
(gcc 12.2, JDK 17, Go 1.21). Any team whose build environment uses
different versions gets an SBOM that reflects OUR toolchains, not theirs.
This is a fundamental accuracy problem that directly contradicts the
project's core value proposition: "the SBOM must reflect the production
binary."

**Devil's advocate questions:**

1. **Who updates the standalone toolchains?** If gcc 14 ships and three
   teams need it, do we update the published standalone image? What about
   teams still on gcc 11? One image cannot serve all.
2. **Custom standalone shifts maintenance burden.** Telling teams "build
   your own image with your toolchains" means every team is now
   maintaining their own Dockerfile — compiling OmniBOR tools against
   their base, resolving version conflicts, and debugging integration
   issues without our support. This is a significant adoption barrier.
3. **Sidecar eliminates the problem entirely.** The sidecar image has NO
   toolchains, so there is no mismatch. The team's native toolchain
   is always used. This is the strongest argument for making sidecar
   the primary deployment model and positioning standalone as
   evaluation/demo only.
4. **Standalone (custom) is really "bring your own container."** Is this
   meaningfully different from sidecar mode with extra steps? A team
   building a custom standalone image could instead mount the sidecar
   alongside their existing build container — less effort, same result.

**Resolved.** Section 3.1 of the implementation design now explicitly
states that **sidecar is the recommended model for any team that cares
about SBOM accuracy**. Standalone (default) is for evaluation/demos.
Standalone (custom) is an escape hatch.

### D6. No Versioning or Compatibility Story

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

<a id="3-alternative-approaches-not-considered"></a>

## 3. Alternative Approaches Not Considered

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

<a id="4-unvalidated-performance-claims"></a>

## 4. Unvalidated Performance Claims

### P1. "3–5% Overhead" for C/C++ Wrappers — No Benchmark Data

**Claim (refactoring plan Section 4.1):** "Expected overhead: 3–5% (wrapper)."

This is an estimate, not a measurement. The overhead depends on hash
algorithm speed, I/O contention under `make -j64`, and process startup.
ccache reports 1–5% for cache hits and 10–20% for cache misses. Since
OmniBOR always hashes (no cache), **5–15%** is more defensible.

**Recommendation:** Acknowledge this is an estimate and commit to
benchmarking during implementation. Widen the range or cite data.

### P2. Rust Build Cache ✅

**Resolved.** The refactoring plan no longer claims "no `-a` problem"
for Rust. The implementation design (Section 8.5) now documents that
Rust has a build cache, `RUSTC_WRAPPER` misses cached crates, and
`Cargo.lock` provides complete dependency metadata as compensation.

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

<a id="6-reviewer-likely-challenges"></a>

## 6. Reviewer Likely Challenges

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

<a id="7-recommendations"></a>

## 7. Recommendations

### Resolved Issues

| # | Issue | Resolution |
|---|-------|-----------|
| ✅ | Raw logfile concurrency (M1) | Section 10.3: `O_APPEND` + `PIPE_BUF` atomic writes |
| ✅ | Wrapper self-discovery (M2) | Section 10.3: `/proc/self/exe` + inode comparison |
| ✅ | Maven dep:tree accuracy (M3) | Section 5.3: shade/profile/optional caveats documented |
| ✅ | Failure mode strategy (M5) | Design principle P7: four failure scenarios defined |
| ✅ | Build reproducibility (M6) | P7: wrapper MUST NOT modify build environment |
| ✅ | Sidecar image size (M7) | Section 3.1: ~270 MB estimated |
| ✅ | Readiness levels (M8) | Section 3.1: L1/L2/L3 defined with criteria |
| ✅ | Go overhead baseline (M9) | Section 7.5: total vs. cached build stated explicitly |
| ✅ | Rust build cache (M10) | Section 8.5: cache interaction + `Cargo.lock` compensation |
| ✅ | Toolchain mismatch (D5) | Section 3.1: sidecar explicitly recommended for SBOM accuracy |

### Open Issues

| # | Issue | Fix | Severity |
|---|-------|-----|----------|
| 1 | Missing Syft/Trivy comparison (6.1) | Add value proposition: build-time tracing vs. static analysis | **High** |
| 2 | Wrapper chaining protocol (M4) | Specify `OMNIBOR_DELEGATE` behavior for missing/misbehaving delegates | **Medium** |
| 3 | Strategy subclass proliferation (D1) | Config options on base classes, not separate subclasses | **Medium** |
| 4 | Config 3-layer resolution untested (D2) | Implement + test before committing schema | **Medium** |
| 5 | String-based command instrumentation (D3) | Require single command per `build_step` entry | **Medium** |
| 6 | No versioning story (D6) | Raw logfile format version header, compatibility matrix | **Medium** |
| 7 | Security considerations missing (6.6) | Wrapper integrity, logfile ACLs, SBOM classification | **Medium** |

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

<a id="8-appendix-editorial-notes"></a>

## 8. Appendix: Editorial Notes

Minor wording and consistency issues. None of these affect design
decisions — address if time permits.

- **"Identical SPDX output" wording:** Consider "equivalent SPDX output"
  for external audiences who might misread "identical" as byte-level.
- **Priority numbering:** ROI sections say "Priority 1 (tied with Go)"
  for Rust, but implementation schedule puts it at Phase 3. Use
  "Highest Technical ROI" vs. "Phase 1 Pilot" to avoid confusion.
- **InterceptionStrategy interface:** ABC definition says 2 methods but
  class diagram shows 3. Reconcile.
- **raw_logfile path:** Both modes use the same temp file path. Use
  mode-specific paths or include run timestamp for isolation during
  testing.
- **Python "zero overhead":** Clarify as "zero build overhead" — SBOM
  generation itself has runtime cost.

---

*Document created: 2026-05-01 09:59 HST*
*Restructured: 2026-05-01 11:30 HST — reordered to lead with design issues*
