# Enterprise Integration Guide: OmniBOR Build-Time SBOM Generation

- **Date:** March 9, 2026
- **Author:** OmniBOR Analysis Team
- **Status:** Draft — Living Document
- **Audience:** Internal Cisco development teams integrating build-time SBOM generation

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [What OmniBOR Build Interception Does](#what-omnibor-build-interception-does)
3. [Current State of omnibor-analysis](#current-state-of-omnibor-analysis)
4. [Enterprise Integration Requirements](#enterprise-integration-requirements)
5. [Gap Analysis: Current vs. Enterprise](#gap-analysis-current-vs-enterprise)
6. [Integration Architecture](#integration-architecture)
7. [Distro Compatibility Matrix](#distro-compatibility-matrix)
8. [Compiler and Toolchain Considerations](#compiler-and-toolchain-considerations)
9. [Build System Integration Patterns](#build-system-integration-patterns)
10. [CI/CD Pipeline Integration](#cicd-pipeline-integration)
11. [Cross-Compilation Support](#cross-compilation-support)
12. [Turnkey Packaging Strategy](#turnkey-packaging-strategy)
13. [Rollback and Fallback Strategy](#rollback-and-fallback-strategy)
14. [Performance Impact and Mitigation](#performance-impact-and-mitigation)
15. [Multi-Repo Product Support](#multi-repo-product-support)
16. [Vendored vs. System Dependencies](#vendored-vs-system-dependencies)
17. [Cisco Policy Compliance](#cisco-policy-compliance)
18. [Recommended Modifications to omnibor-analysis](#recommended-modifications-to-omnibor-analysis)
19. [Phased Rollout Plan](#phased-rollout-plan)
20. [Open Questions](#open-questions)

---

## Executive Summary

Cisco internal policy mandates build-time SBOM generation. The `omnibor-analysis` project
generates accurate, build-intercepted SPDX 2.3 SBOMs by wrapping the actual compiler/linker
invocations using **bomtrace3** (a patched strace). This captures *exactly* what went into
each binary — not what a manifest says *should* go in.

**The goal:** Enable internal Cisco development teams to integrate OmniBOR build-time SBOM
generation into their existing build systems and CI/CD pipelines **without changing how they
build, test, or deploy their software.**

**Key finding:** The current `omnibor-analysis` was designed as a standalone research/analysis
tool. Significant modifications are needed to support enterprise integration as a turnkey
package. This document details what works today, what gaps exist, and a concrete plan to
close those gaps.

---

## What OmniBOR Build Interception Does

### How It Works

```
Normal build:    make -j4  →  gcc compiles foo.c  →  ld links foo.o  →  binary
                                                                         
OmniBOR build:   bomtrace3 make -j4  →  strace intercepts every gcc/ld call
                                     →  records input files (sources, headers, .o, .a, .so)
                                     →  records output files (binaries, libraries)
                                     →  builds an Artifact Dependency Graph (ADG)
                                     →  generates SPDX 2.3 SBOM from the ADG
```

### What the Team Sees

From the development team's perspective, the only change is prefixing their final build
command with `bomtrace3`:

```bash
# Before (unchanged build)
make -j$(nproc)

# After (instrumented build — same result, plus SBOM)
bomtrace3 make -j$(nproc)
```

The build produces the **exact same binaries**. bomtrace3 is a passive observer — it uses
`ptrace` (the same mechanism as strace/gdb) to watch syscalls without modifying the build
process itself.

### What It Produces

| Output | Format | Description |
|--------|--------|-------------|
| ADG documents | OmniBOR JSON | Artifact Dependency Graph — every file that went into every output |
| SPDX SBOM | SPDX 2.3 JSON | Standard SBOM with `DEPENDS_ON`, `STATIC_LINK`, `DYNAMIC_LINK`, `BUILD_TOOL_OF` relationships |
| HTML visualization | D3.js HTML | Interactive dependency graph (optional, for human review) |

---

## Current State of omnibor-analysis

### What Exists Today

| Component | Status | Notes |
|-----------|--------|-------|
| bomtrace3 build interception | ✅ Working | C/C++ via patched strace v6.11 |
| bomtrace2 (Rust, Go) | ✅ Working | Uses bomsh_hook2.py for language-specific parsing |
| SPDX 2.3 generation | ✅ Working | Per-binary SBOMs with relationship types |
| Dynamic library detection | ✅ Working | ldd + readelf + dpkg metadata resolution |
| Vendored dependency detection | ✅ Working | Configurable vendored_dirs in config.yaml |
| System package metadata | ✅ Working | dpkg-query based (Debian/Ubuntu only) |
| HTML visualization | ✅ Working | D3.js interactive graphs |
| Docker container | ✅ Working | Ubuntu 22.04 base, all tools pre-installed |
| Python orchestration | ✅ Working | analyze.py pipeline with config.yaml |

### How It's Deployed Today

```
┌─────────────────────────────────────────────────┐
│  Docker Container (ubuntu:22.04, linux/amd64)   │
│                                                 │
│  ┌──────────┐  ┌──────────┐                    │
│  │bomtrace3 │  │ bomsh    │                    │
│  │(patched  │  │(ADG +    │                    │
│  │ strace)  │  │ SPDX)    │                    │
│  └────┬─────┘  └────┬─────┘                    │
│       │              │                          │
│  ┌────┴──────────────┴──────────────────┐       │
│  │  analyze.py (Python orchestrator)    │       │
│  │  config.yaml (repo definitions)      │       │
│  │  spdx_from_adg.py (SPDX emitter)    │       │
│  └──────────────────────────────────────┘       │
│                                                 │
│  Compilers: gcc, g++, clang, rustc, go          │
│  OS packages: libssl-dev, zlib1g-dev, etc.      │
└─────────────────────────────────────────────────┘
```

### Hard Constraints (Cannot Change)

| Constraint | Reason |
|------------|--------|
| **x86_64 architecture only** | bomtrace3 includes `<sys/reg.h>` which only exists on x86 Linux |
| **Linux only** | strace/ptrace is Linux-specific |
| **SYS_PTRACE capability** | Required for strace to attach to child processes |
| **seccomp:unconfined** | Required if running inside Docker (strace needs unrestricted syscall access) |
| **strace v6.11 pin** | bomsh patches only apply cleanly against this specific version |

---

## Enterprise Integration Requirements

Based on expected Cisco dev teams' profile:

| Requirement | Detail |
|-------------|--------|
| **Linux distros** | RHEL 8/9, Ubuntu 20.04/22.04, CentOS, Alpine, Cisco-hardened (Alpine/Ubuntu-based) |
| **Build systems** | make, cmake, Ninja, autotools — possibly multiple per product |
| **Compilers** | Internal toolchain (specific gcc/g++ versions) AND/OR distro-default |
| **Cross-compilation** | Different Cisco hardware targets, different deployment distros |
| **Build hosts** | VM-based, possibly containerized (Docker/Podman) |
| **CI systems** | Jenkins, GitHub Actions, others |
| **SBOM trigger** | Every CI build ideally; fallback to release-tag-only if overhead too high |
| **Build invocation** | Single top-level `make all` / `cmake --build`, may be multi-stage |
| **Repos** | Single or multiple repos per product, 1-4 output binaries |
| **Dependencies** | System `-dev` packages primarily; may include vendored libs |
| **Network** | Build hosts can reach github.com |
| **Compliance** | Cisco internal policy mandates build-based SBOM generation |
| **Ownership** | Team maintains long-term, but initial delivery must be turnkey |

---

## Gap Analysis: Changes Needed in omnibor-analysis for Enterprise Use

The following gaps exist in the current `omnibor-analysis` codebase. Each must be addressed
to support enterprise Cisco dev team integration. None are fundamental blockers — all have
known solutions with estimated effort.

### Implementation Gaps

| # | Gap | Severity | Detail |
|---|-----|----------|--------|
| G1 | **Package metadata is dpkg-only (solvable)** | � High | `collect_metadata.py` and `collect_dynamic_libs.py` currently use `dpkg-query` to resolve system files to named packages. Equivalent tools exist on every distro — `rpm -qf` (RHEL/CentOS), `apk info --who-owns` (Alpine) — but are not yet implemented. The resolution logic is identical in structure; only the CLI tool and output parsing differ. Estimated effort: ~2-3 weeks to add a `PackageResolver` abstraction with per-distro backends. |
| G2 | **Hardcoded Ubuntu 22.04 container** | � High | The Dockerfile installs Ubuntu-specific packages. Enterprise teams need the tooling to work in *their* existing build environment, not ours. The fix is the sidecar/tarball packaging approach described in this document — bomtrace3 and bomsh are installed into the team's environment, not the other way around. |
| G3 | **PURL scheme varies by distro** | 🟡 Medium | SPDX component PURLs are currently `pkg:deb/ubuntu/...`. Each distro family needs its own PURL scheme (`pkg:rpm/rhel/...`, `pkg:apk/alpine/...`). This is a small extension to the package resolver — each backend emits the correct PURL format. |
| G4 | **No support for custom compiler paths** | 🟡 Major | bomtrace3 intercepts `execve` syscalls and matches against known compiler binary names (gcc, g++, cc, etc.). Internal toolchains at non-standard paths (e.g., `/opt/cisco-toolchain/bin/gcc-12`) need verification that bomtrace3 still intercepts them. |
| G5 | **No cross-compilation awareness** | 🟡 Major | Cross-compilers (e.g., `aarch64-linux-gnu-gcc`) produce binaries for a different arch. The SPDX SBOM currently doesn't record the target architecture or deployment platform. |
| G6 | **No lightweight SBOM-only mode** | 🟡 Medium | `analyze.py` provides a full pipeline (clone, build, SBOM, docs) which is valuable for onboarding and validation. However, once a team has validated the tooling, their production CI may only need a lightweight post-build SBOM generation step — without cloning or doc writing. Adding an `omnibor-sbom-gen` CLI as a companion tool (not a replacement) would serve this use case. |
| G7 | **No native CI integration** | 🟡 Major | No Jenkins pipeline library, GitHub Action, or generic CI script. Teams would have to reverse-engineer the Docker + analyze.py workflow. |
| G8 | **Alpine musl libc unknown** | 🟡 Major | bomtrace3/bomsh are tested against glibc. Alpine uses musl libc. Needs validation — strace itself works on Alpine, but bomsh patches may have glibc-specific assumptions. |
| G9 | **No product-level SBOM composition** | 🟢 Minor | Each repo correctly generates its own SBOM. For multi-repo products, there is no tooling yet to compose a product-level SBOM from individual per-repo SBOMs using SPDX `ExternalDocumentRef`. |
| G10 | **No build metadata retention for provenance** | 🟢 Minor | Cisco policy does not require signing of internally generated SBOMs. However, software provenance may require build metadata (compiler version, build flags, environment details) associated with build-time SBOMs to be retained alongside the SBOM artifacts. |

### What Already Works for Enterprise

| Capability | Why It Works |
|------------|-------------|
| **bomtrace3 core interception** | Works with any compiler — it intercepts `execve` syscalls at the kernel level, agnostic to the specific compiler binary. A custom gcc at `/opt/toolchain/bin/gcc-12` will be intercepted just like `/usr/bin/gcc`. |
| **Build system agnostic** | bomtrace3 wraps the top-level build command. Whether that's `make`, `cmake --build`, `ninja`, or a custom script — it traces all child processes recursively. |
| **SPDX 2.3 output** | Industry-standard format, accepted by Cisco compliance tooling. |
| **Vendored dependency detection** | Configurable `vendored_dirs` patterns already handle bundled third-party source. |
| **Parallel build support** | bomtrace3 handles `make -j$(nproc)` — it traces all forked processes. |

---

## Integration Architecture

### Target State: Enterprise Deployment

```
┌─────────────────────────────────────────────────────────────┐
│  Team's Existing Build Environment (VM or Container)         │
│  (RHEL 9 / Ubuntu 22.04 / Alpine / Cisco-hardened)          │
│                                                             │
│  Team's existing compilers, libs, build tools               │
│  ┌────────────────────────────────────────────┐             │
│  │  /opt/cisco-toolchain/bin/gcc-12           │             │
│  │  /usr/bin/make, cmake, ninja               │             │
│  │  System -dev packages (rpm/deb/apk)        │             │
│  └────────────────────────────────────────────┘             │
│                                                             │
│  OmniBOR Sidecar (installed, not containerized separately)  │
│  ┌────────────────────────────────────────────┐             │
│  │  bomtrace3          (pre-built binary)     │             │
│  │  bomsh scripts      (Python)               │             │
│  │  omnibor-sbom-gen   (new: lightweight CLI) │             │
│  │  pkg-resolver       (new: rpm/deb/apk)     │             │
│  └────────────────────────────────────────────┘             │
│                                                             │
│  CI Pipeline Step:                                          │
│  1. [existing steps... configure, deps, etc.]               │
│  2. bomtrace3 make -j$(nproc)         ← only change        │
│  3. omnibor-sbom-gen --output sbom/   ← new post-build step│
│  4. [existing steps... test, package, deploy]               │
└─────────────────────────────────────────────────────────────┘
```

### Key Design Principle: Sidecar, Not Container

The current omnibor-analysis packages everything in a Docker container with its own compilers.
For enterprise integration, **bomtrace3 and the SBOM tooling must be installed alongside the
team's existing toolchain** — not replace it.

This means:
- **Pre-built bomtrace3 binary** distributed as an RPM, DEB, APK, or tarball
- **bomsh Python scripts** installed to a known path
- **New lightweight CLI** (`omnibor-sbom-gen`) that replaces the monolithic `analyze.py`
- **No requirement to use our Docker image** — the team's build environment is untouched

---

## Distro Compatibility Matrix

### bomtrace3 Binary Compatibility

bomtrace3 is a statically-linkable patched strace. The key question per distro is:
*Can we build bomtrace3 on this distro, and does ptrace work correctly?*

| Distro | glibc/musl | `<sys/reg.h>` | strace works | bomtrace3 status | Package metadata |
|--------|-----------|---------------|-------------|-----------------|-----------------|
| **Ubuntu 20.04** | glibc 2.31 | ✅ | ✅ | ✅ Tested | dpkg-query |
| **Ubuntu 22.04** | glibc 2.35 | ✅ | ✅ | ✅ Tested (current) | dpkg-query |
| **RHEL 8** | glibc 2.28 | ✅ | ✅ | 🟡 Untested, expected to work | rpm -qf |
| **RHEL 9** | glibc 2.34 | ✅ | ✅ | 🟡 Untested, expected to work | rpm -qf |
| **CentOS Stream 8/9** | glibc 2.28/2.34 | ✅ | ✅ | 🟡 Untested, expected to work | rpm -qf |
| **Alpine 3.18+** | musl 1.2.4+ | ⚠️ Partial | ✅ | 🔴 Untested, risk | apk info --who-owns |
| **Cisco-hardened (Alpine)** | musl | ⚠️ Partial | ❓ | 🔴 Must validate | Custom (TBD) |
| **Cisco-hardened (Ubuntu)** | glibc | ✅ | ✅ | 🟡 Expected to work | dpkg-query (likely) |

### Alpine-Specific Risk

Alpine Linux uses **musl libc** instead of glibc. Key concerns:

1. **`<sys/reg.h>`** — musl provides a minimal version of this header, but it may not include
   all register definitions that bomsh_hook.c expects. Needs compile-time testing.
2. **`strace` on Alpine** — strace itself is available as an Alpine package and works on musl,
   but the bomsh patches modify strace source code that may have glibc assumptions.
3. **`dpkg` not available** — Alpine uses `apk`, requiring a new package resolver.

**Recommendation:** Validate bomtrace3 compilation and runtime on Alpine as a separate
spike before committing to Alpine support. If Alpine support is blocked, the team can
run the SBOM generation step in a glibc-based sidecar container on Alpine hosts.

### Package Metadata Resolution by Distro Family

| Distro Family | Package Manager | File → Package Command | PURL Scheme |
|--------------|----------------|----------------------|-------------|
| Debian/Ubuntu | dpkg | `dpkg-query -S /path/to/file` | `pkg:deb/ubuntu/<name>@<ver>` |
| RHEL/CentOS | rpm | `rpm -qf /path/to/file` | `pkg:rpm/rhel/<name>@<ver>` |
| Alpine | apk | `apk info --who-owns /path/to/file` | `pkg:apk/alpine/<name>@<ver>` |
| Cisco-hardened | varies | TBD — may need custom resolver | `pkg:generic/<name>@<ver>` |

**This is Gap G1/G3** — `collect_metadata.py` currently only implements the dpkg path.
We need to abstract this into a **package resolver interface** with implementations for
each distro family.

---

## Compiler and Toolchain Considerations

### bomtrace3 Intercepts at the Syscall Level

bomtrace3 does **not** care what compiler is being used or where it lives. It intercepts
the `execve` syscall, which means:

```bash
# All of these are intercepted identically:
bomtrace3 make -j4                    # distro gcc at /usr/bin/gcc
bomtrace3 make CC=/opt/gcc-12/bin/gcc # custom toolchain
bomtrace3 cmake --build build/        # cmake invoking ninja invoking clang
bomtrace3 ninja -j8                   # direct ninja invocation
```

The `bomsh_create_bom.py` script then parses the raw logfile to identify which `execve`
calls were compiler/linker invocations (by matching binary names like `gcc`, `g++`, `cc`,
`c++`, `ld`, `ar`, `as`).

### Potential Issue: Non-Standard Compiler Names

If the internal toolchain uses non-standard binary names (e.g., `cisco-gcc-12` instead of
`gcc-12`), bomsh's compiler detection regex may not recognize it. The bomsh
`bomsh_hook2.py` and `bomsh_create_bom.py` scripts use patterns like:

```python
# From bomsh source — compiler detection patterns
("gcc", "g++", "cc", "c++", "clang", "clang++", ...)
```

**Action required:** Verify the internal toolchain's binary names. If they don't match
bomsh's patterns, we have two options:
1. **Symlink/wrapper:** Create symlinks with standard names pointing to the toolchain binaries
2. **Patch bomsh:** Add the custom names to bomsh's compiler detection — this is a small,
   upstreamable change

### Toolchain Metadata in SPDX

The SPDX SBOM should record which compiler produced the binary. This is currently captured
in `creationInfo.creators` but should be extended to include:
- Compiler name and version (`gcc (Cisco-internal) 12.3.0`)
- Target triple (`x86_64-linux-gnu`, `aarch64-linux-gnu`)
- Optimization flags (`-O2 -fstack-protector-strong`)

This metadata is available from the bomtrace3 raw logfile (full command lines are recorded).

---

## Build System Integration Patterns

### Pattern 1: Make / Autotools (Most Common)

```bash
# Team's existing build:
./configure --prefix=/usr --enable-foo
make -j$(nproc)
make install DESTDIR=/tmp/pkg

# With OmniBOR instrumentation:
./configure --prefix=/usr --enable-foo
bomtrace3 make -j$(nproc)              # ← wrap only the compile step
make install DESTDIR=/tmp/pkg
omnibor-sbom-gen --bom-dir /tmp/omnibor --output sbom/  # ← new step
```

**Key:** Only the `make` step is wrapped. `./configure` and `make install` are NOT
instrumented — they don't compile anything.

### Pattern 2: CMake + Ninja

```bash
# Team's existing build:
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build -j $(nproc)

# With OmniBOR instrumentation:
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
bomtrace3 cmake --build build -j $(nproc)   # ← wrap the build step
omnibor-sbom-gen --bom-dir /tmp/omnibor --output sbom/
```

### Pattern 3: CMake + Make

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Release
bomtrace3 cmake --build build -- -j$(nproc)
omnibor-sbom-gen --bom-dir /tmp/omnibor --output sbom/
```

### Pattern 4: Multi-Stage Pipeline Script

```bash
#!/bin/bash
# build.sh — team's existing build script

set -e
./bootstrap.sh
./configure --with-openssl
make -j$(nproc)
make test
make install DESTDIR=$DESTDIR
```

Integration option A — **wrap the script** (simplest, traces everything including tests):

```bash
bomtrace3 ./build.sh
```

Integration option B — **modify the script** (precise, only traces compilation):

```bash
#!/bin/bash
set -e
./bootstrap.sh
./configure --with-openssl
${BOMTRACE_CMD:-} make -j$(nproc)    # ← env var, defaults to no-op
make test
make install DESTDIR=$DESTDIR
```

Then in CI: `BOMTRACE_CMD=bomtrace3 ./build.sh`

**Option B is recommended** because it:
- Only traces the actual compilation (not configure, test, install)
- Produces a smaller, more focused ADG
- Reduces performance overhead
- Can be toggled off with an empty env var

---

## CI/CD Pipeline Integration

### Jenkins (Most Popular for Enterprise Linux)

```groovy
// Jenkinsfile
pipeline {
    agent { label 'linux-x86_64' }

    environment {
        OMNIBOR_ENABLED = "${params.GENERATE_SBOM ?: 'true'}"
    }

    parameters {
        booleanParam(name: 'GENERATE_SBOM', defaultValue: true,
                     description: 'Generate build-time SBOM via OmniBOR')
    }

    stages {
        stage('Build') {
            steps {
                script {
                    def buildCmd = 'make -j$(nproc)'
                    if (env.OMNIBOR_ENABLED == 'true') {
                        buildCmd = "bomtrace3 ${buildCmd}"
                    }
                    sh buildCmd
                }
            }
        }

        stage('Generate SBOM') {
            when { environment name: 'OMNIBOR_ENABLED', value: 'true' }
            steps {
                sh 'omnibor-sbom-gen --bom-dir /tmp/omnibor --output sbom/'
                archiveArtifacts artifacts: 'sbom/*.spdx.json', fingerprint: true
            }
        }

        stage('Test') {
            steps {
                sh 'make test'
            }
        }
    }
}
```

### GitHub Actions

```yaml
# .github/workflows/build.yml
name: Build with SBOM

on:
  push:
    branches: [main]
  pull_request:
  release:
    types: [published]

jobs:
  build:
    runs-on: ubuntu-latest  # or self-hosted linux x86_64 runner

    env:
      GENERATE_SBOM: ${{ github.event_name == 'push' || github.event_name == 'release' }}

    steps:
      - uses: actions/checkout@v4

      - name: Install OmniBOR tooling
        if: env.GENERATE_SBOM == 'true'
        run: |
          # Install from pre-built package (future: omnibor-tools package)
          curl -sSL https://github.com/tedg-dev/omnibor-analysis/releases/latest/download/omnibor-tools-linux-amd64.tar.gz | sudo tar -xzf - -C /usr/local

      - name: Build
        run: |
          ./configure
          ${{ env.GENERATE_SBOM == 'true' && 'bomtrace3' || '' }} make -j$(nproc)

      - name: Generate SBOM
        if: env.GENERATE_SBOM == 'true'
        run: omnibor-sbom-gen --bom-dir /tmp/omnibor --output sbom/

      - name: Upload SBOM
        if: env.GENERATE_SBOM == 'true'
        uses: actions/upload-artifact@v4
        with:
          name: sbom
          path: sbom/*.spdx.json
```

### Recommended SBOM Generation Trigger Strategy

| Trigger | SBOM Generation | Rationale |
|---------|----------------|-----------|
| **Every push to main** | ✅ Yes | Continuous compliance — catches dependency changes immediately |
| **Pull requests** | ❌ No (optional) | Avoid overhead on iterative development; PR reviewers can opt in |
| **Release tags** | ✅ Yes (mandatory) | Compliance requirement — every released artifact must have an SBOM |
| **Nightly builds** | ✅ Yes | Catch drift between commits; good for large repos where per-push is too slow |

**Fallback:** If bomtrace3 overhead is unacceptable for every push, fall back to
release-tag-only generation. The `GENERATE_SBOM` flag in the CI examples above
makes this a configuration change, not a code change.

---

## Cross-Compilation Support

### The Challenge

Cisco products may target different hardware architectures:
- x86_64 servers and appliances
- ARM64 (aarch64) embedded devices
- Custom Cisco ASICs with cross-compiled userspace

Cross-compilation means the **build host** is x86_64 but the **output binary** targets a
different architecture (e.g., `aarch64-linux-gnu-gcc` producing ARM64 binaries).

### bomtrace3 and Cross-Compilation

**Good news:** bomtrace3 runs on the **build host**, not the target. It intercepts the
cross-compiler's `execve` on the x86_64 build machine. The fact that the compiler produces
ARM64 output is irrelevant to bomtrace3 — it's watching the *build process*, not executing
the output.

```bash
# This works — bomtrace3 traces the cross-compiler on x86_64
bomtrace3 make CC=aarch64-linux-gnu-gcc -j$(nproc)
```

### What Needs to Change for Cross-Compilation

1. **Compiler name detection** — bomsh must recognize cross-compiler prefixed names like
   `aarch64-linux-gnu-gcc`, `arm-cisco-linux-gnueabihf-g++`, etc. These follow the
   GNU triplet convention: `<arch>-<vendor>-<os>-<tool>`.

2. **SPDX target platform metadata** — The generated SBOM should record:
   ```json
   {
     "name": "cisco-binary",
     "primaryPackagePurpose": "APPLICATION",
     "comment": "Target: aarch64-linux-gnu (cross-compiled on x86_64-linux-gnu)"
   }
   ```

3. **Dynamic library resolution** — `ldd` cannot inspect cross-compiled binaries on the
   build host (wrong architecture). Use `readelf -d` instead, which reads ELF headers
   without executing the binary. `collect_dynamic_libs.py` already uses readelf as a
   fallback — this needs to become the primary path for cross-compiled binaries.

4. **System package mapping** — The `-dev` packages on the build host are for the
   *cross-compilation sysroot*, not the host. Package resolution needs to be sysroot-aware
   (e.g., `dpkg-query -S` within the cross-compilation sysroot, or reading `.pc` files from
   `PKG_CONFIG_SYSROOT_DIR`).

---

## Turnkey Packaging Strategy

### Distribution Format Options

| Format | Target Distros | Install Command | Pros | Cons |
|--------|---------------|-----------------|------|------|
| **RPM** | RHEL 8/9, CentOS | `yum install omnibor-tools-*.rpm` | Native to enterprise Linux | Must build per distro version |
| **DEB** | Ubuntu, Debian | `dpkg -i omnibor-tools-*.deb` | Native to current dev/test env | Different from RHEL targets |
| **APK** | Alpine, Cisco-hardened | `apk add omnibor-tools-*.apk` | Native to Alpine | musl validation needed |
| **Tarball** | All | `tar -xzf omnibor-tools.tar.gz -C /usr/local` | Universal, no pkg manager | No dependency tracking |
| **Container sidecar** | All (Docker/Podman) | `docker run --rm -v ... omnibor-tools` | Isolated, reproducible | Adds container complexity |

### Recommended: Tiered Approach

**Tier 1 (MVP):** Static tarball containing:
```
omnibor-tools/
├── bin/
│   ├── bomtrace3              # Pre-built static binary
│   └── omnibor-sbom-gen       # New lightweight Python CLI (or compiled)
├── lib/
│   └── bomsh/                 # bomsh Python scripts
│       ├── bomsh_create_bom.py
│       ├── bomsh_sbom.py
│       ├── bomsh_hook2.py
│       └── ...
├── etc/
│   └── omnibor/
│       └── bomtrace.conf      # Default config
└── share/
    └── omnibor/
        └── examples/          # CI integration examples
```

**Tier 2:** Native packages (RPM, DEB, APK) that install the same files and declare
dependencies on Python 3.8+.

**Tier 3:** Container sidecar image for teams that want complete isolation.

### The `omnibor-sbom-gen` CLI (New Component)

This is the **key new component** that doesn't exist today. It replaces the monolithic
`analyze.py` with a focused, enterprise-friendly CLI:

```bash
# After a bomtrace3-instrumented build, generate SBOMs:
omnibor-sbom-gen \
  --bom-dir /tmp/omnibor \
  --binary src/.libs/myapp \
  --binary lib/.libs/libfoo.so \
  --output sbom/ \
  --format spdx-json \
  --product-name "Cisco Product" \
  --product-version "2.5.0" \
  --supplier "Cisco Systems"
```

What it does:
1. Reads the ADG from `--bom-dir` (produced by bomtrace3 + bomsh_create_bom.py)
2. Resolves system files to packages using the **detected package manager** (dpkg/rpm/apk)
3. Detects vendored directories (auto-detect or `--vendored-dirs` flag)
4. Classifies dependencies (`STATIC_LINK`, `DYNAMIC_LINK`, `DEPENDS_ON`, `BUILD_TOOL_OF`)
5. Emits SPDX 2.3 JSON per binary
6. Optionally generates HTML visualization

What it does **NOT** do (enterprise teams don't need these):
- Clone repos
- Run builds
- Write markdown docs
- Manage timestamps or output directory conventions

---

## Rollback and Fallback Strategy

### Levels of Integration

| Level | Integration | SBOM Quality | Build Impact | Rollback |
|-------|------------|-------------|-------------|----------|
| **L0: No SBOM** | None | ❌ None | Zero | N/A |
| **L1: bomtrace3 per-release** | `bomtrace3 make` on release tags only | ✅ Full build-time SBOM | 15-40% on release builds only | Change CI trigger |
| **L2: bomtrace3 per-push** | `bomtrace3 make` on every push to main | ✅ Full build-time SBOM | 15-40% on every build | Change to L1 |

**Recommended rollout path:** L1 → L2

- Start at **L1** once bomtrace3 is validated on the team's build (release-only)
- Upgrade to **L2** if the build-time overhead is acceptable for every push

### Emergency Rollback

If bomtrace3 causes a build failure or unacceptable slowdown:

```bash
# In CI — simply unset the BOMTRACE_CMD variable or set GENERATE_SBOM=false
# The build command reverts to the original:
#   ${BOMTRACE_CMD:-} make -j$(nproc)   →   make -j$(nproc)
```

This is a **one-line CI configuration change** — no code changes, no rebuild of the
build environment.

---

## Performance Impact and Mitigation

### Measured Overhead (from omnibor-analysis testing)

| Repository | Normal Build | With bomtrace3 | Overhead |
|-----------|-------------|----------------|----------|
| redis (~293K LoC) | ~1-2 min | ~2-3 min | ~40% |
| curl (~170K LoC) | ~1-2 min | ~2-3 min | ~35% |
| nmap (~420 files) | ~3-5 min | ~5-7 min | ~30% |
| FFmpeg (~1.2M LoC) | ~15 min | ~24 min | ~60% |

**Note:** FFmpeg is an extreme case — 1.2M lines of C code. Typical products with
100K-500K LoC will see 15-40% overhead.

### What Causes the Overhead

bomtrace3 is a modified strace. For every `execve`, `open`, `read`, `write`, and `close`
syscall in the build process, strace:
1. Intercepts the syscall via ptrace
2. Copies arguments from the tracee's address space
3. Logs the relevant data
4. Resumes the tracee

The overhead is proportional to the **number of compiled files**, not the size of individual
files. A project with 1000 small `.c` files has higher relative overhead than one with 100
large files.

### Mitigation Strategies

1. **Release-only instrumentation (L2)** — Only run bomtrace3 on release/tag builds.
   Daily development builds remain uninstrumented.

2. **Parallel build scaling** — bomtrace3 works with `make -j$(nproc)`. More cores reduce
   absolute build time even with overhead. On a 16-core build host, a 30% overhead on a
   2-minute build is only +36 seconds.

3. **Separate SBOM CI job** — Run the instrumented build as a parallel CI job that doesn't
   gate deployment. The uninstrumented build continues to gate testing and deployment.

4. **Caching** — If only 10 of 500 source files changed, `make` only recompiles those 10.
   bomtrace3 only traces those 10 compilations, so overhead scales with *changed* files,
   not total files. (Requires incremental build support — `cargo build` and `make` both
   support this; `go build -a` does not, but `-a` is only needed for Go.)

---

## Multi-Repo Product Support

### Problem

A Cisco product may consist of:
- `acme-core` — shared library (libacme.so)
- `acme-cli` — command-line tool linking libacme.so
- `acme-daemon` — long-running service linking libacme.so
- `acme-plugins` — loadable modules (.so files)

Each repo builds independently, but the final product is the combination.

### Solution: Composable SBOMs

Each repo generates its own SPDX SBOM independently. A final **product SBOM** is composed
by referencing the per-repo SBOMs using SPDX `ExternalDocumentRef`:

```json
{
  "spdxVersion": "SPDX-2.3",
  "name": "Cisco-Product-2.5.0",
  "packages": [
    {
      "name": "Cisco-Product",
      "versionInfo": "2.5.0",
      "primaryPackagePurpose": "APPLICATION"
    }
  ],
  "externalDocumentRefs": [
    {
      "externalDocumentId": "DocumentRef-acme-core",
      "spdxDocument": "https://spdx.cisco.com/acme-core/1.2.0",
      "checksum": { "algorithm": "SHA256", "checksumValue": "abc123..." }
    },
    {
      "externalDocumentId": "DocumentRef-acme-cli",
      "spdxDocument": "https://spdx.cisco.com/acme-cli/2.5.0",
      "checksum": { "algorithm": "SHA256", "checksumValue": "def456..." }
    }
  ],
  "relationships": [
    {
      "spdxElementId": "SPDXRef-Cisco-Product",
      "relatedSpdxElement": "DocumentRef-acme-core:SPDXRef-libacme",
      "relationshipType": "DEPENDS_ON"
    }
  ]
}
```

This is a standard SPDX pattern. The `omnibor-sbom-gen` CLI should support:
```bash
omnibor-sbom-gen compose \
  --product "Cisco Product" \
  --version "2.5.0" \
  --sbom sbom/acme-core.spdx.json \
  --sbom sbom/acme-cli.spdx.json \
  --sbom sbom/acme-daemon.spdx.json \
  --output sbom/acme-tools-product.spdx.json
```

---

## Vendored vs. System Dependencies

### System Dependencies (Primary Case)

System `-dev` packages installed via the distro package manager. These are resolved by
querying the package manager for file ownership:

```bash
# Debian/Ubuntu
dpkg-query -S /usr/lib/x86_64-linux-gnu/libssl.so  →  libssl-dev: /usr/lib/...

# RHEL/CentOS
rpm -qf /usr/lib64/libssl.so  →  openssl-devel-3.0.7-1.el9.x86_64

# Alpine
apk info --who-owns /usr/lib/libssl.so  →  openssl-dev-3.1.4-r0
```

### Vendored Dependencies

Source code copied/bundled into the repo (e.g., nmap bundles liblua, libdnet, etc.).
These are detected by:
1. **Configured vendored_dirs** — explicit paths in config (current approach)
2. **Auto-detection** (proposed) — scan for known patterns:
   - `third_party/`, `vendor/`, `deps/`, `external/`
   - Directories containing their own `Makefile` / `CMakeLists.txt` / `configure`
   - Directories with `LICENSE` or `COPYING` files

### Mixed Mode (Common in Enterprise)

Most enterprise products use both:
- System packages for OpenSSL, zlib, etc. (installed by ops/infra team)
- Vendored libs for proprietary or modified dependencies

The SBOM must distinguish between:
- `STATIC_LINK` — vendored source compiled and linked in
- `DYNAMIC_LINK` — system `.so` loaded at runtime
- `BUILD_TOOL_OF` — compiler, assembler, linker

This is **already supported** in omnibor-analysis's `spdx_from_adg.py`.

---

## Cisco Policy Compliance

### Build-Time SBOM Requirement

Cisco internal policy requires that SBOMs be generated from the **actual build process**,
not from manifest/lockfile scanning alone. This is because:

1. **Manifest ≠ Reality** — A `CMakeLists.txt` may list 20 dependencies, but the build
   might only link 15 (some conditionally compiled out). Build interception captures reality.
2. **Vendored code is invisible** — Manifest scanners cannot detect vendored C source
   code that's compiled directly. bomtrace3 sees every `.c` → `.o` → binary.
3. **Dynamic linking** — ldd-based resolution after build interception captures the actual
   runtime dependency chain.

### How OmniBOR Meets the Requirement

| Policy Requirement | OmniBOR Approach |
|-------------------|-----------------|
| Build-time SBOM | bomtrace3 intercepts actual compiler/linker calls |
| Complete dependency list | ADG captures every input file to every output binary |
| Standard format | SPDX 2.3 JSON output |
| Provenance | OmniBOR ExternalRef (gitoid) per package |
| Reproducibility | Same build + same bomtrace3 = same ADG |

---

## Recommended Modifications to omnibor-analysis

### Priority 1: Package Resolver Abstraction (Closes G1, G3)

**Effort:** ~2-3 weeks

Create a `PackageResolver` interface with distro-specific implementations:

```python
class PackageResolver(ABC):
    @abstractmethod
    def resolve_file(self, filepath: str) -> Optional[PackageInfo]:
        """Given a file path, return the package that owns it."""
        ...

class DpkgResolver(PackageResolver):    # Debian/Ubuntu — exists today
class RpmResolver(PackageResolver):      # RHEL/CentOS — new
class ApkResolver(PackageResolver):      # Alpine — new
class GenericResolver(PackageResolver):  # Fallback — file path only
```

Auto-detect at runtime:
```python
def get_resolver() -> PackageResolver:
    if shutil.which("dpkg-query"):
        return DpkgResolver()
    elif shutil.which("rpm"):
        return RpmResolver()
    elif shutil.which("apk"):
        return ApkResolver()
    else:
        return GenericResolver()
```

### Priority 2: Lightweight CLI — `omnibor-sbom-gen` (Closes G6, G7)

**Effort:** ~2-3 weeks

Extract SBOM generation from `analyze.py` into a standalone CLI:
- No repo cloning, no doc writing, no timestamp management
- Takes pre-existing ADG data and produces SBOMs
- Minimal dependencies (Python 3.8+, PyYAML)
- Can be packaged as a single-file script or PyInstaller binary

### Priority 3: Alpine/musl Validation (Closes G8)

**Effort:** ~1 week (spike)

Build bomtrace3 on Alpine, run test builds, validate ADG output. Pass/fail determines
whether Alpine gets native support or requires a glibc sidecar container.

### Priority 4: Cross-Compiler Name Detection (Closes G4, G5)

**Effort:** ~1 week

Extend bomsh's compiler detection to recognize GNU triplet-prefixed names and record
target architecture in SPDX metadata.

### Priority 5: Multi-Repo SBOM Composition (Closes G9)

**Effort:** ~1 week

Add `omnibor-sbom-gen compose` subcommand for product-level SBOMs.

### Priority 6: Native Packages — RPM, DEB, APK (Part of G2 closure)

**Effort:** ~1-2 weeks

Build packaging pipelines for `omnibor-tools` package distribution.

### Priority 7: Build Metadata Retention for Provenance (Closes G10)

**Effort:** ~1 week

Capture and retain build metadata (compiler version, build flags, environment details)
alongside SBOM artifacts to support software provenance requirements.

---

## Phased Rollout Plan

### Phase 1: Validate (Weeks 1-2)

- [ ] Set up a test build that mimics a Cisco dev team's environment (C/C++, make/cmake, RHEL or Ubuntu)
- [ ] Install bomtrace3 + bomsh on the test build host (not in our Docker container)
- [ ] Run `bomtrace3 make -j$(nproc)` on the test build
- [ ] Generate SPDX SBOM from the ADG
- [ ] Review SBOM completeness with the Cisco dev team

### Phase 2: Package Resolver + CLI (Weeks 3-5)

- [ ] Implement rpm package resolver
- [ ] Implement apk package resolver (if Alpine validation passes)
- [ ] Build `omnibor-sbom-gen` CLI
- [ ] Test on the Cisco dev team's actual build output

### Phase 3: CI Integration (Weeks 6-7)

- [ ] Create Jenkins pipeline library / GitHub Action
- [ ] Integrate into the Cisco dev team's CI as an optional parallel job
- [ ] Validate SBOM output on real release builds
- [ ] Measure and document build-time overhead

### Phase 4: Turnkey Packaging (Weeks 8-9)

- [ ] Package omnibor-tools as RPM/DEB/tarball
- [ ] Write team-facing integration guide (subset of this document)
- [ ] Hand off to Cisco dev team with documentation
- [ ] Establish support channel for ongoing questions

### Phase 5: Multi-Repo + Cross-Compile (Weeks 10-12)

- [ ] Add SBOM composition for multi-repo products
- [ ] Validate cross-compilation SBOM generation
- [ ] Add build metadata retention for software provenance

---

## Open Questions

| # | Question | Owner | Status |
|---|----------|-------|--------|
| Q1 | What are the exact Cisco-hardened distro names/versions? | Cisco Dev Team | Open |
| Q2 | What are the internal toolchain binary names? (standard gcc-12 or custom?) | Cisco Dev Team | Open |
| Q3 | What cross-compilation target triples are used? | Cisco Dev Team | Open |
| Q4 | Is there a central SBOM collection/storage system at Cisco? | Cisco Security | Open |
| Q5 | What build metadata must be retained for software provenance? | Cisco Security | Open |
| Q6 | What's the acceptable build-time overhead percentage? | Cisco Dev Team | Open |
| Q7 | Can we get access to a test build environment matching the team's setup? | Cisco Dev Team | Open |
| Q8 | Does Alpine musl support work for bomtrace3? | OmniBOR Team | Open — needs spike |
| Q9 | Are there air-gapped build environments that can't reach github.com? | Cisco Dev Team | Open |
| Q10 | What CI system does the team use specifically? | Cisco Dev Team | Open |

---

*This is a living document. Update as answers to open questions are resolved and as
implementation progresses.*
