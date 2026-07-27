# Analyzed vs. Build SBOMs: Two-File Approach

This document explains why bisbom-gen generates **two** distinct SPDX 2.3
SBOMs per binary artifact, what each contains, and how the design aligns with
CISA guidance and industry best practices.

---

## Table of Contents

1. [Background: The Problem with a Single SBOM](#1-background-the-problem-with-a-single-sbom)
2. [CISA SBOM Types](#2-cisa-sbom-types)
3. [Our Two-File Approach](#3-our-two-file-approach)
4. [What Goes in Each SBOM](#4-what-goes-in-each-sbom)
5. [`BUILD_TOOL_OF` Exclusion](#5-build_tool_of-exclusion)
6. [Naming Conventions](#6-naming-conventions)
7. [Implementation Details](#7-implementation-details)
8. [Use Cases](#8-use-cases)
9. [SPDX Relationship Types by SBOM Type](#9-spdx-relationship-types-by-sbom-type)
10. [Examples from Real Projects](#10-examples-from-real-projects)

---

## 1. Background: The Problem with a Single SBOM

Early versions of bisbom-gen produced a single `_adg.spdx.json` file per
binary. This combined everything the build system touched into one document:
vendored libraries compiled into the binary, dynamically linked system
libraries, transitive Maven dependencies, and build tools like GCC or the Go
compiler.

This created confusion:

- **Vulnerability scanners** received false positives from dynamic libraries
  that were not actually embedded in the artifact.
- **License compliance** tools could not distinguish between code compiled into
  a binary (strong copyleft concern) and code merely linked at runtime.
- **Build reproducibility** auditors wanted the full dependency graph, but
  security analysts wanted only what ships inside the artifact.

A single SBOM tries to serve every audience and serves none of them well.

## 2. CISA SBOM Types

The Cybersecurity and Infrastructure Security Agency (CISA) defines several SBOM
types in their "Types of Software Bill of Materials (SBOM)" document:

| CISA Type | Focus | When Produced |
|-----------|-------|---------------|
| **Analyzed** | Components actually present in the artifact | Post-build, from binary analysis or build instrumentation |
| **Build** | Everything used to produce the artifact | During build, from dependency resolution + build tooling |
| Design | Planned/intended components | Pre-build, from design specs |
| Source | Components in the source tree | Pre-build, from manifest files |
| Deployed | What is installed on a system | Post-deploy |
| Runtime | What is loaded during execution | Runtime observation |

Our two-file approach maps directly to the first two:

- **`_analyzed.spdx.json`** → CISA Analyzed SBOM
- **`_build.spdx.json`** → CISA Build SBOM

## 3. Our Two-File Approach

### Before (single file)

```
nmap_adg.spdx.json
├── nmap 8.19.0-DEV          (root binary)
├── liblua 5.4.8             (vendored, statically linked)
├── libssh2 1.11.1           (vendored, statically linked)
├── libc6 2.35               (dynamic, system library)
├── libssl3 3.0.2            (dynamic, system library)
├── gcc 11.4.0               (build tool, not in binary)
└── ... everything mixed together
```

### After (two files)

```
nmap_analyzed.spdx.json       # What's IN the binary
├── nmap 8.19.0-DEV           (root binary)
├── liblua 5.4.8              (vendored, STATIC_LINK)
├── libssh2 1.11.1            (vendored, STATIC_LINK)
├── libdnet-stripped 1.18.0   (vendored, STATIC_LINK)
└── ... only embedded components

nmap_build.spdx.json          # Everything used to BUILD the binary
├── nmap 8.19.0-DEV           (root binary)
├── liblua 5.4.8              (vendored, STATIC_LINK)
├── libssh2 1.11.1            (vendored, STATIC_LINK)
├── libc6 2.35                (dynamic, DYNAMIC_LINK)
├── libssl3 3.0.2             (dynamic, DYNAMIC_LINK)
├── gcc 11.4.0                (BUILD_TOOL_OF)
└── ... full dependency graph
```

## 4. What Goes in Each SBOM

### Analyzed SBOM (`_analyzed.spdx.json`)

Contains **only components whose code is compiled into the binary**:

- The root binary package itself
- Vendored/statically linked libraries (`STATIC_LINK` relationship)
- For Java: nothing beyond the root JAR (Maven deps are not bundled in
  thin JARs)
- For Rust: crate code compiled into the final binary
- For Go: Go module code compiled into the final binary

**Excludes:**
- Dynamically linked system libraries (`DYNAMIC_LINK`)
- Build tools (`BUILD_TOOL_OF`) — GCC, Go compiler, etc.
- Transitive dependencies not compiled in (`DEPENDS_ON` for non-embedded)

### Build SBOM (`_build.spdx.json`)

Contains **everything involved in producing the binary**:

- Everything in the analyzed SBOM, plus:
- Dynamically linked system libraries (`DYNAMIC_LINK`)
- Build tools: GCC, Go compiler, rustc (`BUILD_TOOL_OF`)
- Transitive dependencies (`DEPENDS_ON`)
- For Java: all Maven compile/runtime/provided scope dependencies

## 5. `BUILD_TOOL_OF` Exclusion

Build tools like GCC are recorded in the SPDX with a `BUILD_TOOL_OF`
relationship. These tools are essential for reproducibility but their code is
**not compiled into the output binary** (the compiler produces machine code, but
the compiler's own code does not end up in the result).

The exclusion is implemented generically in `app/spdx/emitter.py` as a
post-processing step at the end of the `emit()` method:

```python
# When static_only (CISA Analyzed), strip all
# BUILD_TOOL_OF relationships and their orphaned
# packages.
if static_only:
    build_tool_ids = {
        r["spdxElementId"]
        for r in doc["relationships"]
        if r["relationshipType"] == "BUILD_TOOL_OF"
    }
    doc["relationships"] = [
        r for r in doc["relationships"]
        if r["relationshipType"] != "BUILD_TOOL_OF"
    ]
    # Remove packages only referenced by build rels
    still_used = set()
    for r in doc["relationships"]:
        still_used.add(r["spdxElementId"])
        still_used.add(r["relatedSpdxElement"])
    orphans = build_tool_ids - still_used
    if orphans:
        doc["packages"] = [
            p for p in doc["packages"]
            if p["SPDXID"] not in orphans
        ]
```

This approach is **generic** — it works for any current or future build tool
without hard-coding specific tool names. If a new build tool type is added to
the pipeline, it will automatically be excluded from analyzed SBOMs as long as
it uses the `BUILD_TOOL_OF` relationship type.

## 6. Naming Conventions

### File naming

```
{binary}_analyzed.spdx.json    # CISA Analyzed SBOM
{binary}_build.spdx.json       # CISA Build SBOM
{binary}.syft.spdx.json        # Syft manifest baseline
{binary}_analyzed.spdx.html    # Interactive visualization
{binary}_build.spdx.html       # Interactive visualization
```

### SPDX document naming (inside the JSON)

```json
{
  "name": "nmap-analyzed-spdx",
  "documentNamespace": "https://spdx.org/spdxdocs/nmap-analyzed-<uuid>"
}
```

The `_analyzed` / `_build` suffixes align with CISA terminology and are
immediately recognizable to anyone familiar with the SBOM type taxonomy.

### Legacy naming

The previous `_adg.spdx.json` suffix (Artifact Dependency Graph) has been
retired. The regression test framework still accepts `_adg` files for backward
compatibility during the transition but new golden files use only `_analyzed`
and `_build`.

## 7. Implementation Details

### Pipeline flow

The pipeline calls the SPDX generator twice per binary:

```python
# In app/pipeline/adg_spdx.py
# First pass: analyzed SBOM
gen.generate(
    binary_name=binary,
    static_only=True,   # Only embedded components
    suffix="_analyzed",
)

# Second pass: build SBOM
gen.generate(
    binary_name=binary,
    static_only=False,   # Full dependency graph
    suffix="_build",
)
```

### The `static_only` parameter

The `static_only` flag in `app/spdx/emitter.py` controls what gets included:

| Component | `static_only=True` | `static_only=False` |
|-----------|--------------------|---------------------|
| Root binary | Yes | Yes |
| Vendored/static libs | Yes | Yes |
| Dynamic system libs | No | Yes |
| Build tools (GCC, Go, etc.) | No | Yes |
| Maven dependencies | No | Yes |
| Transitive deps | No | Yes |

### Java-specific behavior

For Java, the analyzed SBOM contains only the root JAR because Maven
dependencies are not bundled into thin JARs (they are classpath dependencies
resolved at runtime). The build SBOM contains all Maven compile, runtime, and
provided-scope dependencies with their full transitive tree.

## 8. Use Cases

### Vulnerability scanning (use Analyzed SBOM)

A vulnerability scanner should use the analyzed SBOM because it contains only
components whose code is actually present in the artifact. Scanning the build
SBOM would produce false positives for dynamic libraries that may be patched
independently on the deployment system.

### License compliance (use Analyzed SBOM)

For copyleft license analysis, the analyzed SBOM tells you exactly which code
is compiled into the binary. A statically linked GPL library has different
implications than a dynamically linked one.

### Build reproducibility (use Build SBOM)

For reproducing a build, the build SBOM provides the complete picture: which
compiler version was used, which system libraries were available, and the full
transitive dependency tree.

### Supply chain audit (use both)

For a comprehensive supply chain audit, both SBOMs together provide the full
picture — what is in the artifact and what was used to produce it.

## 9. SPDX Relationship Types by SBOM Type

| Relationship | Analyzed | Build | Meaning |
|-------------|----------|-------|---------|
| `STATIC_LINK` | Yes | Yes | Library code compiled into binary |
| `DYNAMIC_LINK` | No | Yes | Runtime shared library dependency |
| `BUILD_TOOL_OF` | No | Yes | Compiler/toolchain used to build |
| `DEPENDS_ON` | Partial | Yes | Transitive dependency (only if embedded) |
| CONTAINS | Yes | Yes | Source files belonging to a package |

## 10. Examples from Real Projects

### nmap (C/C++ with vendored libraries)

**Analyzed** (8 packages): nmap + 7 vendored libs (liblua, libssh2,
libdnet-stripped, liblinear, libnetutil, nbase, nsock)

**Build** (23 packages): everything above + 12 dynamic system libs (libc6,
libssl3, libpcap0.8, etc.) + gcc

### redis (C with vendored libraries)

**Analyzed** (9 packages): redis-server + 8 vendored libs (jemalloc, lua,
hiredis, xxhash, linenoise, fpconv, fast_float, hdr_histogram)

**Build** (12 packages): everything above + libc6, libgcc-s1, gcc

### checkstyle (Java with Maven dependencies)

**Analyzed** (1 package): just the checkstyle JAR (thin JAR, no bundled deps)

**Build** (many packages): checkstyle + all compile/runtime/provided Maven
dependencies with transitive tree

### lazygit (Go)

**Analyzed** (1 package): the lazygit binary (Go statically links everything)

**Build** (many packages): lazygit + all Go module dependencies + Go compiler

---

*Last updated: March 12, 2026*
