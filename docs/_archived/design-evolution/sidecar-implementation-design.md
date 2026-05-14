# Sidecar Implementation Design Plan

| | |
|---|---|
| **Date** | 2026-05-01 |
| **Authors** | Ted G. (architect), Cascade AI |
| **Status** | Design — pending review and approval |
| **Prerequisite reading** | [Sidecar Refactoring Plan](sidecar-refactoring-plan.md), [Enterprise Integration Guide](../guides/enterprise-integration-guide.md), [Platform Support](../architecture/platform-support.md) |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Design Principles](#2-design-principles)
3. [Architectural Overview](#3-architectural-overview)
   - [3.1 Current Architecture (Standalone Mode)](#31-current-architecture-standalone-mode)
   - [3.2 Target Architecture (Dual Mode)](#32-target-architecture-dual-mode)
   - [3.3 Interception Strategy Pattern](#33-interception-strategy-pattern)
4. [Cross-Cutting Infrastructure Changes](#4-cross-cutting-infrastructure-changes)
   - [4.1 CommandRunner — Environment Variable Support](#41-commandrunner--environment-variable-support)
   - [4.2 Config Schema — Mode Selection](#42-config-schema--mode-selection)
   - [4.3 Package Resolver Abstraction](#43-package-resolver-abstraction)
   - [4.4 Path Abstraction Layer](#44-path-abstraction-layer)
   - [4.5 Interception Strategy Interface](#45-interception-strategy-interface)
5. [Per-Language Refactoring: Java](#5-per-language-refactoring-java)
6. [Per-Language Refactoring: C/C++](#6-per-language-refactoring-cc)
7. [Per-Language Refactoring: Go](#7-per-language-refactoring-go)
8. [Per-Language Refactoring: Rust](#8-per-language-refactoring-rust)
9. [Per-Language Refactoring: Python (New)](#9-per-language-refactoring-python-new)
10. [Upstream bomsh Changes](#10-upstream-bomsh-changes)
11. [Effort Estimates and ROI Analysis](#11-effort-estimates-and-roi-analysis)
12. [Phased Implementation Plan](#12-phased-implementation-plan)
13. [Extensibility and Future-Proofing](#13-extensibility-and-future-proofing)
14. [Risk Register](#14-risk-register)
15. [Testing Strategy](#15-testing-strategy)
16. [Success Criteria](#16-success-criteria)
    - [16.1 Pre-Onboarding Screening](#16-1-pre-onboarding-screening)

---

<a id="1-executive-summary"></a>

## 1. Executive Summary

This document is the **implementation design** for converting `omnibor-analysis`
from a standalone, container-centric tool into a dual-mode system that supports
both standalone (current) and sidecar (enterprise) deployment.

**Scope:**

- **Upstream bomsh** — new wrapper binaries (C/C++, Go, Rust), modifications
  to `bomsh_create_bom.py`
- **omnibor-analysis** — refactoring of builder, metadata, SPDX generation,
  and config to support sidecar mode
- **New language** — Python pipeline (metadata-only, no compilation tracing)

**Key design constraint:** Every change must be **backward-compatible** with
existing standalone mode. The refactoring must not break any current analysis
capability. Both modes must produce **structurally equivalent** SPDX output
from identical source code — same dependency graph shape, same relationship
types, and package counts within ±5%. File-level checksums and system library
versions will differ between environments (different compilers, different
distros), which is expected and correct: each SBOM reflects its actual build.

**Estimated total effort:** 14–20 person-weeks across 4 phases over
approximately 4 months, with Phase 1 delivering production value in 4–5 weeks.

---

<a id="2-design-principles"></a>

## 2. Design Principles

These principles guide every design decision in this plan. They are ordered
by priority — when principles conflict, higher-numbered principles yield.

### P1. Backward Compatibility

Every refactoring MUST preserve existing standalone mode functionality.
The test suite must pass with zero regressions after each change.
Standalone and sidecar modes are additive — sidecar is never at the
expense of standalone.

### P2. Strategy Pattern for Interception

Each language's build interception is a **strategy** selected by config.
New interception mechanisms (e.g., eBPF, WASM) can be added as new
strategy implementations without modifying existing code. This follows
the [Gang of Four Strategy Pattern](https://refactoring.guru/design-patterns/strategy).

### P3. Config-Driven Behavior

No `if language == "go"` branches in pipeline orchestration code.
Language-specific behavior is encoded in `config.yaml` and dispatched
through strategy objects. Adding a new language means adding a config
section and a strategy class — not modifying existing pipeline files.

### P4. Interface Segregation

Each abstraction has a minimal interface. The `PackageResolver` interface
has two methods (`resolve`, `purl_scheme`). The `InterceptionStrategy`
interface has two methods (`instrument_command` which returns both the
instrumented command and any required env vars, and `generate_adg`).
Small interfaces are easier to implement, test, and extend.

### P5. Open/Closed Principle

Modules are **open for extension** (new strategies, new languages, new
package managers) but **closed for modification** (existing C/C++ pipeline
code does not change when Python is added). This is achieved through
registration patterns and config-driven dispatch.

### P6. Fail-Safe Defaults

If a config option is missing, the system falls back to standalone mode
behavior. If a wrapper binary is not found, the system logs a warning
and falls back to ptrace. Degradation is graceful, not catastrophic.

### P7. Failure Isolation — Wrappers Must Not Break Builds

The wrapper MUST NOT cause a customer's build to fail. Failure modes:

| Scenario | Behavior |
|----------|----------|
| Wrapper crashes after compiler succeeds | Build succeeds; SBOM is incomplete; pipeline reports warning |
| `bomsh_create_bom.py` fails to parse raw logfile | Build succeeded; SBOM generation fails; pipeline reports error |
| Package resolver can't identify a system library | SBOM uses `NOASSERTION` for that package; no pipeline failure |
| Wrapper can't find real compiler on PATH | Wrapper exits with error; build fails (unavoidable — same behavior as a misconfigured `CC=`) |

The wrapper MUST NOT modify the build environment beyond its own tracing
side-effects. It MUST NOT alter compiler flags, timestamps, or
environment variables (other than `CC=` itself). It MUST use `exec()` to
invoke the real compiler so the process environment is identical to a
non-wrapped build.

### P8. Value Proposition — Build-Time Tracing vs. Static Analysis

Existing tools (Syft, Trivy, SPDX-SBOM-Generator) produce SBOMs from
static metadata (go.mod, Cargo.lock, pom.xml, package-lock.json).
OmniBOR's build-time tracing produces SBOMs from the **actual build** —
it knows exactly which files were compiled into the binary.

| Capability | Static (Syft/Trivy) | Build-Time (OmniBOR) |
|-----------|---------------------|---------------------|
| C/C++ vendored deps | ❌ No manifest to read | ✅ Sees every `.c` → `.o` compilation |
| Unused declared deps | Included (false positive) | Excluded (only built code) |
| Dynamic linking evidence | ❌ Guesses from ELF headers | ✅ Traces actual `ld` invocations |
| Build tool provenance | ❌ Unknown compiler version | ✅ Records exact compiler binary |
| File-level SHA-256 | Metadata hashes only | Every compiled artifact hashed |

This is critical for C/C++ (no package manifest), vendored dependencies,
and regulatory requirements (NTIA minimum elements require build-time
provenance evidence).

---

<a id="3-architectural-overview"></a>

## 3. Architectural Overview

<a id="31-current-architecture-standalone-mode"></a>

### 3.1 Current Architecture (Standalone Mode)

<a href="sidecar-standalone-architecture.png"><img src="sidecar-standalone-architecture.png" width="600" alt="Current Architecture (Standalone Mode) — click to enlarge"></a>

*Click image to enlarge. Source: [sidecar-standalone-architecture.drawio](sidecar-standalone-architecture.drawio)*

**Coupling points** (things that bind us to container mode):

1. `CommandRunner.run()` — no `env` parameter; env vars must be baked
   into the command string
2. `BomtraceBuilder.build()` — hardcodes `{tracer} {make_cmd}` prefix
3. `AdgParser` — hardcodes Go stdlib path, system lib paths, Cargo
   registry path
4. `MetadataCollector` — calls `collect_metadata.py` which shells out
   to `dpkg-query`
5. `ComponentResolver._make_purl()` — hardcodes `pkg:deb/ubuntu/`
6. `SpdxEmitter` — unconditionally adds GCC as BUILD_TOOL_OF
7. `config.yaml` paths — `/workspace/repos`, `/opt/bomsh`,
   `/tmp/bomsh_hook_raw_logfile.sha1`

**Fundamental limitation:** Standalone mode bundles fixed toolchain
versions (e.g., gcc 12.2, JDK 17, Go 1.21). If a development team uses
different versions, the generated SBOM reflects the container's toolchains —
not the team's actual build environment.

Teams that require standalone mode due to their dev/build environment
constraints can build their own image using our Dockerfile as a base,
adding their specific toolchain versions. In this case the container is
team-maintained, not the published image on containers.cisco.com.

This yields three deployment models:

1. **Sidecar** — published to containers.cisco.com; no bundled
   toolchains; uses the team's native build tools. SBOM inherently
   reflects reality.
2. **Standalone (default)** — our published image with reference
   toolchains; suitable for demos, evaluation, and internal analysis.
3. **Standalone (custom)** — team extends our published base image via
   `FROM omnibor-env:standalone` in their own Dockerfile, adding their
   specific toolchains. Team-owned and team-maintained. SBOM reflects
   their actual build environment. **Teams MUST NOT fork the
   omnibor-analysis repository** — `FROM` inheritance ensures automatic
   security patches and pipeline updates from the upstream image.

**Recommendation:** Sidecar is the recommended model for any team that
cares about SBOM accuracy, because it uses their actual toolchains.
Standalone (default) is for evaluation, demos, and open-source analysis
where there is no canonical "correct" toolchain. Standalone (custom)
exists as an escape hatch for teams that cannot mount a sidecar.

**Sidecar readiness levels:** Each language progresses through three
stages. Phase gates and integration tests use these levels to define
"done" for each pilot:

| Level | Definition | Criteria |
|-------|-----------|----------|
| **L1: Demo-ready** | Works in our container on Ubuntu | Build completes, SPDX generated, golden file test passes |
| **L2: Enterprise-ready** | Works on customer's distro without `SYS_PTRACE` | PURLs resolve correctly on RHEL/Alpine, no privileged capabilities required |
| **L3: Production-hardened** | ARM64 validated, wrapper chaining tested, golden file regression suite passing | CI/CD integration guide complete, pre-onboarding questionnaire screening passed |

Current readiness: Java is L1 (strace works on Ubuntu), targeting L2
after Phase 1 (Maven dep:tree removes `SYS_PTRACE`). C/C++, Go, Rust
are pre-L1 (wrappers not yet available).

**Sidecar image size estimate:** The sidecar image excludes all
compilers. Estimated contents:

| Component | Size (est.) |
|-----------|-------------|
| Python 3.11 + pip packages | ~250 MB |
| bomsh scripts | ~5 MB |
| bomtrace3 (ptrace fallback) | ~2 MB |
| strace | ~3 MB |
| Wrapper binaries (C/Go/Rust) | ~10 MB |
| Analysis pipeline scripts | ~1 MB |
| **Total** | **~270 MB** |

This is well under the 500 MB threshold for enterprise acceptance.
The standalone image (with all toolchains) is 2–5 GB by comparison.

<a id="32-target-architecture-dual-mode"></a>

### 3.2 Target Architecture (Dual Mode)

<a href="sidecar-target-architecture.png"><img src="sidecar-target-architecture.png" width="600" alt="Target Architecture (Dual Mode) — click to enlarge"></a>

*Click image to enlarge. Source: [sidecar-target-architecture.drawio](sidecar-target-architecture.drawio)*

<a id="33-interception-strategy-pattern"></a>

### 3.3 Interception Strategy Pattern

<a href="sidecar-strategy-pattern.png"><img src="sidecar-strategy-pattern.png" width="600" alt="Interception Strategy Pattern — click to enlarge"></a>

*Click image to enlarge. Source: [sidecar-strategy-pattern.drawio](sidecar-strategy-pattern.drawio)*

Each concrete strategy knows how to:
1. Transform a build command into an instrumented build command
2. Supply environment variables needed for instrumentation
3. Generate ADG documents from the tracer's output

The pipeline selects the strategy based on `config.yaml`:

```yaml
omnibor:
  mode: sidecar            # or "standalone"
  # Strategy auto-selected: sidecar → WrapperStrategy
  #                          standalone → PtraceStrategy

# Per-repo override (for hermetic builds, see Section 4.2):
repos:
  my-bazel-project:
    interception: ptrace   # Forces PtraceStrategy regardless of mode
```

**Strategy resolution order:** per-repo `interception` override >
global `mode` > default (`standalone`). This ensures hermetic build
systems (Bazel, Nix, Yocto) can fall back to ptrace on a per-project
basis without affecting other projects.

---

<a id="4-cross-cutting-infrastructure-changes"></a>

## 4. Cross-Cutting Infrastructure Changes

These changes are language-independent and must be implemented first.
They form the foundation on which all per-language sidecar support is built.

<a id="41-commandrunner--environment-variable-support"></a>

### 4.1 CommandRunner — Environment Variable Support

**Current state:** `CommandRunner.run()` accepts `cmd` and `cwd` only.
Environment variables must be embedded in the command string.

**Required change:** Add an `env` parameter that merges with `os.environ`:

```python
# app/runner.py — proposed change
class CommandRunner:
    def run(self, cmd, cwd=None, description="", env=None):
        run_env = os.environ.copy()
        if env:
            run_env.update(env)
        result = subprocess.run(
            cmd, shell=True, cwd=cwd, env=run_env, ...
        )
```

**Effort:** 0.5 days. **Risk:** None — additive change, `env=None` preserves
existing behavior.

**Why this matters:** Sidecar mode for C/C++ requires `CC=`, `CXX=`, `AR=`,
`LD=` injection. For Rust, `RUSTC_WRAPPER=`. For Go, the `-toolexec` flag is
embedded in the command, but `GOROOT` may need to be set. Without `env`
support, these must be awkwardly prepended to the command string.

<a id="42-config-schema--mode-selection"></a>

### 4.2 Config Schema — Mode Selection

**Current state:** `config.yaml` has per-language `omnibor` sections with
hardcoded tracer references (`bomtrace3`, `bomtrace2`).

**Proposed schema extension:**

```yaml
# Top-level mode selector — applies to all languages unless overridden
mode: standalone    # "standalone" (default) or "sidecar"

# Per-language config gains mode-aware fields
omnibor:
  # Standalone mode (existing — unchanged)
  standalone:
    tracer: bomtrace3
    raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1
    create_bom_script: bomsh_create_bom.py
  # Sidecar mode (new)
  sidecar:
    wrappers:
      cc: /opt/omnibor/gcc-wrapper
      cxx: /opt/omnibor/g++-wrapper
      ar: /opt/omnibor/ar-wrapper
      ld: /opt/omnibor/ld-wrapper
      as: /opt/omnibor/as-wrapper
      ranlib: /opt/omnibor/ranlib-wrapper
    raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1
    create_bom_script: bomsh_create_bom.py

omnibor_go:
  standalone:
    tracer: bomtrace2 -c /opt/bomsh/bin/bomtrace_go.conf
    raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1
    create_bom_script: bomsh_create_bom.py
  sidecar:
    toolexec: /opt/omnibor/go-wrapper
    raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1
    create_bom_script: bomsh_create_bom.py

omnibor_rust:
  standalone:
    tracer: bomtrace2
    raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1
    create_bom_script: bomsh_create_bom.py
  sidecar:
    rustc_wrapper: /opt/omnibor/rustc-wrapper
    raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1
    create_bom_script: bomsh_create_bom.py

# Java and Python are mode-agnostic (same behavior in both modes)
omnibor_java:
  strace_opts: -f -s99999 --seccomp-bpf -e trace=openat -qqq
  create_bom_script: bomsh_create_bom_java.py
  strace_logfile: /tmp/strace_java_logfile

omnibor_python:
  # No tracer — metadata-only analysis
  create_bom_script: null

# ── Per-Repo Overrides ──────────────────────────────────────
# Any repo can override the global interception strategy.
# This is required for hermetic builds (Bazel, Nix, Yocto)
# where wrapper-based strategies do not work.
repos:
  curl:
    # Standard project — uses global mode (sidecar/standalone)
    build_steps:
      - ./configure --with-openssl
      - make -j$(nproc)

  my-bazel-project:
    language: c-cpp
    build_system: bazel          # Informational — logged in SPDX
    interception: ptrace         # Override: use bomtrace3 regardless of mode
    build_steps:
      - bazel build //...

  my-ccache-project:
    language: c-cpp
    wrapper_chain:               # Chaining: OmniBOR → ccache → real compiler
      - ccache                   # Existing wrapper to delegate through
    build_steps:
      - make -j$(nproc)
```

**Per-repo `interception` override** allows falling back to ptrace for
projects where wrappers don't work. The `build_system` field is recorded
in the SPDX `creationInfo` comment for traceability. The `wrapper_chain`
field tells `CcWrapperStrategy` to delegate through existing wrappers
(see Section 4.5) instead of calling the compiler directly.

**Backward compatibility:** A new `config.py` function resolves the
mode-aware config:

```python
def resolve_omnibor_cfg(config, language):
    """Return the active omnibor config for a language.

    If the config uses the new nested standalone/sidecar
    format, selects based on config["mode"]. If the config
    uses the legacy flat format, returns it directly.
    """
    mode = config.get("mode", "standalone")
    section = _lang_omnibor_key(language)
    cfg = config[section]
    if "standalone" in cfg or "sidecar" in cfg:
        return cfg.get(mode, cfg.get("standalone"))
    return cfg  # Legacy flat format
```

**Effort:** 2 days. **Risk:** Low — fallback to flat format means existing
configs work unchanged.

<a id="43-package-resolver-abstraction"></a>

### 4.3 Package Resolver Abstraction

**Current state:** `collect_metadata.py` (bomsh script) hardcodes
`dpkg-query`. `ComponentResolver._make_purl()` hardcodes `pkg:deb/ubuntu/`.

**Design:**

```python
# app/spdx/package_resolver.py (new file)
from abc import ABC, abstractmethod

class PackageResolver(ABC):
    """Resolves file paths to OS package metadata."""

    @abstractmethod
    def resolve(self, file_path):
        """Return package metadata for a file, or None."""
        ...

    @abstractmethod
    def purl_scheme(self):
        """Return PURL scheme string, e.g. 'pkg:deb/ubuntu'."""
        ...

class DpkgResolver(PackageResolver):
    """Debian/Ubuntu: dpkg-query -S"""
    def purl_scheme(self): return "pkg:deb/ubuntu"

class RpmResolver(PackageResolver):
    """RHEL/CentOS/Fedora: rpm -qf"""
    def purl_scheme(self): return "pkg:rpm/rhel"

class ApkResolver(PackageResolver):
    """Alpine: apk info --who-owns"""
    def purl_scheme(self): return "pkg:apk/alpine"

def auto_detect_resolver():
    """Detect distro and return the appropriate resolver."""
    # Check /etc/os-release or run lsb_release
```

**Why this is the #1 enterprise blocker:** Without multi-distro package
resolution, sidecar mode on RHEL/CentOS (the most common enterprise Linux)
produces no system library metadata.

**Effort:** 3–4 days (3 implementations + auto-detection + tests).
**Risk:** Medium — each distro has edge cases in package naming.

<a id="44-path-abstraction-layer"></a>

### 4.4 Path Abstraction Layer

**Current state:** 14 hardcoded container-specific paths (inventoried in
Appendix A.9 of the sidecar refactoring plan).

**Design:** Move all paths into `config.yaml` with sensible defaults:

```yaml
paths:
  repos_dir: /workspace/repos       # Override in sidecar mode
  output_dir: /workspace/output
  bomsh_dir: /opt/bomsh             # Or /opt/omnibor in sidecar
  go_root: /usr/local/go            # Or auto-detect from $GOROOT
  cargo_home: null                  # null = auto-detect from $CARGO_HOME
```

And in the code, resolve paths at startup:

```python
# app/config.py — path resolution
def resolve_paths(config):
    """Resolve paths from config, env vars, and auto-detection."""
    paths = config["paths"]
    paths["go_root"] = (
        paths.get("go_root")
        or os.environ.get("GOROOT", "/usr/local/go")
    )
    paths["cargo_home"] = (
        paths.get("cargo_home")
        or os.environ.get("CARGO_HOME", os.path.expanduser("~/.cargo"))
    )
    return paths
```

**Effort:** 2 days. **Risk:** Low — environment variables are the
industry-standard way to discover toolchain paths.

<a id="45-interception-strategy-interface"></a>

### 4.5 Interception Strategy Interface

**Design:**

```python
# app/pipeline/interception.py (new file)
from abc import ABC, abstractmethod

class InterceptionStrategy(ABC):
    """Defines how a build is instrumented for OmniBOR tracing."""

    @abstractmethod
    def instrument_command(self, build_cmd, repo_dir):
        """Transform a build command into an instrumented one.

        Returns (instrumented_cmd, env_vars_dict).
        """
        ...

    @abstractmethod
    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        """Run post-build ADG generation.

        Returns True on success.
        """
        ...

class PtraceStrategy(InterceptionStrategy):
    """Standalone mode: bomtrace3/bomtrace2 prefix."""

    def instrument_command(self, build_cmd, repo_dir):
        return f"{self.tracer} {build_cmd}", {}

class CcWrapperStrategy(InterceptionStrategy):
    """Sidecar C/C++: CC=/CXX=/AR=/LD= environment variables.

    Supports wrapper chaining: if the repo config specifies
    ``wrapper_chain: [ccache]``, the wrapper delegates through
    ccache before calling the real compiler.
    """

    def instrument_command(self, build_cmd, repo_dir):
        env = {
            "CC": self.wrappers["cc"],
            "CXX": self.wrappers["cxx"],
            "AR": self.wrappers["ar"],
            "LD": self.wrappers["ld"],
        }
        # If the repo uses ccache/distcc, tell the wrapper to chain
        if self.wrapper_chain:
            env["OMNIBOR_DELEGATE"] = " ".join(self.wrapper_chain)
        return build_cmd, env

class GoToolexecStrategy(InterceptionStrategy):
    """Sidecar Go: -toolexec flag injection."""

    def instrument_command(self, build_cmd, repo_dir):
        # Inject -toolexec into 'go build' command.
        # NOTE: build_steps config entries MUST contain exactly one
        # 'go build' invocation per entry.  If the command contains
        # multiple 'go build' calls, split them into separate steps.
        return build_cmd.replace(
            "go build", f"go build -toolexec={self.toolexec}",
            1  # Replace only the first occurrence
        ), {}

class RustcWrapperStrategy(InterceptionStrategy):
    """Sidecar Rust: RUSTC_WRAPPER env var."""

    def instrument_command(self, build_cmd, repo_dir):
        return build_cmd, {
            "RUSTC_WRAPPER": self.rustc_wrapper
        }

class StraceStrategy(InterceptionStrategy):
    """Java: strace openat wrapping (both modes)."""
    # Already sidecar-compatible — same in both modes.

class MetadataOnlyStrategy(InterceptionStrategy):
    """Python: no build tracing, pip metadata only."""

    def instrument_command(self, build_cmd, repo_dir):
        return build_cmd, {}  # No instrumentation

    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        return True  # ADG comes from pip metadata, not build tracing
```

**Builder refactoring:** `BomtraceBuilder.build()` delegates to the strategy:

```python
# app/pipeline/builder.py — refactored
def build(self, repo_name, repo_cfg, paths_cfg, omnibor_cfg,
          strategy=None, run_ts=None):
    ...
    make_cmd = build_steps[-1]
    instrumented, env_vars = strategy.instrument_command(
        make_cmd, repo_dir
    )
    rc = self.runner.run(
        instrumented, cwd=str(repo_dir), env=env_vars, ...
    )
    if rc != 0:
        return False
    return strategy.generate_adg(
        repo_dir, bom_dir, omnibor_cfg
    )
```

**Effort:** 3 days. **Risk:** Low — `PtraceStrategy` preserves exact
existing behavior.

---

<a id="5-per-language-refactoring-java"></a>

## 5. Per-Language Refactoring: Java

### 5.1 Current State

| Component | File | Status |
|-----------|------|--------|
| Pipeline runner | `lang_runners.py:167–387` | `run_java_pipeline()` + `generate_java_adg_spdx()` |
| Builder | `builder.py:114–222` | `strace {opts} -o {log} {build_cmd}` |
| SPDX generator | `java_generator.py` | Full Maven/Gradle support |
| Maven parser | `maven_parser.py` | `mvn dependency:tree` |
| Gradle parser | `gradle_parser.py` | `./gradlew dependencies` |

### 5.2 Current Sidecar Readiness: Already There

Java is **already sidecar-compatible** — the strace+Maven/Gradle approach
works with whatever JDK is on PATH. No wrappers needed. No bomtrace.

### 5.3 Optional Optimization: Replace strace with Maven dep:tree

This is an optimization, not a requirement for sidecar mode:

**Current:** `strace -e trace=openat mvn package` (requires `SYS_PTRACE`)
**Proposed:** `mvn package` + `mvn dependency:tree` (no ptrace needed)

This removes the last `SYS_PTRACE` requirement for Java, reducing
overhead from 5–17% to <2%.

**Accuracy caveat:** `mvn dependency:tree` reports the *declared*
dependency graph, which may diverge from the *actual* runtime classpath:

- **Maven shade plugin** bundles transitive dependencies into the uber-JAR
  without Maven knowing the final set. Dependencies relocated via shade
  may appear as separate packages in dep:tree but exist only as renamed
  classes in the JAR.
- **Maven profiles** (`-P production`) can activate/deactivate
  dependencies. dep:tree output depends on which profiles are active.
- **Optional dependencies** may or may not be present at runtime.

dep:tree is still the best available metadata source (and matches the
pattern used by CycloneDX Maven Plugin). The pipeline should log a
warning when shade or assembly plugins are detected, noting that the
SPDX may not perfectly reflect the uber-JAR contents.

**Implementation:**

```python
class MavenDepTreeStrategy(StraceStrategy):
    """Java: Maven dependency:tree instead of strace."""

    def instrument_command(self, build_cmd, repo_dir):
        return build_cmd, {}  # No strace prefix

    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        # Run: mvn dependency:tree -DoutputType=dot
        # Parse output into treedb-compatible format
        # Run: bomsh_create_bom_java.py for class→source mapping
        ...
```

### 5.4 Effort Summary

| Work Item | Effort | Owner |
|-----------|--------|-------|
| Core sidecar support | 0 days | Already works |
| Maven dep:tree optimization | 3–4 days | omnibor-analysis |
| Gradle dep:tree optimization | 2–3 days | omnibor-analysis |
| Remove strace dependency (optional) | 1 day | omnibor-analysis |
| Integration tests | 1 day | omnibor-analysis |
| **Total (required for sidecar)** | **0** | |
| **Total (with optimization)** | **~1.5 weeks** | |

### 5.5 ROI Assessment

| Factor | Score |
|--------|-------|
| **Enterprise demand** | High — Java is everywhere |
| **Performance gain** | Low — already 5–17%, optimization saves ~3–15% |
| **Platform unlock** | Medium — removes SYS_PTRACE for Java |
| **Dependency on upstream** | None |
| **Recommendation** | **Priority 1** — already sidecar-compatible; first language for enterprise pilot. Optimization removes SYS_PTRACE requirement. |

---

<a id="6-per-language-refactoring-cc"></a>

## 6. Per-Language Refactoring: C/C++

### 6.1 Current State

| Component | File | Status |
|-----------|------|--------|
| Pipeline runner | `lang_runners.py:20–89` | `run_c_cpp_pipeline()` — calls `builder.build()` |
| Builder | `builder.py:26–112` | `{tracer} {make_cmd}` prefix pattern |
| ADG parser | `parser.py` | Classifies by `/usr/lib`, `/usr/include` paths |
| SPDX emitter | `emitter.py:506–547` | Adds GCC as BUILD_TOOL_OF unconditionally |
| Metadata | `metadata_collector.py` | dpkg-query only |
| Config | `config.yaml` omnibor section | `tracer: bomtrace3` |

### 6.2 Required Changes

**Upstream bomsh (new deliverables):**

| Deliverable | Language | Lines (est.) | Purpose |
|-------------|----------|--------------|---------|
| `gcc-wrapper` | C | ~200 | Hash inputs/outputs, call real gcc |
| `g++-wrapper` | C | ~200 | Same for C++ |
| `ar-wrapper` | C | ~150 | Archive creation tracking |
| `ld-wrapper` | C | ~200 | Link-step tracking |
| `as-wrapper` | C | ~150 | Assembly compilation tracking |
| `ranlib-wrapper` | C | ~100 | Archive index tracking |

Each wrapper:
1. Locates the real tool via `PATH` (skipping itself)
2. Records argv to raw_logfile
3. Calls the real tool with `exec`
4. On return: hashes output file(s), writes raw_logfile entry
5. For `gcc-wrapper`: reads `-MD` dependency output for header tracking

**omnibor-analysis changes:**

| File | Change | Effort |
|------|--------|--------|
| `runner.py` | Add `env` parameter | 0.5 days |
| `builder.py` | Accept `InterceptionStrategy`, delegate | 1 day |
| `lang_runners.py` | Construct `CcWrapperStrategy` or `PtraceStrategy` based on config | 0.5 days |
| `config.yaml` | Add `omnibor.sidecar` section with wrapper paths | 0.5 days |
| `metadata_collector.py` | Use `PackageResolver` instead of hardcoded dpkg | 1 day |
| `resolver.py` | Use `PackageResolver.purl_scheme()` | 0.5 days |
| `emitter.py` | Add compiler info from strategy (not hardcoded GCC) | 1 day |

### 6.3 Effort Summary

| Work Item | Effort | Owner |
|-----------|--------|-------|
| Wrapper binaries (upstream bomsh) | 2–3 weeks | bomsh team |
| Strategy implementation | 2 days | omnibor-analysis |
| Package resolver (shared) | 3–4 days | omnibor-analysis |
| Config + plumbing | 2 days | omnibor-analysis |
| Integration tests | 2 days | omnibor-analysis |
| **Total (omnibor-analysis only)** | **~2 weeks** | |
| **Total (including upstream)** | **~5 weeks** | |

### 6.4 ROI Assessment

| Factor | Score |
|--------|-------|
| **Enterprise demand** | High — C/C++ is the primary enterprise use case |
| **Performance gain** | Moderate — 20–60% → 3–5% overhead reduction |
| **Platform unlock** | High — wrappers enable ARM64 without bomtrace3 porting |
| **Dependency on upstream** | High — wrappers must exist in bomsh first |
| **Recommendation** | **Priority 2** — second pilot language for engineering teams; implement immediately after Java infrastructure |

---

<a id="7-per-language-refactoring-go"></a>

## 7. Per-Language Refactoring: Go

### 7.1 Current State

| Component | File | Status |
|-----------|------|--------|
| Pipeline runner | `lang_runners.py:394–460` | `run_go_pipeline()` |
| Builder | `builder.py:26–112` | `bomtrace2 -c bomtrace_go.conf {cmd}` |
| ADG parser | `parser.py:51` | Hardcoded `/usr/local/go/src/` |
| SPDX emitter | `emitter.py:413–504` | Go stdlib, go.mod, modules.txt |
| Lang parsers | `lang_parsers.py:118` | `/usr/local/go/VERSION` hardcoded |
| Config | `config.yaml` omnibor_go | `tracer: bomtrace2 -c ...` |

### 7.2 Required Changes

**Upstream bomsh (new deliverable):**

| Deliverable | Language | Lines (est.) | Purpose |
|-------------|----------|--------------|---------|
| `go-wrapper` | Go | ~500 | `-toolexec` compatible wrapper |

The Go wrapper is invoked by `go build -toolexec=<wrapper>`. It receives
the full tool command as arguments (e.g., `go-wrapper /usr/local/go/pkg/tool/linux_amd64/compile -o output.a -p main source.go`).

The wrapper:
1. Records argv (especially input `.go` files and output `.a`/binary)
2. Calls the real tool
3. Hashes output file(s)
4. Writes raw_logfile entry
5. Handles both `compile` and `link` tool invocations

**omnibor-analysis changes:**

| File | Change | Effort |
|------|--------|--------|
| `lang_runners.py` | Construct `GoToolexecStrategy` in sidecar mode | 0.5 days |
| `config.yaml` | Add `omnibor_go.sidecar` section | 0.5 days |
| `parser.py` | Replace `/usr/local/go/src/` with configurable `go_root` | 0.5 days |
| `lang_parsers.py` | Replace `/usr/local/go/VERSION` with `$GOROOT/VERSION` | 0.5 days |
| `emitter.py` | Use configurable Go stdlib source path | 0.5 days |

### 7.3 The `-a` Problem — Phased Mitigation

The Go `-a` flag forces full rebuild (~100–200% overhead). This is a known
limitation with a three-phase mitigation:

**Phase A (immediate):** Accept `-a` penalty. Still a major improvement
over bomtrace2 (150–400% → ~100–200%).

**Phase B (medium-term):** Derive third-party module SBOMs from `go.sum` +
`$GOPATH/pkg/mod/cache/`. Only trace first-party packages with `-a`:

```python
class GoHybridStrategy(GoToolexecStrategy):
    """Trace first-party, read go.sum for third-party."""

    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        # 1. Parse go.sum for third-party module checksums
        # 2. Parse vendor/modules.txt for versions
        # 3. Only the wrapper output covers first-party code
        # 4. Merge into unified ADG
        ...
```

**Phase C (future — contingent on Go issue #41145):**
If Go implements `-toolexec` cache integration, the wrapper can participate
in the build cache. This eliminates the `-a` requirement entirely.

**Extensibility point:** The strategy interface makes it trivial to swap
Phase A → B → C implementations by changing the config:

```yaml
omnibor_go:
  sidecar:
    strategy: go_toolexec_hybrid  # Phase B
    # strategy: go_toolexec        # Phase A
    # strategy: go_toolexec_cached  # Phase C (future)
```

### 7.4 Effort Summary

| Work Item | Effort | Owner |
|-----------|--------|-------|
| Wrapper binary (upstream bomsh) | 2–3 weeks | bomsh team |
| Strategy implementation (Phase A) | 1.5 days | omnibor-analysis |
| Path abstraction (go_root, etc.) | 1.5 days | omnibor-analysis |
| Config + plumbing | 1 day | omnibor-analysis |
| Phase B hybrid strategy | 3–4 days | omnibor-analysis |
| Integration tests | 2 days | omnibor-analysis |
| **Total Phase A (omnibor-analysis)** | **~1.5 weeks** | |
| **Total Phase A+B (omnibor-analysis)** | **~2.5 weeks** | |
| **Total (including upstream)** | **~5.5 weeks** | |

### 7.5 ROI Assessment

| Factor | Score |
|--------|-------|
| **Enterprise demand** | High — Go is dominant for cloud-native |
| **Performance gain** | Highest — bomtrace2 150–400% → wrapper 10–15% on top of forced rebuild. **Note:** total overhead vs. a normal cached build is 100–215% because `-a` forces full rebuild; the 10–15% is the wrapper's marginal cost. Phase B reduces total overhead by deriving third-party from `go.sum`. |
| **Platform unlock** | High — `-toolexec` works on ARM64 |
| **Dependency on upstream** | High — Go wrapper is the most complex wrapper |
| **Recommendation** | **Priority 3** — highest overhead improvement but complex; schedule after C/C++ |

---

<a id="8-per-language-refactoring-rust"></a>

## 8. Per-Language Refactoring: Rust

### 8.1 Current State

| Component | File | Status |
|-----------|------|--------|
| Pipeline runner | `lang_runners.py:96–160` | `run_rust_pipeline()` |
| Builder | `builder.py:26–112` | Same `{tracer} {make_cmd}` pattern |
| ADG parser | `parser.py` | Detects `/.cargo/registry/src/` |
| SPDX emitter | `emitter.py:596–690` | Rust crate detection, STATIC_LINK |
| Lang parsers | `lang_parsers.py` | `_CARGO_REGISTRY_RE` hardcoded |
| Config | `config.yaml` omnibor_rust | `tracer: bomtrace2` |

### 8.2 Required Changes

**Upstream bomsh (new deliverable):**

| Deliverable | Language | Lines (est.) | Purpose |
|-------------|----------|--------------|---------|
| `rustc-wrapper` | Rust | ~300 | Wrap `rustc`, hash .rlib/.so outputs |

The Rust wrapper receives `rustc <args>` from Cargo (Cargo passes the
real `rustc` path as the first argument). The wrapper:
1. Records argv
2. Calls real `rustc`
3. Hashes output `.rlib`, `.so`, or binary
4. Writes raw_logfile entry

**omnibor-analysis changes:**

| File | Change | Effort |
|------|--------|--------|
| `lang_runners.py` | Construct `RustcWrapperStrategy` in sidecar mode | 0.5 days |
| `config.yaml` | Add `omnibor_rust.sidecar` section | 0.5 days |
| `lang_parsers.py` | Make `_CARGO_REGISTRY_RE` configurable via `$CARGO_HOME` | 0.5 days |

### 8.3 Optimization: `RUSTC_WORKSPACE_WRAPPER`

In a second pass, use `RUSTC_WORKSPACE_WRAPPER` for workspace crates
+ derive third-party info from `Cargo.lock`. This avoids wrapping
~85% of crate compilations:

```python
class RustcWorkspaceWrapperStrategy(RustcWrapperStrategy):
    """Wraps only workspace crates; reads Cargo.lock for third-party."""

    def instrument_command(self, build_cmd, repo_dir):
        return build_cmd, {
            "RUSTC_WORKSPACE_WRAPPER": self.rustc_wrapper
        }

    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        # Generate ADG from wrapper output (workspace crates)
        # + supplement with Cargo.lock metadata (third-party)
        ...
```

### 8.4 Effort Summary

| Work Item | Effort | Owner |
|-----------|--------|-------|
| Wrapper binary (upstream bomsh) | 1–2 weeks | bomsh team |
| Strategy implementation | 1 day | omnibor-analysis |
| Config + path fixes | 1 day | omnibor-analysis |
| RUSTC_WORKSPACE_WRAPPER optimization | 2–3 days | omnibor-analysis |
| Integration tests | 1 day | omnibor-analysis |
| **Total (omnibor-analysis only)** | **~1.5 weeks** | |
| **Total (including upstream)** | **~3.5 weeks** | |

### 8.5 ROI Assessment

| Factor | Score |
|--------|-------|
| **Enterprise demand** | Medium — growing Rust adoption |
| **Performance gain** | High — 100–250% → 5–10% overhead reduction |
| **Platform unlock** | High — RUSTC_WRAPPER works on ARM64 |
| **Dependency on upstream** | Medium — single wrapper binary |
| **Build cache** | Rust uses a build cache (`target/` directory). Cached crates are not recompiled, so `RUSTC_WRAPPER` does not see them on subsequent builds. Unlike Go, this is manageable: `Cargo.lock` provides complete dependency metadata (versions, checksums) for all crates, so the SBOM is complete from metadata even when the wrapper misses cached crates. For first-party code hashing, run `cargo clean` before traced builds or accept that only changed crates are hashed. |
| **Simplicity** | Highest of all languages — no forced-rebuild requirement (unlike Go `-a`), no daemon issues |
| **Recommendation** | **Priority 4** — cleanest implementation, fastest win once Go/C++ infrastructure exists |

---

<a id="9-per-language-refactoring-python-new"></a>

## 9. Per-Language Refactoring: Python (New)

### 9.1 Current State

**Nothing exists.** No pipeline runner, no SPDX generator, no config entry.
Analysis document exists: `docs/deep-dive/python-omnibor-support-analysis.md`.

### 9.2 Design

Python SBOM generation is **metadata-only** — no compilation tracing for
pure Python packages. The data sources are:

| Source | What It Provides |
|--------|-----------------|
| `pip freeze` | Installed package names + exact versions |
| `importlib.metadata` | Per-package: name, version, license, dependencies |
| `dist-info/RECORD` | SHA-256 hash of every installed file |
| `dist-info/METADATA` | `Requires-Dist:` for dependency graph |
| `pyproject.toml` / `requirements.txt` | Direct vs. transitive classification |
| `pipdeptree --json` | Full dependency tree with hierarchy |

### 9.3 New Files

| New File | Lines (est.) | Purpose |
|----------|-------------|---------|
| `app/spdx/python_generator.py` | ~400 | `PythonSpdxGenerator` — generates SPDX from pip metadata |
| `app/spdx/python_parser.py` | ~200 | Parse `RECORD`, `METADATA`, `requirements.txt`, `pyproject.toml` |
| `app/pipeline/lang_runners.py` addition | ~80 | `run_python_pipeline()` |

### 9.4 PythonSpdxGenerator Design

```python
class PythonSpdxGenerator:
    """Generate SPDX 2.3 JSON for Python projects.

    Uses pip metadata instead of build tracing.
    Produces per-package SPDX packages with:
      - pkg:pypi/ PURLs
      - SHA-256 checksums from RECORD files
      - DEPENDS_ON relationships from Requires-Dist
      - Direct vs. transitive classification from
        requirements.txt / pyproject.toml
    """

    def generate(self, output_path, venv_path,
                 requirements_file=None, sbom_type="build"):
        # 1. Enumerate installed packages via importlib.metadata
        # 2. Parse RECORD for file hashes
        # 3. Parse Requires-Dist for dependency graph
        # 4. Classify direct vs. transitive
        # 5. Emit SPDX 2.3 JSON
        ...
```

### 9.5 C Extension Handling

For Python packages with C extensions (numpy, cryptography, etc.),
add optional strace tracing during `pip install`:

```yaml
omnibor_python:
  trace_c_extensions: true  # Optional: strace pip install
  strace_opts: -f -s99999 --seccomp-bpf -e trace=openat -qqq
```

This reuses the existing `StraceStrategy` from Java. The C compilation
events are merged into the Python SBOM.

### 9.6 Effort Summary

| Work Item | Effort | Owner |
|-----------|--------|-------|
| `python_parser.py` (RECORD, METADATA, requirements) | 3–4 days | omnibor-analysis |
| `python_generator.py` (SPDX generation) | 4–5 days | omnibor-analysis |
| `run_python_pipeline()` + config | 2 days | omnibor-analysis |
| C extension strace integration | 2 days | omnibor-analysis |
| Unit tests (≥95% coverage) | 3 days | omnibor-analysis |
| Integration tests (real projects) | 2 days | omnibor-analysis |
| **Total** | **~3.5 weeks** | |

### 9.7 ROI Assessment

| Factor | Score |
|--------|-------|
| **Enterprise demand** | High — Python is #1 for ML/AI, cloud automation |
| **Performance gain** | N/A — no existing baseline |
| **Platform unlock** | N/A — metadata-only, inherently cross-platform |
| **Dependency on upstream** | Low — minimal bomsh involvement |
| **Simplicity** | High — metadata-only, no wrappers needed |
| **Recommendation** | **Priority 4** — high demand but not in initial pilot; low upstream dependency allows flexible scheduling |

---

<a id="10-upstream-bomsh-changes"></a>

## 10. Upstream bomsh Changes

All wrapper binaries are **upstream bomsh deliverables**. They must be
written in their target language for minimal startup overhead.

### 10.1 Deliverables

| Wrapper | Language | Est. Lines | Raw Logfile Compat. | Priority |
|---------|----------|-----------|---------------------|----------|
| `gcc-wrapper` | C | ~200 | Must write `bomsh_hook_raw_logfile` format | P1 |
| `g++-wrapper` | C | ~200 | Same as gcc-wrapper | P1 |
| `ar-wrapper` | C | ~150 | Same format | P1 |
| `ld-wrapper` | C | ~200 | Same format | P1 |
| `as-wrapper` | C | ~150 | Same format | P1 |
| `ranlib-wrapper` | C | ~100 | Same format | P1 |
| `go-wrapper` | Go | ~500 | Must write `bomsh_hook_raw_logfile` format | P2 |
| `rustc-wrapper` | Rust | ~300 | Must write `bomsh_hook_raw_logfile` format | P2 |

### 10.2 Critical Requirement: Raw Logfile Format Compatibility

All wrappers MUST write the same raw logfile format that bomtrace3 writes.
This ensures `bomsh_create_bom.py` can consume wrapper output identically
to bomtrace3 output. The downstream pipeline (`parser.py`, `emitter.py`,
`generator.py`) does not need to know which tracing mechanism was used.

The raw logfile SHOULD include a format version header (e.g.,
`#omnibor-rawlog-v1`) so that future format changes can be detected.
This enables `bomsh_create_bom.py` to support both old and new formats
during migration.

### 10.3 Wrapper Implementation Requirements

**Concurrent write safety:** Under `make -j64`, 64 wrapper processes
write to the same raw logfile simultaneously. The wrapper MUST use
`O_APPEND` mode for all writes and keep each record ≤`PIPE_BUF` (4096
bytes on Linux) to ensure atomic appends without file locking. If a
record exceeds `PIPE_BUF`, the wrapper MUST use `flock()` or write to a
per-process file (`raw_logfile.$PID`) that `bomsh_create_bom.py` merges
post-build.

**Real compiler discovery:** The wrapper must find the real compiler on
`PATH` while skipping itself. Algorithm (following ccache's approach):

1. Get own absolute path via `/proc/self/exe` (Linux) or `realpath(argv[0])`
2. Search each directory in `PATH` for the tool name (e.g., `gcc`)
3. For each candidate, resolve symlinks and compare inodes
4. Return the first candidate whose inode differs from the wrapper's
5. If no candidate found, exit with error: "real compiler not found on PATH"

This handles symlinks, wrapper chains, and non-standard install paths.

**Build environment isolation:** Per Principle P7, the wrapper MUST NOT:
- Modify `argv` before passing to the real compiler
- Set or unset environment variables visible to the compiler
- Write to stdout/stderr (compiler warnings/errors must pass through)
- Return a different exit code than the real compiler returned

### 10.4 Modifications to Existing bomsh Scripts

| Script | Change | Why |
|--------|--------|-----|
| `bomsh_create_bom.py` | Accept `--wrapper-mode` flag | Skip ptrace-specific fields in raw logfile parsing |
| `bomsh_hook2.py` | No change needed | Not used in sidecar mode |
| `bomsh_sbom.py` | No change needed | Consumes treedb, not raw logfile |

### 10.5 Timeline Dependency

The **C/C++ wrappers** are on the critical path for Phase 1 — C/C++ is
the second pilot language for engineering teams. Java requires no upstream
wrapper changes (strace + Maven dep:tree). The **Go and Rust wrappers**
can follow in Phase 2. Python requires no upstream changes.

---

<a id="11-effort-estimates-and-roi-analysis"></a>

## 11. Effort Estimates and ROI Analysis

### 11.1 Summary Table (ordered by pilot priority)

| Language | omnibor-analysis Effort | Upstream bomsh Effort | Total | Overhead Reduction | Pilot Priority |
|----------|------------------------|----------------------|-------|--------------------|---------------|
| **Java** | 1.5 weeks | 0 | 1.5 weeks | 5–17% → <2%; removes `SYS_PTRACE` | **#1 — first pilot** |
| **C/C++** | 2 weeks | 2–3 weeks | 5 weeks | 20–60% → 3–5% | **#2 — second pilot** |
| **Infrastructure** | 2 weeks | 0 | 2 weeks | Blocks Java + C/C++ on RHEL | **Prerequisite** |
| **Go** | 2.5 weeks | 2–3 weeks | 5.5 weeks | 150–400% → 10–15% | #3 |
| **Rust** | 1.5 weeks | 1–2 weeks | 3.5 weeks | 100–250% → 5–10% | #4 |
| **Python** | 3.5 weeks | 0 | 3.5 weeks | N/A (new capability) | #5 |
| **Total** | **~14 weeks** | **~7 weeks** | **~21 weeks** | | |

### 11.2 Priority Ranking (enterprise adoption order)

```
Priority = Enterprise Pilot Demand first, then ROI

1. Infrastructure ......... ████████████████████ (PREREQUISITE)
   - Package resolver, config schema, dual-mode Docker
   - Blocks BOTH pilot languages on enterprise distros (RHEL)
   - 2 weeks — must be first

2. Java optimization ...... ███████████████████  (first pilot language)
   - Already sidecar-compatible via strace
   - Maven dep:tree removes SYS_PTRACE (enterprise security blocker)
   - 1.5 weeks, zero upstream dependency

3. C/C++ sidecar .......... ██████████████████   (second pilot language)
   - CC= wrappers are industry-standard (ccache, distcc, Coverity)
   - Unlocks ARM64 and removes SYS_PTRACE
   - 5 weeks (2 wks omnibor-analysis + 2-3 wks upstream wrappers)

4. Go sidecar ............. ███████████████      (highest overhead win)
   - Largest absolute overhead reduction (150-400% → 10-15%)
   - Not in initial pilot — schedule after C/C++

5. Rust sidecar ........... ██████████████       (cleanest implementation)
   - No -a problem, single wrapper binary
   - Not in initial pilot — can run in parallel with Go

6. Python (new) ........... █████████████        (new capability)
   - No upstream dependency, high demand for ML/AI teams
   - Can be scheduled any time — no blockers
```

### 11.3 Critical Path

<a href="sidecar-critical-path.png"><img src="sidecar-critical-path.png" width="600" alt="Phased Implementation Critical Path — click to enlarge"></a>

*Click image to enlarge. Source: [sidecar-critical-path.drawio](sidecar-critical-path.drawio)*

---

<a id="12-phased-implementation-plan"></a>

## 12. Phased Implementation Plan

### Phase 1: Infrastructure + Java Pilot (Weeks 1–4)

**Goal:** Java sidecar mode production-ready on RHEL. No `SYS_PTRACE` required.

This phase has three parallel tracks with no dependencies between them,
allowing maximum parallelism. All three are prerequisites for the Java
pilot with engineering teams.

| Week | Track A: Package Resolver | Track B: Java Optimization | Track C: Config + Docker |
|------|--------------------------|---------------------------|-------------------------|
| 1 | `PackageResolver` interface + `DpkgResolver` | Java Maven `dep:tree` replacing strace | `runner.py` env support + tests |
| 1–2 | `RpmResolver` + `ApkResolver` | Gradle `dep:tree` support | Config schema mode selection |
| 2–3 | Refactor `metadata_collector.py` | Integration tests: Java without strace | `InterceptionStrategy` interface |
| 3 | Refactor `resolver.py` for distro PURLs | Java on RHEL integration tests | Dual-mode Dockerfile |
| 4 | RPM/Alpine validation | **Java pilot on RHEL: READY** | Sidecar image published |

| Branch | Scope |
|--------|-------|
| `feat/package-resolver` | Track A: all resolver work |
| `feat/java-dep-tree` | Track B: Maven/Gradle dep:tree |
| `feat/config-mode-schema` | Track C: config, runner, strategy interface |
| `feat/dual-mode-docker` | Track C: Dockerfile |

**Deliverables:**
- `analyze.py --repo jsoup --mode sidecar` produces valid SPDX on RHEL
- `analyze.py --repo spring-boot --mode sidecar` produces valid SPDX (Gradle)
- Package resolution works on Ubuntu (dpkg), RHEL (rpm), Alpine (apk)
- PURLs use correct scheme per distro (`pkg:deb/`, `pkg:rpm/`, `pkg:apk/`)
- `SYS_PTRACE` not required for Java sidecar builds
- Docker Hub publishes `omnibor-env:sidecar` image
- All existing standalone tests pass (zero regressions)

**Upstream dependency:** None. Java requires no upstream bomsh changes.

### Phase 2: C/C++ Pilot (Weeks 5–7)

**Goal:** C/C++ sidecar mode production-ready. Wrappers replace bomtrace3.

| Week | Work Item | Branch |
|------|-----------|--------|
| 5 | `CcWrapperStrategy` implementation | `feat/cc-sidecar` |
| 5 | Path abstraction (configurable system lib / include paths) | `feat/path-abstraction` |
| 5–6 | `emitter.py` — compiler info from strategy, not hardcoded GCC | `feat/cc-sidecar` |
| 6 | Integration tests: C/C++ sidecar on Ubuntu | `feat/cc-sidecar` |
| 6–7 | Integration tests: C/C++ sidecar on RHEL | `feat/sidecar-integration-tests` |
| 7 | **C/C++ pilot: READY** | |

**Deliverables:**
- `analyze.py --repo curl --mode sidecar` produces valid SPDX
- `CC=` / `CXX=` / `AR=` / `LD=` injection via `CommandRunner` env support
- `SYS_PTRACE` not required for C/C++ sidecar builds
- Sidecar SPDX output matches standalone within ≤5% package count

**Upstream dependency:** C/C++ wrappers must be available from bomsh by week 5.
Request upstream work to begin during Phase 1 (week 1) so wrappers are
ready when needed.

### Phase 3: Go + Rust + Python (Weeks 8–12)

**Goal:** Complete sidecar support for all remaining languages.

| Week | Work Item | Branch |
|------|-----------|--------|
| 8 | `GoToolexecStrategy` implementation | `feat/go-sidecar` |
| 8 | Go path abstraction (`go_root`, `GOROOT`) | `feat/go-sidecar` |
| 9 | `RustcWrapperStrategy` implementation | `feat/rust-sidecar` |
| 9 | Rust path abstraction (`cargo_home`, `CARGO_HOME`) | `feat/rust-sidecar` |
| 10 | `python_parser.py` (RECORD, METADATA, requirements) | `feat/python-spdx` |
| 10–11 | `python_generator.py` + `run_python_pipeline()` | `feat/python-spdx` |
| 11–12 | Integration tests: Go, Rust, Python sidecar | `feat/sidecar-integration-tests` |

**Deliverables:**
- `analyze.py --repo fzf --mode sidecar` produces valid SPDX
- `analyze.py --repo oxipng --mode sidecar` produces valid SPDX
- `analyze.py --repo <python-project>` produces valid SPDX
- All existing standalone tests pass (zero regressions)

**Upstream dependency:** Go and Rust wrappers must be available by week 8.

### Phase 4: Optimization + Hardening (Weeks 13–16)

**Goal:** Performance optimizations and production hardening.

| Week | Work Item | Branch |
|------|-----------|--------|
| 13 | Go Phase B: hybrid strategy (`go.sum` for third-party) | `feat/go-hybrid-strategy` |
| 13 | Rust `RUSTC_WORKSPACE_WRAPPER` optimization | `feat/rust-workspace-wrapper` |
| 14 | Python C extension strace integration | `feat/python-c-extensions` |
| 14–15 | ARM64 validation (wrappers on Graviton) | `feat/arm64-validation` |
| 15–16 | Documentation + runbook updates + enterprise handoff | `docs/sidecar-runbook` |

**Deliverables:**
- Go builds ~50% faster (Phase B vs Phase A)
- Rust wraps only workspace crates (~85% fewer invocations)
- ARM64 validated on AWS Graviton

### Phase 5: Future (Ongoing)

These items are explicitly **deferred** and tracked as future work:

| Item | Trigger | Design Extensibility Point |
|------|---------|---------------------------|
| Go `-toolexec` cache integration | Go issue #41145 merged | New `GoToolexecCachedStrategy` class — swap via config |
| eBPF interception | Language with no wrapper mechanism | New `EbpfStrategy` class — same interface |
| SPDX 3.0 output | SPDX 3.0 finalized and adopted | New `SpdxEmitter3` class alongside existing `SpdxEmitter` |
| Conda resolver | Enterprise demand for conda-based Python | New `CondaResolver` alongside `PipMetadataParser` |
| Bazel support | Enterprise demand | New `BazelStrategy` — reads `bazel aquery` action graph for input/output mappings |
| `clang` wrapper | Teams using clang instead of gcc | Extend `CcWrapperStrategy` — wrappers are compiler-agnostic |
| CMake `CMAKE_C_COMPILER_LAUNCHER` | Alternative to `CC=` for CMake-only projects | New strategy class |
| Wrapper chaining (ccache/distcc) | Pilot team already uses ccache | `CcWrapperStrategy` reads `wrapper_chain` config, sets `OMNIBOR_DELEGATE` env var |
| GraalVM native-image | Enterprise Java teams using Quarkus/GraalVM | New `GraalVmStrategy` — reads `-H:+BuildReport`, routes to C/C++ ADG pipeline |
| Ant/Ivy dependency resolution | Enterprise Java teams using Ant | New `AntIvyDependencyParser` — reads `ivy.xml` or analyzes classpath from strace |
| Yocto `bbclass` integration | Embedded Linux teams | Custom `omnibor.bbclass` wraps recipe's `${CC}`; documented in [B.7.1](sidecar-refactoring-plan.md#b7-build-systems-that-break-all-assumptions) |
| Nix overlay wrapper | Teams using NixOS/Nix for builds | Nix derivation overlay that wraps compiler with OmniBOR wrapper |
| `uv` lock file parser | Python teams adopting `uv` | Parse `uv.lock` (TOML) for direct vs. transitive dependency classification |

---

<a id="13-extensibility-and-future-proofing"></a>

## 13. Extensibility and Future-Proofing

### 13.1 Adding a New Language

To add language X to the pipeline:

1. **Config:** Add `omnibor_x` section to `config.yaml` with
   `standalone` and `sidecar` sub-keys
2. **Strategy:** Create `XStrategy(InterceptionStrategy)` in
   `app/pipeline/interception.py`
3. **Runner:** Add `run_x_pipeline()` to `lang_runners.py`
4. **Registration:** Add `"x": "omnibor_x"` to `lang_omnibor_keys`
   in `runners.py`
5. **SPDX generator** (if needed): Create `app/spdx/x_generator.py`
6. **Tests:** Unit tests + integration test with a reference project

**No existing files need modification** except `runners.py` (registration)
and `config.yaml` (new section). This is the Open/Closed Principle in action.

### 13.2 Adding a New Interception Mechanism

To add mechanism Y (e.g., eBPF):

1. Create `YStrategy(InterceptionStrategy)` implementing
   `instrument_command()` and `generate_adg()`
2. Register it in the strategy factory
3. Reference it in `config.yaml`:
   ```yaml
   omnibor:
     sidecar:
       strategy: ebpf  # Selects EbpfStrategy
   ```

**No pipeline code changes required.**

### 13.3 Adding a New Package Manager

To support distro Z:

1. Create `ZResolver(PackageResolver)` implementing `resolve()` and
   `purl_scheme()`
2. Add detection logic to `auto_detect_resolver()`

**No SPDX generation code changes required** — the resolver is injected
via dependency injection.

### 13.4 Go Issue #41145 — `-toolexec` Cache Integration

When/if Go merges cache-aware `-toolexec`:

1. Create `GoToolexecCachedStrategy(GoToolexecStrategy)` that omits
   the `-a` flag
2. Add to config:
   ```yaml
   omnibor_go:
     sidecar:
       strategy: go_toolexec_cached
       min_go_version: "1.XX"  # Version that supports cache integration
   ```
3. The strategy factory selects the cached strategy only when the Go
   version meets the minimum requirement

**Effort:** ~2 days when the Go feature ships. **Zero impact on existing
strategies.**

---

<a id="14-risk-register"></a>

## 14. Risk Register

<table>
<tr>
  <th style="width:3%">#</th>
  <th style="width:20%">Risk</th>
  <th style="width:20%">Impact</th>
  <th style="width:7%">Likelihood</th>
  <th style="width:50%">Mitigation</th>
</tr>
<tr>
  <td>R1</td>
  <td><strong>Upstream bomsh wrappers delayed</strong></td>
  <td>Blocks Go/Rust/C++ sidecar</td>
  <td>Medium</td>
  <td>Start Python (no upstream dep) in parallel; prepare integration tests against mock wrappers</td>
</tr>
<tr>
  <td>R2</td>
  <td><strong>Raw logfile format incompatibility</strong></td>
  <td>Wrappers produce data <code>bomsh_create_bom.py</code> can't parse</td>
  <td>Low</td>
  <td>Define format spec before wrapper development; integration test with real <code>bomsh_create_bom.py</code></td>
</tr>
<tr>
  <td>R3</td>
  <td><strong>Go <code>-a</code> performance unacceptable</strong></td>
  <td>Enterprise Go teams reject 100–200% overhead</td>
  <td>Medium</td>
  <td>Phase B hybrid strategy ready as fallback; monitor Go #41145</td>
</tr>
<tr>
  <td>R4</td>
  <td><strong>Alpine musl incompatibility</strong></td>
  <td>bomtrace3 doesn't compile on Alpine</td>
  <td>Medium</td>
  <td>Sidecar mode uses wrappers (no bomtrace3) — bypasses the issue entirely</td>
</tr>
<tr>
  <td>R5</td>
  <td><strong>RPM package metadata differs from dpkg</strong></td>
  <td><code>RpmResolver</code> produces incorrect metadata</td>
  <td>Low</td>
  <td>Test against RHEL 8 and 9 before release; use <code>rpm --queryformat</code> for predictable output</td>
</tr>
<tr>
  <td>R6</td>
  <td><strong>Backward compatibility regression</strong></td>
  <td>Standalone mode breaks during refactoring</td>
  <td>High impact, low likelihood</td>
  <td>Full test suite runs on every PR; golden file regression tests for SPDX output</td>
</tr>
<tr>
  <td>R7</td>
  <td><strong>Strategy interface too rigid</strong></td>
  <td>New language doesn't fit the 2-method interface</td>
  <td>Low</td>
  <td>Interface is deliberately minimal; strategies can have additional methods consumed by language-specific runners</td>
</tr>
<tr>
  <td>R8</td>
  <td><strong>Python C extension tracing gaps</strong></td>
  <td>strace misses some pip-invoked C compilations</td>
  <td>Medium</td>
  <td>Accept as known limitation in v1; document which packages need <code>CC=</code> wrapping</td>
</tr>
<tr>
  <td>R9</td>
  <td><strong>Pilot team uses hermetic build system (Bazel, Nix, Yocto)</strong></td>
  <td>Wrapper-based sidecar strategies completely fail — <code>CC=</code>, <code>-toolexec</code>, <code>RUSTC_WRAPPER</code> are all ignored</td>
  <td>Medium</td>
  <td>Pre-onboarding questionnaire (Section 16.1) screens teams before pilot. Fallback: <code>bomtrace3</code> ptrace works universally at the kernel level. Long-term: <code>BazelStrategy</code> reads <code>bazel aquery</code> action graph. See <a href="sidecar-refactoring-plan.md#b7-build-systems-that-break-all-assumptions">refactoring plan B.7</a>.</td>
</tr>
<tr>
  <td>R10</td>
  <td><strong>Wrapper stacking conflict (ccache, distcc, sccache)</strong></td>
  <td>Enterprise teams already using <code>CC="ccache gcc"</code> or <code>RUSTC_WRAPPER=sccache</code> — OmniBOR's wrapper displaces theirs</td>
  <td>High</td>
  <td><code>CcWrapperStrategy</code> must support chaining (call existing wrapper as delegate). For Rust, use <code>RUSTC_WORKSPACE_WRAPPER</code> for OmniBOR alongside <code>RUSTC_WRAPPER=sccache</code> — Cargo supports both. Pre-onboarding questionnaire asks about existing wrappers.</td>
</tr>
<tr>
  <td>R11</td>
  <td><strong>GraalVM native-image breaks Java pipeline</strong></td>
  <td>Java strace+javap analysis assumes JAR output. GraalVM AOT produces ELF native binary — <code>javap -v</code> does not apply</td>
  <td>Medium</td>
  <td>Detect GraalVM via build command inspection (<code>native-image</code> or <code>-Pnative</code>). Route to C/C++ pipeline (ADG from bomtrace3) augmented with Maven/Gradle dependency metadata. Long-term: dedicated <code>GraalVmStrategy</code>.</td>
</tr>
<tr>
  <td>R12</td>
  <td><strong>CGo projects silently miss C dependencies</strong></td>
  <td>Go <code>-toolexec</code> wraps Go tools only. CGo's <code>gcc</code>/<code>clang</code> invocations are invisible to the Go wrapper</td>
  <td>Medium</td>
  <td>When <code>CGO_ENABLED=1</code> is detected, automatically set <code>CC=</code> wrapper alongside <code>-toolexec</code>. Document this dual-interception requirement in onboarding guide.</td>
</tr>
</table>

---

<a id="14-1-security-considerations"></a>

### 14.1 Security Considerations

The OmniBOR wrappers occupy a **security-sensitive position** — they
intercept every compiler invocation and have read access to all source
code and build artifacts.

| Concern | Mitigation |
|---------|------------|
| **Wrapper binary integrity** | Wrappers should be distributed with SHA-256 checksums. Enterprise teams should verify checksums before deployment. Future: sign wrapper binaries with a code signing certificate. |
| **Raw logfile contains full command lines** | Command lines may include paths to proprietary source code. The raw logfile MUST be stored with restrictive permissions (0600) and deleted after SBOM generation. |
| **SBOM reveals internal dependency graph** | The generated SPDX document discloses all dependencies, versions, and build tools. Classify SBOMs appropriately per organizational data classification policy. |
| **Wrapper PATH injection** | Setting `CC=` to a malicious wrapper could compromise the build. Enterprise teams should deploy OmniBOR wrappers to a trusted, immutable path (`/opt/omnibor/`) with root-owned binaries. |
| **No network access** | Wrappers MUST NOT make network calls. All tracing data is written locally to the raw logfile. The analysis pipeline may access package registries for metadata enrichment, but this is a separate, auditable step. |

### 14.2 Platform Scope

| Platform | Wrapper support | Analysis pipeline | Notes |
|----------|----------------|-------------------|-------|
| **Linux x86_64** | ✅ Full | ✅ Full | Primary platform |
| **Linux ARM64** | ✅ Full (wrappers are arch-independent) | ✅ Full (Python analysis scripts) | Unlocked by sidecar mode |
| **macOS (Apple Silicon)** | ✅ Wrappers work | ⚠️ Partial — no strace, no bomtrace3 | Java requires Maven dep:tree (no strace fallback); C/C++/Go/Rust wrappers work natively |
| **Windows** | ✅ Wrappers work (with native compiler on PATH) | ⚠️ Partial — bomsh scripts assume POSIX | Future: Windows support requires `bomsh_create_bom.py` POSIX dependency removal |

The wrapper approach (`CC=`, `-toolexec`, `RUSTC_WRAPPER`) is
inherently cross-platform. The **analysis pipeline** (Python scripts,
bomsh) is currently Linux-specific due to POSIX assumptions (`strace`,
`readelf`, `/proc` filesystem). Sidecar mode on macOS/Windows would
require porting the analysis pipeline or running it in a Linux container
that reads wrapper output from a shared volume.

---

<a id="15-testing-strategy"></a>

## 15. Testing Strategy

### 15.1 Unit Tests (per-component, mocked I/O)

| Component | What to Test | Isolation |
|-----------|-------------|-----------|
| `InterceptionStrategy` subclasses | `instrument_command()` returns correct (cmd, env) tuple | Pure function tests |
| `PackageResolver` subclasses | Parse output of `dpkg-query`, `rpm -qf`, `apk info` | Mock subprocess |
| `PythonSpdxGenerator` | SPDX output from known RECORD/METADATA inputs | Mock importlib.metadata |
| `config.resolve_omnibor_cfg()` | Mode selection, fallback to flat format | No I/O |
| `CommandRunner.run()` with env | Environment variable propagation | Mock subprocess |

### 15.2 Integration Tests (real builds, golden file comparison)

| Test | Reference Project | Validates |
|------|------------------|-----------|
| Rust sidecar | oxipng v10.1.0 | `RUSTC_WRAPPER` → identical SPDX to standalone |
| Go sidecar | fzf v0.70.0 | `-toolexec` → identical SPDX to standalone |
| C/C++ sidecar | curl 8.19.0 | `CC=` wrapper → identical SPDX to standalone |
| Python | TBD reference project | Pip metadata → valid SPDX with correct PURLs |
| Java (unchanged) | jsoup 1.22.1 | No regression from infrastructure changes |

**Structural equivalence policy:** Standalone golden files are the
reference. Sidecar mode output must match:
- Same number of `DESCRIBES` relationships
- Same direct dependency names (versions may differ across distros)
- Same relationship type distribution (STATIC_LINK, DYNAMIC_LINK, etc.)
- Package count within ±5% (distro-specific system libs may differ)
- File-level hashes WILL differ (different compiler, different distro)

### 15.3 Coverage Requirements

- **Overall project:** ≥97% line coverage (existing threshold)
- **New files:** 100% of public functions must have at least one test
- **Strategy classes:** 100% branch coverage on `instrument_command()`

---

<a id="16-success-criteria"></a>

## 16. Success Criteria

### Phase 1 (Weeks 1–6)

- [ ] `analyze.py --mode sidecar` flag accepted and dispatches correctly
- [ ] Go sidecar produces valid SPDX with ≤10% fewer packages than standalone
- [ ] Rust sidecar produces valid SPDX with 0 fewer packages than standalone
- [ ] Python pipeline produces valid SPDX for a reference Python project
- [ ] All 180+ existing tests pass (zero regressions)
- [ ] Coverage remains ≥97%

### Phase 2 (Weeks 7–10)

- [ ] C/C++ sidecar produces valid SPDX with ≤5% fewer packages than standalone
- [ ] Package resolution works on Ubuntu, RHEL 8/9, Alpine 3.18+
- [ ] PURLs use correct scheme per distro family
- [ ] `SYS_PTRACE` capability not required for sidecar Go/Rust/C++ builds

### Phase 3 (Weeks 11–14)

- [ ] Go Phase B reduces overhead by ≥30% vs Phase A
- [ ] Rust workspace wrapper reduces wrapper invocations by ≥80%
- [ ] Docker Hub has separate standalone and sidecar image tags
- [ ] ARM64 (Graviton) validation passes for Go, Rust, C/C++
- [ ] Enterprise integration guide updated with sidecar instructions

### Overall

- [ ] **No standalone regression** — every project that works today still works
- [ ] **SPDX output equivalence** — sidecar mode produces comparable SBOMs
- [ ] **Strategy pattern** — adding a new language requires <1 day of pipeline code

---

<a id="16-1-pre-onboarding-screening"></a>

### 16.1 Pre-Onboarding Screening

Before onboarding any engineering team for sidecar pilot, run the
screening questionnaire from
[sidecar-refactoring-plan.md B.7.5](sidecar-refactoring-plan.md#b7-build-systems-that-break-all-assumptions)
to identify which interception strategy applies.

**Critical blockers** (require ptrace fallback or deferred support):

| Scenario | Impact | Resolution |
|----------|--------|------------|
| Bazel / Buck2 / Pants | Wrappers do not work | Use `interception: ptrace` per-repo override; defer to `BazelStrategy` (Phase 5) |
| Nix / Guix | Wrappers do not work | Use `interception: ptrace` per-repo override; defer to Nix overlay (Phase 5) |
| Yocto / BitBake | CC= overridden per recipe | Use `interception: ptrace` per-repo override; defer to `bbclass` (Phase 5) |
| GraalVM native-image | Java pipeline assumes JAR output | Route to C/C++ pipeline + Maven dependency metadata (R11 mitigation) |

**Compatibility issues** (solvable with config changes):

| Scenario | Impact | Resolution |
|----------|--------|------------|
| Existing ccache/distcc | Wrapper conflict | Set `wrapper_chain: [ccache]` in repo config |
| Existing sccache (Rust) | `RUSTC_WRAPPER` conflict | Use `RUSTC_WORKSPACE_WRAPPER` for OmniBOR |
| CGo with vendored C | Go SBOM misses C deps | Set `CC=` wrapper alongside `-toolexec` (R12 mitigation) |
| Internal toolchain at non-standard path | Wrapper may not find real compiler | Wrapper discovers compiler on `PATH` (skip self); test with actual toolchain |
| CMake hardcoded `CMAKE_C_COMPILER` | `CC=` ignored | Delete `CMakeCache.txt`; use `CMAKE_C_COMPILER_LAUNCHER` instead |

**Recommendation:** Run the screening questionnaire during the team intake
meeting, **before** any technical work begins. If a team hits a critical
blocker, either: (a) use ptrace mode (higher overhead, but universally
works), or (b) defer that team to a later phase when the appropriate
strategy is implemented.

---

*Document created: 2026-05-01 09:08 HST*
*Updated: 2026-05-01 09:53 HST — risks R9–R12, per-repo interception override, wrapper chaining, pre-onboarding screening*
*Updated: 2026-05-01 09:59 HST — devil's advocate review fixes: structural equivalence criteria, failure isolation (P7), value proposition (P8), security considerations (14.1), platform scope (14.2), wrapper implementation requirements (10.3), Go overhead baseline correction, Rust build cache correction*
