# SPDX Output FAQ

Common questions that arise when reviewing omnibor-analysis SPDX
documents and their HTML visualizations. Each entry explains **why**
the output looks the way it does, with references to the SPDX 2.3
spec and the code that implements the behavior.

---

## Table of Contents

1. [Relationships](#1-relationships)
   - [Why is Ant / a library shown as `DEPENDS_ON` instead of `BUILD_TOOL_OF`?](#11-why-is-ant--a-library-shown-as-depends_on-instead-of-build_tool_of)
   - [What does `BUILD_TOOL_OF` actually mean?](#12-what-does-build_tool_of-actually-mean)
   - [Why is a Maven "provided" scope dependency shown as `DEPENDS_ON`?](#13-why-is-a-maven-provided-scope-dependency-shown-as-depends_on)
   - [Why are test-scope dependencies missing from the SBOM?](#14-why-are-test-scope-dependencies-missing-from-the-sbom)
   - [Why does the Go standard library show as `DEPENDS_ON`?](#15-why-does-the-go-standard-library-show-as-depends_on)
2. [Two-File Output (Analyzed vs. Build)](#2-two-file-output-analyzed-vs-build)
   - [Why are there two SPDX files per binary?](#21-why-are-there-two-spdx-files-per-binary)
   - [Why does the analyzed SBOM for Java have only 1 package?](#22-why-does-the-analyzed-sbom-for-java-have-only-1-package)
   - [Why is GCC missing from the analyzed SBOM?](#23-why-is-gcc-missing-from-the-analyzed-sbom)
   - [Why are dynamic libraries missing from the analyzed SBOM?](#24-why-are-dynamic-libraries-missing-from-the-analyzed-sbom)
   - [What does `filesAnalyzed` mean?](#25-what-does-filesanalyzed-mean)
3. [Versions](#3-versions)
   - [Why does a package show no version (versionInfo missing)?](#31-why-does-a-package-show-no-version-versioninfo-missing)
   - [Why does the root package version differ from what I expect?](#32-why-does-the-root-package-version-differ-from-what-i-expect)
   - [Why does a version show "8.19.0" when the source says "8.19.0-DEV"?](#33-why-does-a-version-show-8190-when-the-source-says-8190-dev)
4. [Java-Specific](#4-java-specific)
   - [What is a "sibling module" in the visualization?](#41-what-is-a-sibling-module-in-the-visualization)
   - [Why are transitive dependencies of a sibling module excluded?](#42-why-are-transitive-dependencies-of-a-sibling-module-excluded)
   - [Why does the comment say "Maven scope: compile" for something that looks like a build tool?](#43-why-does-the-comment-say-maven-scope-compile-for-something-that-looks-like-a-build-tool)
5. [Go-Specific](#5-go-specific)
   - [Why is the Go compiler listed separately from go-stdlib?](#51-why-is-the-go-compiler-listed-separately-from-go-stdlib)
   - [What does "indirect dependency" mean for a Go module?](#52-what-does-indirect-dependency-mean-for-a-go-module)
6. [C/C++-Specific](#6-cc-specific)
   - [Why do some vendored libraries have no version?](#61-why-do-some-vendored-libraries-have-no-version)
   - [Why is a transitive dynamic library missing from curl but present in libcurl?](#62-why-is-a-transitive-dynamic-library-missing-from-curl-but-present-in-libcurl)
7. [Visualization](#7-visualization)
   - [What do the node colors mean?](#71-what-do-the-node-colors-mean)
   - [Why do some edges look different?](#72-why-do-some-edges-look-different)

---

## 1. Relationships

### 1.1 Why is Ant / a library shown as `DEPENDS_ON` instead of `BUILD_TOOL_OF`?

**Short answer:** Because it is a library dependency, not the build tool
that compiled the project.

SPDX 2.3 Table 68 defines `BUILD_TOOL_OF` as the relationship for the
*compiler, linker, or build system* that produces the artifact — not for
library JARs that the project calls at runtime.

For example, `dependency-check` uses `org.apache.ant:ant` as an **API it
calls** to scan Ant-based projects. Maven (not Ant) compiles
dependency-check. Even though "Ant" sounds like a build tool, in this
context it is a compile-scope library.

**Rule of thumb:** If it is listed in `pom.xml` `<dependencies>` with
`compile`, `runtime`, or `provided` scope, it is `DEPENDS_ON`. If it is
the thing that *runs* `javac` or `mvn`, it is `BUILD_TOOL_OF`.

**Spec reference:** SPDX 2.3 Clause 11, Table 68
**Code:** `app/spdx/relationships.py` — `_JAVA_SCOPE_MAP` and `BUILD_TOOL_GROUP_IDS`

### 1.2 What does `BUILD_TOOL_OF` actually mean?

`BUILD_TOOL_OF` identifies software that compiled, linked, or packaged
the binary. Examples:

| Tool | Language | Why `BUILD_TOOL_OF` |
|------|----------|-------------------|
| GCC 11.4.0 | C/C++ | Compiled the .c/.cpp files into machine code |
| Go 1.22.0 | Go | Compiled and linked the Go binary |
| rustc | Rust | Compiled the Rust crate |
| javac | Java | (Implicit in Maven) Compiled .java to .class |

These tools' own code is **not present** in the output binary. GCC
produces machine code, but GCC's source code is not in the resulting
binary. That is why `BUILD_TOOL_OF` packages are excluded from the
analyzed (CISA Analyzed) SBOM but included in the build (CISA Build) SBOM.

**Code:** `app/spdx/relationships.py` — `BUILD_TOOL_BINARIES`, `BUILD_TOOL_GROUP_IDS`

### 1.3 Why is a Maven "provided" scope dependency shown as `DEPENDS_ON`?

Maven `provided` means "required at compile time but supplied by the
deployment environment at runtime" (e.g., the Servlet API in a web
container). It is still a dependency the code needs to function — just
not bundled in the artifact.

SPDX 2.3 maps this to `DEPENDS_ON`. SPDX 3.0 introduces
`hasProvidedDependency` for finer granularity, but in SPDX 2.3 there is
no separate relationship type for provided-scope deps.

The Maven scope is recorded in the package `comment` field (e.g.,
"Maven scope: provided") so consumers can distinguish it.

**Code:** `app/spdx/relationships.py` lines 24–28, `_JAVA_SCOPE_MAP`

### 1.4 Why are test-scope dependencies missing from the SBOM?

Test dependencies (`<scope>test</scope>` in Maven, `testImplementation`
in Gradle) are excluded because they do not ship in the production
binary. They are only used during `mvn test` / `gradle test`.

SPDX 2.3 does define `TEST_DEPENDENCY_OF`, but including test deps in a
production SBOM would confuse vulnerability scanners and license
compliance tools. Our build uses `mvn package -DskipTests`, and the
SPDX only reflects what is in the resulting JAR.

**Code:** `app/spdx/relationships.py` — `_JAVA_EXCLUDED_SCOPES`

### 1.5 Why does the Go standard library show as `DEPENDS_ON`?

The Go standard library (`go-stdlib`) is compiled into every Go binary.
It uses `DEPENDS_ON` because it is a *library* the binary depends on,
not the build tool. The Go *compiler* (`go`) is a separate package with
a `BUILD_TOOL_OF` relationship.

This distinction matters: `go-stdlib` code **is** in the binary (so it
appears in the analyzed SBOM), while `go` (the compiler) code **is not**
(so it only appears in the build SBOM).

**Code:** `app/spdx/emitter.py` — Go stdlib and Go compiler sections

---

## 2. Two-File Output (Analyzed vs. Build)

### 2.1 Why are there two SPDX files per binary?

Per CISA's [SBOM Types](https://www.cisa.gov/sbom) guidance:

| File | CISA Type | Contains |
|------|-----------|----------|
| `*_analyzed.spdx.json` | Analyzed | Only components compiled into the binary |
| `*_build.spdx.json` | Build | Everything used to produce the binary |

Different consumers need different views — vulnerability scanners want
the analyzed SBOM (what ships), build reproducibility auditors want the
build SBOM (everything involved).

**Full details:** [Analyzed vs. Build SBOMs](../features/analyzed-vs-build-sboms.md)

### 2.2 Why does the analyzed SBOM for Java have only 1 package?

Java projects typically produce "thin JARs" — the JAR contains only the
project's own compiled classes, not its Maven dependencies. Dependencies
are resolved at runtime via the classpath.

Since the analyzed SBOM shows only what is *compiled into* the artifact,
a thin JAR's analyzed SBOM contains only the root package. The build
SBOM contains the full Maven dependency tree.

Exception: If a project uses the Maven Shade Plugin or Assembly Plugin
to produce a "fat JAR" (uber-JAR), the analyzed SBOM would contain
bundled dependencies. This is noted in the package comment when detected.

### 2.3 Why is GCC missing from the analyzed SBOM?

GCC (or any compiler) is a build tool — its code is not compiled into
the output binary. The analyzed SBOM follows the CISA Analyzed type:
only components whose code is present in the artifact. Build tools
appear only in the `_build.spdx.json`.

**Code:** `app/spdx/emitter.py` — `static_only` parameter and
`BUILD_TOOL_OF` stripping logic

### 2.4 Why are dynamic libraries missing from the analyzed SBOM?

Dynamic libraries (`.so` files) are separate files on disk — they are
loaded at runtime by the dynamic linker, not compiled into the binary.
The analyzed SBOM includes only statically linked (embedded) components.
Dynamic libraries appear in the build SBOM with `DYNAMIC_LINK`
relationships.

### 2.5 What does `filesAnalyzed` mean?

Per SPDX 2.3 §7.8, `filesAnalyzed` indicates whether the files within
a package were actually analyzed and enumerated in the SPDX document:

- **`true`** — we inspected the package contents and the `files`
  section lists what we found
- **`false`** — we know the package exists but did NOT inspect its
  contents

| Package | `filesAnalyzed` | Why |
|---------|----------------|-----|
| Root JAR (e.g., jsoup) | `true` | bomsh traced JAR→class→source provenance |
| Dependency (e.g., jspecify) | `false` | Discovered via `mvn dependency:tree` — never opened |

Setting `filesAnalyzed: true` on a dependency whose contents were
never inspected would be a **spec violation**.

This is the norm across SPDX tooling (Syft, Trivy, CycloneDX): `true`
for packages you built (source provenance), `false` for packages you
consumed (declared dependencies).

---

## 3. Versions

### 3.1 Why does a package show no version (versionInfo missing)?

Several reasons a version may be absent:

- **Vendored C/C++ library with no standard version marker.** Some
  libraries use flat integers (`#define VERSION 250`), non-standard
  locations (changelogs, git tags, Python scripts), or simply have no
  version at all (internal sub-libraries like nmap's `nbase`).
- **Config tag has no semver.** If the `config.yaml` branch is `master`
  or a non-numeric tag like `r1rv84`, no version can be extracted.
- **dpkg metadata unavailable.** System libraries inside the container
  occasionally lack version metadata.

The pipeline intentionally omits `versionInfo` rather than guessing.
An absent version is more honest than a wrong one.

**Details:** [Version Detection — Known Limitations](../features/vendored-version-detection.md#8-known-limitations)

### 3.2 Why does the root package version differ from what I expect?

The root package version comes from the `branch` field in `config.yaml`.
For example, if `branch: v0.25.9`, the pipeline extracts `0.25.9`.

Common discrepancies:

| Situation | Example | Result |
|-----------|---------|--------|
| Tag has a prefix | `curl-8_19_0` | No version (underscores, not dots) |
| Tag is a branch name | `master` | No version |
| Tag has a non-standard format | `r1rv84` | No version |
| Source code says X.Y.Z-DEV | `8.19.0-DEV` | `8.19.0` (suffix stripped) |

If the tag fails, the pipeline falls back to file-based detection
(`Cargo.toml` for Rust, `pom.xml` for Java, VERSION files for C/C++).

**Details:** [Version Detection — Root Package](../features/vendored-version-detection.md#3-root-package-version-detection)

### 3.3 Why does a version show "8.19.0" when the source says "8.19.0-DEV"?

Development suffixes like `-DEV`, `-SNAPSHOT`, `-rc1` are intentionally
stripped from the `versionInfo` field. SPDX consumers (vulnerability
databases, license scanners) match on the release version, and a `-DEV`
suffix would cause false negatives in CVE matching.

The full unmodified version string is available in the source code and
build logs. The SPDX `versionInfo` field reflects the release version
the build is based on.

---

## 4. Java-Specific

### 4.1 What is a "sibling module" in the visualization?

In a multi-module Maven project (reactor build), the root POM contains
multiple sub-modules that share the same `groupId`. For example,
`dependency-check` has modules like `dependency-check-core`,
`dependency-check-cli`, and `dependency-check-utils`.

When generating the SPDX for `dependency-check-cli`, its sibling modules
appear with a `DEPENDS_ON` relationship and a comment: "Sibling module. See:
dependency-check-core-9.2.0_build.spdx.json". This tells you the
sibling has its own separate SPDX document with its own dependency tree.

**Code:** `app/spdx/java_generator.py` — sibling detection via matching `groupId`

### 4.2 Why are transitive dependencies of a sibling module excluded?

To avoid duplicating the same dependency tree across sibling SPDX files.
If `dependency-check-cli` depends on `dependency-check-core`, and
`dependency-check-core` depends on `commons-io`, then `commons-io`
appears in `dependency-check-core`'s SPDX — not in
`dependency-check-cli`'s.

This keeps each SBOM focused and avoids inflating package counts with
duplicates. The sibling reference tells consumers where to find the full
transitive tree.

**Code:** `app/spdx/java_generator.py` — BFS to find sibling-transitive deps

### 4.3 Why does the comment say "Maven scope: compile" for something that looks like a build tool?

The `comment` field records the Maven scope as-is from `mvn
dependency:tree`. If a library like `org.apache.ant:ant` is declared
with `<scope>compile</scope>` in the POM, the comment will say
"Maven scope: compile" even if the library's name suggests it is a
build tool.

The SPDX relationship type is determined by the **scope**, not the
library name. See [§1.1](#11-why-is-ant--a-library-shown-as-depends_on-instead-of-build_tool_of).

---

## 5. Go-Specific

### 5.1 Why is the Go compiler listed separately from go-stdlib?

They serve different roles:

| Package | Relationship | In Analyzed SBOM? | Purpose |
|---------|-------------|-------------------|---------|
| `go` | `BUILD_TOOL_OF` | No | The compiler that produced the binary |
| `go-stdlib` | `DEPENDS_ON` | Yes | Standard library code compiled into the binary |

Go statically links stdlib into every binary, so its code is physically
present in the artifact. The compiler is not.

### 5.2 What does "indirect dependency" mean for a Go module?

A Go module marked "indirect" in `go.mod` is not imported directly by
the project's own code — it is pulled in transitively by a direct
dependency. The comment in the SPDX package says "Indirect dependency
vendored via go mod vendor."

Both direct and indirect dependencies are compiled into the binary
(Go links statically). The distinction is about the dependency graph,
not about what ships.

---

## 6. C/C++-Specific

### 6.1 Why do some vendored libraries have no version?

Common reasons:

| Library | Why no version |
|---------|---------------|
| `nbase`, `libnetutil` (nmap) | Internal sub-library, no independent version |
| `fast_float` (redis) | Version in C++ namespace, not in a standard location |
| `hdr_histogram` (redis) | No standard version marker |
| `liblinear` (nmap) | Flat integer `#define LIBLINEAR_VERSION 250` — ambiguous |

The detector uses 12 strategies but intentionally avoids guessing. See
[Version Detection — Known Limitations](../features/vendored-version-detection.md#8-known-limitations).

### 6.2 Why is a transitive dynamic library missing from curl but present in libcurl?

The curl project produces two binaries:

- **`curl`** (CLI) — links directly against `libcurl.so`, `libc.so`,
  `libz.so` only
- **`libcurl.so`** — links against `libssl`, `libnghttp2`, `libbrotli`,
  etc.

Each binary gets its own SPDX. The curl CLI's SBOM shows only its 3
direct `NEEDED` entries (from `readelf -d`). The transitive libraries
(OpenSSL, etc.) belong to libcurl's SBOM because that is where the
linkage occurs.

This is correct per SPDX — each document describes one artifact and
its direct dependencies. Consumers should follow the chain: curl →
libcurl.so → libssl3, etc.

---

## 7. Visualization

### 7.1 What do the node colors mean?

In the interactive HTML visualization:

| Color | Meaning |
|-------|---------|
| **Purple** | Root binary (the package being analyzed) |
| **Teal** | Vendored/statically linked library (`STATIC_LINK`) |
| **Blue** | Dynamically linked system library (`DYNAMIC_LINK`) |
| **Orange** | Build tool (`BUILD_TOOL_OF`) — compiler, linker |
| **Green** | Runtime dependency (`DEPENDS_ON`) — Go modules, Maven deps |

### 7.2 Why do some edges look different?

Edge styles indicate relationship types:

| Style | Relationship |
|-------|-------------|
| Solid line | `STATIC_LINK` or `DEPENDS_ON` |
| Dashed line | `DYNAMIC_LINK` |
| Dotted line | `BUILD_TOOL_OF` |

---

## Further Reading

- [Analyzed vs. Build SBOMs](../features/analyzed-vs-build-sboms.md) — full two-file design
- [Version Detection](../features/vendored-version-detection.md) — 12 vendored strategies + root version
- [SPDX 2.3 Relationship Types](https://spdx.github.io/spdx-spec/v2.3/relationships-between-SPDX-elements/) — official spec

---

*Last updated: April 29, 2026*
