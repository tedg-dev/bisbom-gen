# Python Build-Time SPDX SBOM Design

| | |
|---|---|
| **Audience** | OmniBOR/bomsh maintainers, engineering team |
| **Companion docs** | [Cross-Language Build Timing](cross-language-build-timing-improvements.md), [Source Reference](omnibor-interception-source-reference.md) |
| **Last updated** | April 2026 |

---

## Table of Contents

1. [Current State: What bomsh/OmniBOR Does Today for Python](#1-current-state)
2. [What bomsh Does for Other Languages (Comparison)](#2-comparison)
3. [Python Packaging Fundamentals](#3-python-packaging)
4. [Gaps: What Is Missing for Python SBOM](#4-gaps)
5. [Python-Specific Challenges](#5-challenges)
6. [Wheels and C Extensions: Metadata Extraction](#6-wheels-c-extensions)
7. [Proposed Architecture for omnibor-analysis](#7-architecture)
8. [Implementation Plan](#8-implementation)
9. [Target Repos for Validation](#9-target-repos)

---

<a id="1-current-state"></a>

## 1. Current State: What bomsh/OmniBOR Does Today for Python

### bomsh_pylib.py — Runtime Import Dependency Analysis

The only Python tool in bomsh is **`bomsh_pylib.py`** (added Oct 2023,
PR [#51](https://github.com/omnibor/bomsh/pull/51), author: Yongkui Han).

**What it does:**

1. **Static AST analysis** of Python source files using the `ast` module
2. Visits every `import` and `from X import Y` statement
3. Resolves each import to an actual `.py` file on disk via
   `importlib.import_module()` — this means the module must be
   **installed** in the current Python environment to be resolved
4. Handles relative imports by converting to absolute module paths
5. Recursively follows all imported modules to build a full dependency tree
6. Detects and breaks recursion loops in circular imports
7. Handles `try/except ImportError` patterns (common for optional deps)
8. Special handling for empty `__init__.py` files — concatenates all
   `.py` files in the package directory and hashes the result
   (PR [#54](https://github.com/omnibor/bomsh/pull/54))

**Outputs:**

| Output | Description |
|--------|-------------|
| `raw_logfile.sha1` / `.sha256` | Artifact dependency fragments (ADFs) in bomsh format — compatible with `bomsh_create_bom.py` |
| `bomsh_pylib_jsonfile-result.json` | Full recursive dependency tree as nested JSON |
| `bomsh_pylib_jsonfile-pylibs-db.json` | Module name → file path mapping |
| `bomsh_pylib_jsonfile-pyfile-imports.json` | Per-file import details (line numbers, import statements) |

**CLI usage:**

```bash
# Analyze specific files
bomsh_pylib.py -f script1.py,script2.py --hashtype sha1,sha256

# Analyze all .py in a directory
bomsh_pylib.py -d /path/to/project --hashtype sha256

# Then create OmniBOR ADG from the raw_logfile
bomsh_create_bom.py -r /tmp/bomsh_pylib_raw_logfile.sha256 -b omnibor_dir --hashtype sha256

# Then search for CVEs
bomsh_search_cve.py -vvv -b omnibor_dir -f script1.py --hashtype sha256
```

**How hashing works:**

- Uses `git hash-object` for SHA1 (git blob format)
- Uses shell command `printf "blob $(wc -c < file)\0" | cat - file | sha256sum`
  for SHA256 (git blob format with SHA256)
- Results cached in `g_git_file_hash_cache` dict to avoid re-hashing

**How the raw_logfile ADF format works:**

Each dependency fragment looks like:
```
outfile: <sha256-of-script.py> path: /path/to/script.py
infile: <sha256-of-imported-module1.py> path: /path/to/module1.py
infile: <sha256-of-imported-module2.py> path: /path/to/module2.py
build_cmd: bomsh_py_deps /path/to/script.py
==== End of raw info for this process
```

This is the **same format** used by `bomsh_hook2.py` for C/C++/Go/Rust
builds, meaning the output feeds directly into `bomsh_create_bom.py` and
the rest of the OmniBOR pipeline.

### bomsh_hook2.py — No Python Awareness

`bomsh_hook2.py` (the build-time interception hook) has **zero Python
awareness**. It only understands:

| Language | Recognized Programs | Parsing Function |
|----------|-------------------|------------------|
| **C/C++** | `gcc`, `g++`, `clang`, `clang++`, `ld`, `ld.bfd`, `ld.gold`, `ar`, `strip` | Command-line arg parsing for `-o`, `-c`, input `.c`/`.o` files |
| **Rust** | `rustc` | `get_all_subfiles_in_rustc_cmdline()` |
| **Go** | `compile`, `link` (Go toolchain) | `get_all_subfiles_in_golang_compile_cmdline()`, `get_all_subfiles_in_golang_link_cmdline()` |
| **Java** | *(separate script)* | `bomsh_create_bom_java.py` scans workspace |
| **Python** | ❌ **Nothing** | No `pip`, `setuptools`, `python3 setup.py`, `maturin`, etc. |

If you run `bomtrace2 pip install numpy`, bomtrace2 would intercept the
`gcc`/`g++` calls that compile numpy's C extensions, but it would **not**
understand that these are part of a pip package, would not extract package
metadata, and would not produce a useful SPDX.

### bomsh_search_cve.py — Works with Python via bomsh_pylib.py

The CVE search script can consume the `raw_logfile` and OmniBOR database
produced by `bomsh_pylib.py`. It maps source file hashes to known CVE
ranges in git history. This works for Python the same way it works for
C/C++ — the CVE is identified by which version of a source file's git
blob hash falls within a vulnerable range.

### Summary: What Exists vs. What's Missing

| Capability | Status | Tool |
|------------|--------|------|
| Static import analysis (`.py` → imported `.py`) | ✅ Working | `bomsh_pylib.py` |
| Raw logfile / ADF generation | ✅ Working | `bomsh_pylib.py` → `bomsh_create_bom.py` |
| OmniBOR ADG / treedb generation | ✅ Working | `bomsh_create_bom.py` (consumes raw_logfile) |
| CVE search on Python source hashes | ✅ Working | `bomsh_search_cve.py` |
| Snapshot ID for Python run environment | ✅ Working | `bomsh_pylib.py` |
| **pip package metadata** (name, version, author, license) | ❌ Missing | — |
| **pip dependency tree** (transitive deps) | ❌ Missing | — |
| **Wheel / .dist-info parsing** | ❌ Missing | — |
| **C extension .so detection** in wheels | ❌ Missing | — |
| **SPDX SBOM generation** for Python | ❌ Missing | — |
| **Build-time interception** of `pip install` | ❌ Missing | — |
| **venv support** | ❌ Noted as TODO | Comment in bomsh_pylib.py: "will investigate venv later" |

---

<a id="2-comparison"></a>

## 2. What bomsh Does for Other Languages (Comparison)

Understanding how bomsh handles C/C++, Rust, Go, and Java reveals patterns
we can reuse — and gaps that are Python-specific.

### Build Interception by Language

| Aspect | C/C++ | Rust | Go | Java | **Python** |
|--------|-------|------|----|------|------------|
| **Tracer** | `bomtrace3` (modified strace) | `bomtrace2` (modified strace) | `bomtrace2 -c bomtrace_go.conf` | `strace` (stock) | ❌ None |
| **Hook script** | `bomsh_hook.c` (in-process C) | `bomsh_hook2.py` (per-event Python) | `bomsh_hook2.py` (per-event Python) | `bomsh_create_bom_java.py` (post-build) | `bomsh_pylib.py` (static analysis, no tracer) |
| **Syscalls traced** | All | execve only | execve + openat | openat only | N/A |
| **Input file discovery** | Command-line parsing of cc/ld args | `rustc` command-line parsing | `compile`/`link` command-line + openat | Workspace scan (`.java` → `.class` → `.jar`) | AST `import`/`from` parsing |
| **Output artifact** | Binary (ELF) | Binary (ELF) or `.rlib` | Binary (ELF) | `.jar` | `.py` file (runtime dependency) |
| **Dependency graph** | ADG treedb (linker inputs) | ADG treedb + `Cargo.lock` | ADG treedb + `go.mod` | treedb + `mvn dependency:tree` | Import tree JSON only |
| **SPDX generation** | `bomsh_sbom.py` | `bomsh_sbom.py` | `bomsh_sbom.py` | ❌ (omnibor-analysis's `JavaSpdxGenerator`) | ❌ None |
| **Package metadata** | System packages via dpkg/rpm | `Cargo.toml` / `Cargo.lock` | `go.mod` / `go.sum` | `pom.xml` + `mvn dependency:tree` | ❌ None |

### Key Observation: bomsh_pylib.py Is Analogous to bomsh_dynlib.py

`bomsh_pylib.py` was explicitly designed as the **Python equivalent of
`bomsh_dynlib.py`** (ELF runtime dependency analysis). Both produce:
- A raw_logfile of dependency fragments
- A JSON dependency tree
- A "snapshot ID" for a runtime environment

Neither is a build-time interception tool. Both are **post-hoc analysis
tools** that examine an already-built environment.

### Key Observation: Java Shows the Path

Java also lacks direct build-time interception in bomsh (unlike C/C++
which uses `bomsh_hook.c` in-process). Instead, Java uses:
1. Stock `strace` for file I/O tracing
2. `bomsh_create_bom_java.py` for post-build workspace scanning
3. **External dependency graph** from `mvn dependency:tree`

Python can follow this same pattern:
1. Optional `strace` for `pip install` file I/O tracing
2. `bomsh_pylib.py` for source-level import analysis (already exists)
3. **External dependency graph** from pip metadata / `pipdeptree`

The Java analogy is the closest because both languages:
- Don't produce native binaries (bytecode / interpreted)
- Have package managers with rich metadata (Maven Central / PyPI)
- Use post-build analysis rather than compiler interception

---

<a id="3-python-packaging"></a>

## 3. Python Packaging Fundamentals

### Package Types

| Type | Extension | Contents | When Used |
|------|-----------|----------|-----------|
| **Wheel** (binary) | `.whl` | Pre-compiled `.so`/`.pyd` + `.py` + metadata | Default for most installs |
| **sdist** (source) | `.tar.gz` | Pure source + `pyproject.toml` / `setup.py` | Fallback when no wheel matches |
| **Egg** (legacy) | `.egg` | Deprecated, equivalent to sdist | Legacy `easy_install` |

### Metadata Available After `pip install`

Every installed package has a `.dist-info/` directory in `site-packages/`:

```
site-packages/
├── requests/
│   ├── __init__.py
│   ├── api.py
│   └── ...
├── requests-2.31.0.dist-info/
│   ├── METADATA          # Name, Version, Author, License, Requires-Dist
│   ├── RECORD            # SHA256 hash + size of every installed file
│   ├── WHEEL             # Wheel build tag, Python version, ABI tag
│   ├── INSTALLER         # "pip"
│   ├── licenses/         # License files (PEP 639, metadata ≥ 2.4)
│   ├── sboms/            # SBOM files (new PEP, if publisher provides)
│   └── entry_points.txt  # Console scripts, plugins
```

### Key Metadata Fields (PEP 566 / Core Metadata)

| Field | SPDX Mapping | Source |
|-------|-------------|--------|
| `Name` | `PackageName` | METADATA |
| `Version` | `PackageVersion` | METADATA |
| `Author` / `Author-email` | `PackageSupplier` | METADATA |
| `License` / `License-Expression` | `PackageLicenseConcluded` | METADATA (PEP 639 adds SPDX expressions) |
| `Requires-Dist` | `DEPENDS_ON` relationships | METADATA |
| `Home-page` / `Project-URL` | `PackageHomePage` | METADATA |
| `Summary` | `PackageDescription` | METADATA |

### RECORD File: File-Level Integrity

The `RECORD` file lists every installed file with SHA256 hash:

```csv
requests/__init__.py,sha256=abc123...,4521
requests/api.py,sha256=def456...,8903
requests-2.31.0.dist-info/METADATA,sha256=ghi789...,58841
```

**This is the Python equivalent of the bomsh treedb** — it provides
file-level provenance for every component in the installed environment.

### Dependency Resolution: `importlib.metadata`

Python 3.8+ provides `importlib.metadata` for programmatic access:

```python
from importlib.metadata import metadata, requires

m = metadata("requests")
m["Name"]           # "requests"
m["Version"]        # "2.31.0"
m["Author"]         # "Kenneth Reitz"
m["License"]        # "Apache 2.0"

requires("requests")
# ['charset-normalizer<4,>=2', 'idna<4,>=2.5', 'urllib3<3,>=1.21.1', ...]
```

### Dependency Tree: `pipdeptree`

For the full transitive graph (equivalent to `mvn dependency:tree`):

```bash
pipdeptree --json-tree
```

Returns nested JSON with direct and transitive dependencies, versions,
and required version ranges.

---

<a id="4-gaps"></a>

## 4. Gaps: What Is Missing for Python SBOM

Based on the comparison with other languages, these are the specific gaps
that must be filled for a complete Python SBOM pipeline:

1. **No package-level metadata extraction** — `bomsh_pylib.py` maps `.py`
   files to imported `.py` files. It does not know that `requests/__init__.py`
   belongs to the `requests` package version 2.31.0 by Kenneth Reitz. For
   SPDX, we need Name, Version, Author, License, and Download URL.

2. **No pip dependency graph** — The import tree from `bomsh_pylib.py` is a
   file-level graph (which `.py` imports which `.py`). SPDX needs a
   package-level graph (`requests` DEPENDS_ON `urllib3`, `charset-normalizer`,
   etc.) with version constraints.

3. **No wheel/dist-info awareness** — Every pip-installed package has a
   `.dist-info/` directory with `METADATA` (name, version, author, license,
   dependencies) and `RECORD` (SHA256 hashes of every installed file).
   bomsh ignores this entirely.

4. **No C extension handling** — Packages like `numpy`, `cryptography`, and
   `pillow` bundle compiled `.so` shared libraries. These need to be:
   - Detected as binary components
   - Listed in the SPDX with CONTAINS relationships
   - Optionally analyzed with `ldd`/`readelf` for bundled native deps

5. **No SPDX emission** — `bomsh_sbom.py` does not have a Python code path.
   There is no `bomsh_spdx_pypi.py` equivalent to `bomsh_spdx_deb.py` or
   `bomsh_spdx_rpm.py`.

6. **No venv awareness** — `bomsh_pylib.py` uses the system Python's
   `sys.path` for import resolution. It cannot target a specific virtualenv
   (the source code contains the comment "will investigate venv later").

7. **No PURL generation** — No `pkg:pypi/<name>@<version>` external
   references are produced.

---

### What Each Language Needs for a Complete SPDX

| Requirement | C/C++ | Rust | Go | Java | Python |
|-------------|-------|------|----|------|--------|
| **Source file → binary mapping** | ADG treedb (bomtrace3) | ADG treedb (bomtrace2) | ADG treedb (bomtrace2) | bomsh treedb (strace) | `RECORD` file (pip) |
| **Dependency graph** | `ldd` + treedb | `Cargo.lock` / `Cargo.toml` | `go.mod` / `go.sum` | `mvn dependency:tree` | `importlib.metadata` / `pipdeptree` |
| **Version detection** | `VendoredVersionDetector` (12 strategies) | `Cargo.lock` | `go.mod` | `pom.xml` | `METADATA` Version field |
| **License detection** | Header scanning / `VendoredVersionDetector` | `Cargo.toml` | Module LICENSE files | POM `<licenses>` | `METADATA` License / License-Expression |
| **Package URL (PURL)** | `pkg:deb/...` (system libs) | `pkg:cargo/...` | `pkg:golang/...` | `pkg:maven/...` | `pkg:pypi/...` |
| **Build tracer** | bomtrace3 (ptrace) | bomtrace2 (ptrace) | bomtrace2 (ptrace) | strace (openat) | **Not needed** for metadata approach |

### Key Insight: Python Is Closest to Java

Java's pipeline already solved the "no linker" problem:
- Java has no native linker; dependencies come from Maven, not the compiler
- Python has no native linker; dependencies come from pip, not the compiler
- Both use **post-build analysis** rather than build-time interception
- Both have **rich declarative metadata** (POM ↔ METADATA)

The Java pipeline pattern — `strace` wrapper + workspace scan + package manager
metadata — maps directly to Python with pip replacing Maven.

### Key Insight: Python Metadata Is Richer Than All Other Languages

Python's `.dist-info/METADATA` file provides **more SPDX-ready data** than
any other language's native metadata:

| Data Point | C/C++ | Rust | Go | Java | **Python** |
|------------|-------|------|----|------|------------|
| Name | ❌ (inferred) | ✅ Cargo.toml | ✅ go.mod | ✅ pom.xml | ✅ METADATA |
| Version | ❌ (12-strategy detector) | ✅ Cargo.lock | ✅ go.mod | ✅ pom.xml | ✅ METADATA |
| Author | ❌ | ✅ Cargo.toml | ❌ | ❌ (POM varies) | ✅ METADATA |
| License (SPDX expr) | ❌ | ✅ Cargo.toml | ❌ | ❌ | ✅ License-Expression (PEP 639) |
| Dependencies | ❌ (runtime only) | ✅ Cargo.lock | ✅ go.sum | ✅ mvn dep:tree | ✅ Requires-Dist |
| File hashes | ✅ ADG treedb | ✅ ADG treedb | ✅ ADG treedb | ✅ treedb | ✅ RECORD (SHA256) |
| Download URL | ❌ | ✅ crates.io | ✅ proxy.golang.org | ✅ Maven Central | ✅ PyPI JSON API |

---

<a id="5-challenges"></a>

## 5. Python-Specific Challenges

### Challenge 1: Pure Python vs. C Extension Packages

| Category | Examples | % of PyPI | Complexity |
|----------|----------|-----------|------------|
| **Pure Python** | requests, flask, django | ~75% | Low — all metadata in METADATA |
| **C extension (wheel)** | numpy, cryptography, pillow | ~20% | Medium — bundled `.so` files |
| **C extension (sdist)** | some scientific packages | ~5% | High — requires compilation |

### Challenge 2: Bundled Native Libraries in Wheels

Binary wheels for packages like `cryptography`, `numpy`, and `pillow`
bundle compiled `.so` shared libraries inside the wheel:

```
cryptography-42.0.0-cp312-abi3-manylinux_2_28_x86_64.whl
├── cryptography/
│   ├── hazmat/bindings/_rust.abi3.so    # Rust-compiled, ~15MB
│   └── ...
├── cryptography-42.0.0.dist-info/
│   ├── METADATA
│   ├── RECORD                           # SHA256 of _rust.abi3.so
│   └── ...
```

**What we know about the bundled `.so`:**
- **Name**: from the parent package (`cryptography`)
- **Version**: from METADATA `Version` field
- **Author**: from METADATA `Author` field
- **License**: from METADATA `License-Expression`
- **Hash**: from RECORD file (SHA256)
- **Platform**: from wheel filename tag (`manylinux_2_28_x86_64`)

**What we DON'T know without deeper analysis:**
- Which C/Rust libraries were statically linked into the `.so`
- Versions of those statically linked libraries (e.g., OpenSSL version
  bundled into `cryptography`)
- Whether the `.so` has additional dynamic dependencies

### How to Handle Bundled `.so` Files

**Approach 1: RECORD-based (recommended for Phase 1)**
- List the `.so` as a `FILE` entry in SPDX with its RECORD hash
- Annotate with `primaryPackagePurpose: LIBRARY`
- Mark relationship as `CONTAINS` from the parent package
- Version, author, license inherited from parent package METADATA

**Approach 2: ELF analysis (Phase 2 enhancement)**
- Run `ldd` / `readelf` on installed `.so` files to discover dynamic deps
- Cross-reference with system package database (`dpkg -S libssl.so`)
- Add `DYNAMIC_LINK` relationships (same as C/C++ pipeline)
- Uses existing `app/spdx/resolver.py` `ComponentResolver` logic

**Approach 3: auditwheel inspection (Phase 2 enhancement)**
- Parse the wheel filename for manylinux tag
- `auditwheel show <wheel>` lists bundled external shared libraries
- Provides exact versions of bundled system libraries

### Challenge 3: Build-from-Source (sdist) Packages

When pip builds from source (no matching wheel), it invokes:
1. `pip install` downloads the sdist
2. Runs `pyproject.toml` build backend (setuptools, flit, hatch, maturin)
3. If C extensions: calls `gcc`/`g++`/`rustc` to compile
4. Installs resulting files to `site-packages/`

**For bomtrace interception:** This is identical to the C/C++ pipeline.
We can wrap `pip install` with `strace` or `bomtrace2` to capture the
compilation:

```bash
strace -f --seccomp-bpf -e trace=openat,execve -o /tmp/pip_strace.log \
    pip install --no-binary :all: -r requirements.txt
```

However, most production deployments use **pre-built wheels**, so sdist
compilation is the exception, not the rule.

### Challenge 4: Virtual Environments and Isolation

Python projects use virtual environments (`venv`, `conda`, `poetry`) that
isolate dependencies. The SBOM must target a **specific environment**:

```
.venv/lib/python3.12/site-packages/  ← THIS is the SBOM scope
```

This is analogous to:
- Java: the JAR's classpath
- Rust: `target/release/` output
- Go: the final linked binary
- C/C++: the linked binary + dynamic libs

---

<a id="7-architecture"></a>

## 7. Detailed Proposals for bomsh Python Support

The following proposals are for new scripts/features in the **upstream
bomsh** repository (github.com/omnibor/bomsh), modeled after the existing
patterns in `bomsh_spdx_deb.py`, `bomsh_create_bom_java.py`, and
`bomsh_sbom.py`.

---

### Proposal A: `bomsh_spdx_pypi.py` — SPDX from pip metadata

**What it is:** A new script analogous to `bomsh_spdx_deb.py` that
generates SPDX 2.3 documents for Python packages installed via pip.

**How `bomsh_spdx_deb.py` works today (the template):**

1. Queries package metadata via `dpkg -f <pkg>.deb` → name, version, arch
2. Unpacks the `.deb` to a temp dir
3. Hashes every file in the package (SHA1, SHA256) via `spdx_tools`
4. Computes `PackageVerificationCode` from file hashes
5. Creates SPDX Package with PURLs (`pkg:deb/...`) and CPEs
6. Inserts OmniBOR ExternalRef (`gitoid:blob:sha1:<bom_id>`)
7. Creates DESCRIBES, CONTAINS (files), BUILD_DEPENDENCY_OF, DEPENDS_ON relationships
8. Validates via `spdx_tools.spdx.validation`
9. Writes multiple formats (tag-value, JSON, RDF, XML, YAML)

**How `bomsh_spdx_pypi.py` would work (the Python equivalent):**

```
bomsh_spdx_pypi.py
  -p <site-packages-path>    # e.g., .venv/lib/python3.12/site-packages
  -b <bom_dir>               # OmniBOR dir (from bomsh_pylib.py + bomsh_create_bom.py)
  -o <output_dir>            # where to write SPDX documents
  --target <pkg_name>        # optional: only generate SPDX for this package + deps
  --hashtype sha256          # hash algorithm
  --spdx_format spdx.json    # output format(s)
```

**Step-by-step behavior:**

| Step | Action | Data Source | bomsh_spdx_deb.py Equivalent |
|------|--------|-------------|------------------------------|
| 1 | Discover all installed packages | Scan `site-packages/*/dist-info/` directories | `rpm_path.iterdir()` |
| 2 | Parse package metadata | Read each `METADATA` file → name, version, author, license, requires-dist, home-page | `dpkg -f` query |
| 3 | Parse file manifest | Read each `RECORD` file → CSV of (path, sha256, size) | `find_all_regular_files()` on unpacked deb |
| 4 | Hash files | SHA256 already in RECORD; compute SHA1 via `git hash-object` for OmniBOR | `calculate_file_checksum()` |
| 5 | Build SPDX Package | Map METADATA → SPDX fields (see mapping table below) | `spdx_add_package()` |
| 6 | Build SPDX Files | One SPDX File entry per RECORD row | `analyze_files()` |
| 7 | Compute verification code | From file SHA1 hashes | `calculate_package_verification_code()` |
| 8 | Build PURLs | `pkg:pypi/<name>@<version>` | `build_pkg_purl()` |
| 9 | Build dependency graph | Parse `Requires-Dist` from METADATA → DEPENDS_ON relationships | `spdx_add_src_pkg_dependency()` |
| 10 | Detect C extensions | Scan RECORD for `.so`/`.pyd` → CONTAINS relationship | *(new, no deb equivalent)* |
| 11 | Insert OmniBOR ExternalRef | Map file gitoid → bom_id from `g_omnibor_doc_mappings` | `insert_omnibor_into_sbom_doc()` |
| 12 | Validate + write | `spdx_tools` validation + multi-format output | `validate_full_spdx_document()` + `write_file()` |

**METADATA → SPDX field mapping:**

| METADATA Field | SPDX Field | Notes |
|----------------|-----------|-------|
| `Name` | `Package.name` | Mandatory |
| `Version` | `Package.version` | Mandatory |
| `Author` / `Author-email` | `Package.supplier` (Actor) | `ActorType.PERSON` or `ActorType.ORGANIZATION` |
| `License-Expression` | `Package.license_concluded` | PEP 639 gives native SPDX expressions; older packages use `License` field (free-text, needs heuristic mapping) |
| `Summary` | `Package.description` | Optional |
| `Home-page` / `Project-URL` | `Package.homepage` | Optional |
| `Requires-Dist` | Relationships (DEPENDS_ON) | Parse PEP 508 strings; filter by current environment markers |
| `Requires-Python` | *(no direct mapping)* | Could add as comment or ExternalRef |
| `Classifier` | *(no direct mapping)* | Could derive `PackagePurpose` from classifiers |

**RECORD → SPDX File mapping:**

| RECORD Column | SPDX File Field | Notes |
|---------------|----------------|-------|
| `path` | `File.name` | Relative to site-packages |
| `sha256=<hash>` | `File.checksums` (SHA256) | Already provided; also compute SHA1 via `git hash-object` |
| `size` | *(no direct mapping)* | Could store as comment |
| File extension | `File.file_types` | `.py` → SOURCE, `.so`/`.pyd` → BINARY, `.txt`/`.md` → TEXT |

**Dependencies (key difference from deb):**

Debian uses `dpkg` dependency metadata (binary package deps). Python uses
`Requires-Dist` which is richer:

```
Requires-Dist: urllib3 <3,>=1.21.1
Requires-Dist: certifi >=2017.4.17
Requires-Dist: PySocks !=1.5.7,>=1.5.6 ; extra == "socks"
```

The script must:
1. Parse each `Requires-Dist` line (PEP 508 format)
2. Evaluate environment markers (`sys_platform`, `extra`, etc.) against
   the current platform to determine which deps are active
3. Create `DEPENDS_ON` relationships only for active deps
4. Distinguish direct vs. transitive deps (direct = in the target
   package's METADATA; transitive = deps of deps)

**Uses `spdx_tools` library** — same as `bomsh_spdx_deb.py`:

```python
from spdx_tools.spdx.model import (
    Actor, ActorType, Checksum, ChecksumAlgorithm,
    CreationInfo, Document, ExternalPackageRef,
    ExternalPackageRefCategory, File, FileType,
    Package, PackagePurpose, Relationship, RelationshipType,
    SpdxNoAssertion, PackageVerificationCode,
)
from spdx_tools.spdx.validation.document_validator import (
    validate_full_spdx_document,
)
from spdx_tools.spdx.writer.write_anything import write_file
from packageurl import PackageURL
```

---

### Proposal B: `bomsh_create_bom_python.py` — OmniBOR ADG for pip installs

**What it is:** A new script analogous to `bomsh_create_bom_java.py` that
creates OmniBOR artifact dependency graphs (ADGs) for Python packages,
mapping installed files back to their pip source packages.

**How `bomsh_create_bom_java.py` works today (the template):**

1. Scans workspace for all `.java` and `.class` files
2. For each `.jar` file: unbundles it, extracts `.class` files
3. For each `.class`: uses `javap` SourceFile attribute (or strace
   logfile) to find the originating `.java` file
4. Creates ADFs: `outfile: <hash-of-.class>` → `infile: <hash-of-.java>`
5. Rolls up: `outfile: <hash-of-.jar>` → `infile: [<hash-of-.class>...]`
6. Stores treedb + bomdb as JSON files

**How `bomsh_create_bom_python.py` would work:**

```
bomsh_create_bom_python.py
  -p <site-packages-path>    # e.g., .venv/lib/python3.12/site-packages
  -b <bom_dir>               # output OmniBOR dir
  -s <strace_logfile>        # optional: strace log from pip install
  --hashtype sha256
```

**Step-by-step behavior:**

| Step | Action | Java Equivalent |
|------|--------|-----------------|
| 1 | Scan `site-packages/*/dist-info/` for installed packages | Scan workspace for `.jar` files |
| 2 | For each package, read `RECORD` → list of installed files | Unbundle `.jar` → list of `.class` files |
| 3 | Hash each installed file (git blob format) | `get_git_file_hash(classfile)` |
| 4 | Create ADF: `outfile: <hash-of-package>` → `infile: [<hash-of-each-file>]` | `process_jar_file()` records |
| 5 | If strace logfile: parse `pip download` / `pip install` openat events to trace which `.whl` / `.tar.gz` was downloaded for each package | `read_strace_logfile()` for `.java`→`.class` mapping |
| 6 | Create treedb + bomdb JSON files | Same |

**Key difference from Java:** Java has a `.class`→`.java` mapping problem
(solved by `javap` SourceFile attribute). Python doesn't need this because
the `RECORD` file already maps every installed file to its package. The
hard problem for Python is instead: **mapping installed files back to their
upstream source** (PyPI tarball or git commit).

**The strace integration for Python:** When `pip install` is wrapped with
strace, we can capture:

```bash
strace -f -e trace=openat pip install -r requirements.txt
```

This reveals:
- Which `.whl` / `.tar.gz` files were downloaded (from `~/.cache/pip/`)
- Which files were extracted/compiled
- Network operations (PyPI URLs accessed)

This strace data lets us build a complete provenance chain:
```
PyPI wheel → extracted .py/.so files → installed in site-packages
```

---

### Proposal C: Enhance `bomsh_pylib.py` — venv support + package awareness

**What it is:** Targeted improvements to the existing `bomsh_pylib.py`
to make it useful for SPDX generation, not just CVE search.

**Enhancement C.1: venv support**

Currently `bomsh_pylib.py` uses the system Python's `sys.path` for import
resolution (comment in source: "will investigate venv later"). Add:

```
bomsh_pylib.py -d /path/to/project --venv /path/to/.venv
```

Implementation: prepend the venv's `site-packages` to `sys.path` before
running `importlib.import_module()`. This ensures imports resolve against
the target environment, not the system Python.

**Enhancement C.2: package-level grouping**

Currently `bomsh_pylib.py` produces file-level ADFs (`.py` → imported
`.py`). Add an option to **group files by their pip package**:

```
bomsh_pylib.py -d /path/to/project --venv /path/to/.venv --pkg-group
```

For each `.py` file, determine which pip package it belongs to by checking
which `dist-info/RECORD` contains it. Then produce a summary:

```json
{
  "myapp/main.py": {
    "package": "myapp",
    "imports_packages": ["requests", "flask", "sqlalchemy"],
    "imports_files": ["requests/api.py", "flask/app.py", ...]
  }
}
```

This bridges the gap between bomsh_pylib.py's file-level graph and the
package-level graph needed for SPDX DEPENDS_ON relationships.

**Enhancement C.3: C extension module detection**

When `bomsh_pylib.py` encounters an import that resolves to a `.so` or
`.pyd` file (e.g., `import _ssl` → `/usr/lib/python3.12/lib-dynload/_ssl.cpython-312-x86_64-linux-gnu.so`),
record it as a binary dependency rather than ignoring it.

Currently `bomsh_pylib.py` skips modules without `__file__` attribute
(builtins) but doesn't distinguish `.so` from `.py`. Enhance to:

1. Check if `pylib.__file__` ends with `.so` / `.pyd`
2. If so, hash the `.so` file and record it as a binary dep
3. Optionally run `ldd` on the `.so` to discover system library deps
4. Output both in the raw_logfile and JSON

---

### Proposal D: `bomsh_hook2.py` Python awareness (build-from-source)

**What it is:** Add Python build tool recognition to `bomsh_hook2.py` so
that `bomtrace2` can intercept `pip install --no-binary` compilations.

**Current state:** `bomsh_hook2.py` recognizes these program categories:

```python
g_cc_compilers = ["/usr/bin/gcc", "/usr/bin/clang", ...]
g_cc_linkers = ["/usr/bin/ld", "/usr/bin/ld.bfd", ...]
# + Rust: rustc
# + Go: compile, link (Go toolchain)
```

When `pip install --no-binary :all:` compiles a C extension (e.g., numpy),
it invokes `gcc` / `g++` under the hood. `bomtrace2` already intercepts
these — but `bomsh_hook2.py` doesn't know they belong to a pip package.

**Proposed enhancement:**

Add Python build tool recognition:

```python
g_python_build_progs = [
    "pip", "pip3",
    "python3 -m pip",
    "python3 setup.py",
    "python3 -m build",
    "maturin",  # Rust-Python build tool
]
```

When `bomsh_hook2.py` detects a `pip install` process tree:
1. Record the pip command as the "umbrella" process
2. All child `gcc`/`g++`/`rustc` invocations are tagged as belonging
   to this pip install
3. After completion, map the compiled `.so` back to the pip package
   name/version (from the wheel filename or sdist metadata)

This would produce ADFs that look like:

```
outfile: <hash-of-numpy/_core/_multiarray_umath.so> path: site-packages/numpy/...
infile: <hash-of-numpy/core/src/multiarray/array.c> path: /tmp/pip-build-.../numpy/...
infile: <hash-of-numpy/core/src/multiarray/buffer.c> path: /tmp/pip-build-.../numpy/...
build_cmd: gcc -shared -o ... (child of pip install numpy)
==== End of raw info for this process
```

**Complexity:** Medium-high. Requires process-tree tracking in
`bomsh_hook2.py` (the `pstree` functionality already exists in
`bomsh_pstree.py` and could be leveraged).

**When needed:** Only for organizations that build from source instead
of using pre-built wheels. Most Python deployments use wheels.

---

### Proposal E: Integration of Proposals A-D into a complete pipeline

**End-to-end workflow for Python SPDX generation in bomsh:**

```
┌──────────────────────────────────────────────────────────────────┐
│  Step 1: Install Python project                                  │
│                                                                  │
│  Option A (wheels, most common):                                 │
│    pip install -r requirements.txt                               │
│                                                                  │
│  Option B (source, with tracing):                                │
│    bomtrace2 pip install --no-binary :all: -r requirements.txt   │
│                                                                  │
│  Option C (wheels, with strace for download provenance):         │
│    strace -f -e openat pip install -r requirements.txt           │
├──────────────────────────────────────────────────────────────────┤
│  Step 2: Generate OmniBOR ADG                                    │
│                                                                  │
│  # File-level import graph (existing bomsh_pylib.py)             │
│  bomsh_pylib.py -d /path/to/project --venv .venv --hashtype     │
│      sha256 --pkg-group                                          │
│                                                                  │
│  # Package-level ADG (new bomsh_create_bom_python.py)            │
│  bomsh_create_bom_python.py -p .venv/lib/.../site-packages       │
│      -b omnibor_dir --hashtype sha256                            │
│                                                                  │
│  # If bomtrace2 was used (Option B):                             │
│  bomsh_create_bom.py -r /tmp/bomsh_hook_raw_logfile.sha256       │
│      -b omnibor_dir --hashtype sha256                            │
├──────────────────────────────────────────────────────────────────┤
│  Step 3: Generate SPDX SBOM (new bomsh_spdx_pypi.py)            │
│                                                                  │
│  bomsh_spdx_pypi.py                                              │
│      -p .venv/lib/python3.12/site-packages                       │
│      -b omnibor_dir                                              │
│      -o /output/spdx/                                            │
│      --target myproject                                          │
│      --spdx_format spdx.json                                    │
├──────────────────────────────────────────────────────────────────┤
│  Step 4: CVE search (existing bomsh_search_cve.py)               │
│                                                                  │
│  bomsh_search_cve.py -b omnibor_dir -f .venv/bin/myapp           │
│      --hashtype sha256                                           │
└──────────────────────────────────────────────────────────────────┘
```

**Comparison to existing language pipelines:**

| Step | C/C++ | Java | **Python (proposed)** |
|------|-------|------|-----------------------|
| Build/install | `bomtrace3 make` | `strace mvn package` | `pip install` (+ optional strace) |
| Create BOM | `bomsh_create_bom.py` (from raw_logfile) | `bomsh_create_bom_java.py` (workspace scan) | `bomsh_create_bom_python.py` (dist-info scan) + `bomsh_pylib.py` (import graph) |
| Generate SPDX | `bomsh_sbom.py` (augments Syft) | *(not yet in bomsh)* | `bomsh_spdx_pypi.py` (from pip metadata) |
| CVE search | `bomsh_search_cve.py` | `bomsh_search_cve.py` | `bomsh_search_cve.py` (already works) |

---

<a id="6-wheels-c-extensions"></a>

## 6. Wheels and C Extensions: Metadata Extraction

### Pure Python Packages

**Fully handled by `dist-info/METADATA` + `dist-info/RECORD`.** All data
needed for SPDX is already present after `pip install`:

| SPDX Field | Source | Example (requests 2.31.0) |
|------------|--------|---------------------------|
| `Package.name` | METADATA `Name` | `requests` |
| `Package.version` | METADATA `Version` | `2.31.0` |
| `Package.supplier` | METADATA `Author` / `Author-email` | `Kenneth Reitz (me@kennethreitz.org)` |
| `Package.license_concluded` | METADATA `License-Expression` | `Apache-2.0` |
| `Package.download_location` | METADATA `Home-page` / `Project-URL` | `https://requests.readthedocs.io` |
| `ExternalPackageRef` (PURL) | Constructed from name + version | `pkg:pypi/requests@2.31.0` |
| `Package.primary_package_purpose` | `LIBRARY` (default for pip packages) | — |
| `Package.files_analyzed` | `True` (RECORD provides hashes) | — |
| `Package.verification_code` | Computed from RECORD SHA256 hashes | — |
| `File.checksums` | RECORD `sha256=<hash>` per file | — |

### C Extension Packages (Binary Wheels)

Binary wheels for packages like `cryptography`, `numpy`, and `pillow`
bundle compiled `.so` shared libraries:

```
cryptography-42.0.0-cp312-abi3-manylinux_2_28_x86_64.whl
├── cryptography/
│   ├── hazmat/bindings/_rust.abi3.so    # Rust-compiled, ~15MB
│   └── ...
├── cryptography-42.0.0.dist-info/
│   ├── METADATA    # Name, Version, Author, License
│   ├── RECORD      # SHA256 of _rust.abi3.so included
│   └── WHEEL       # Platform tag: manylinux_2_28_x86_64
```

**How `bomsh_spdx_pypi.py` would handle this:**

1. Scan RECORD for entries matching `*.so`, `*.pyd`, `*.dylib`
2. Create a child SPDX Package for each `.so` with:
   - `name`: `<parent_pkg>.<module_name>` (e.g., `cryptography._rust`)
   - `version`: inherited from parent METADATA
   - `primary_package_purpose`: `LIBRARY`
   - `checksums`: SHA256 from RECORD
   - `file_types`: `BINARY`
3. Create `CONTAINS` relationship from parent package to child `.so`
4. Optionally run `ldd` on the `.so` to discover dynamic deps →
   `DYNAMIC_LINK` relationships to system libraries

### How to Determine Version/Author/License for C Extensions

| Data Point | Source | Reliability |
|------------|--------|-------------|
| **Version** | Parent package METADATA `Version` | ✅ Always matches — the `.so` is built and published as part of the same package |
| **Author** | Parent package METADATA `Author` / `Author-email` | ✅ Same publisher |
| **License** | Parent package METADATA `License-Expression` | ✅ Covers the entire distribution including native code |
| **Bundled native lib versions** (e.g., OpenSSL in cryptography) | Not in METADATA. Options: (a) `readelf --string-dump` on the `.so` may reveal version strings, (b) `auditwheel show <whl>` lists bundled external shared libs, (c) Query PyPI JSON API for build metadata, (d) Parse the project's `pyproject.toml` / build config for pinned native dep versions | ⚠️ Project-specific; best-effort |

### PyPI JSON API for Additional Metadata

When generating SBOMs for packages not yet installed, or to get download
URLs/hashes without local install:

```
GET https://pypi.org/pypi/cryptography/42.0.0/json
```

Returns `info.author`, `info.license`, `urls[]` (download URLs + SHA256),
`info.requires_dist`, `info.project_urls`. This is equivalent to querying
Maven Central for POM metadata in the Java pipeline.

---

<a id="8-implementation"></a>

## 8. Implementation Priorities

### Priority 1 (High): `bomsh_spdx_pypi.py`

This is the **highest-value, lowest-complexity** addition because:
- All metadata is already available after `pip install` (zero tracing needed)
- The `spdx_tools` library and patterns from `bomsh_spdx_deb.py` provide
  a proven template
- Directly produces SPDX 2.3 documents comparable to `bomsh_spdx_deb.py`

**Estimated effort:** ~500 lines of Python (comparable to `bomsh_spdx_deb.py`)

**Dependencies:** `spdx_tools`, `packageurl-python` (same as deb script)

### Priority 2 (High): `bomsh_pylib.py` venv + package grouping

Low-risk enhancement to an existing script. Unlocks:
- Analysis of project-specific venvs (not just system Python)
- Package-level dependency awareness (file → package mapping)

**Estimated effort:** ~100 lines added to existing script

### Priority 3 (Medium): `bomsh_create_bom_python.py`

Needed for full OmniBOR ADG/treedb integration, but not required for basic
SPDX generation (which can work from METADATA/RECORD alone).

**Estimated effort:** ~300 lines (simpler than Java because RECORD
eliminates the `.class`→`.java` matching problem)

### Priority 4 (Low): `bomsh_hook2.py` Python awareness

Only needed for build-from-source scenarios. Most Python deployments use
pre-built wheels, so this has narrow applicability.

**Estimated effort:** ~200 lines added to existing script

---

<a id="9-target-repos"></a>

## 9. Target Repos for Validation

### Recommended Python Projects

| Repo | Why | Deps | C Extensions? |
|------|-----|------|--------------|
| **black** | Code formatter, few deps, pure Python | click, pathspec, platformdirs | No |
| **flask** | Web framework, moderate deps | werkzeug, jinja2, itsdangerous, click | No |
| **ansible** | Large, 200+ deps, mix of pure + C ext | requests, jinja2, cryptography, pyyaml | Yes (cryptography, pyyaml) |
| **httpie** | CLI tool, moderate deps | requests, pygments, rich | Minimal |
| **numpy** | Scientific computing | None (self-contained) | **Heavy** (bundled OpenBLAS `.so`) |
| **cryptography** | Security-critical | cffi | **Heavy** (Rust `.so`, OpenSSL bundled) |
| **pillow** | Image processing | None | **Heavy** (libjpeg, libpng, zlib bundled) |

### Validation Strategy

**Phase 1:** Start with **black** — pure Python, ~5 deps, zero C
extensions. Validates the core METADATA/RECORD → SPDX pipeline.

**Phase 2:** **flask** or **httpie** — moderate dep count, validates
transitive dependency graph and DEPENDS_ON relationships.

**Phase 3:** **ansible** — 200+ deps, includes `cryptography` (Rust
extension) and `pyyaml` (C extension). Validates C extension detection
and CONTAINS relationships.

**Phase 4:** **numpy** — heavy C extensions with bundled `.so` (OpenBLAS).
Validates ELF analysis and bundled native library detection.

### Comparison Baseline

For each target, generate SBOMs with both:
1. `bomsh_spdx_pypi.py` (proposed)
2. Syft / CycloneDX Python (existing third-party tools)

Compare package counts, relationship counts, and metadata completeness
to validate that the bomsh approach matches or exceeds existing tools.

---

## References

1. **bomsh_spdx_deb.py:** https://github.com/omnibor/bomsh/blob/master/scripts/bomsh_spdx_deb.py (template for SPDX generation)
2. **bomsh_create_bom_java.py:** https://github.com/omnibor/bomsh/blob/master/scripts/bomsh_create_bom_java.py (template for ADG creation)
3. **bomsh_pylib.py:** https://github.com/omnibor/bomsh/blob/master/scripts/bomsh_pylib.py (existing Python import analysis)
4. **bomsh_sbom.py:** https://github.com/omnibor/bomsh/blob/master/scripts/bomsh_sbom.py (OmniBOR ExternalRef insertion into Syft SBOMs)
5. **Python Core Metadata:** https://packaging.python.org/specifications/core-metadata/
6. **PEP 427 — Wheel Format:** https://peps.python.org/pep-0427/
7. **PEP 639 — License Expression:** https://peps.python.org/pep-0639/
8. **Recording Installed Packages:** https://packaging.python.org/specifications/recording-installed-packages/
9. **`importlib.metadata` API:** https://docs.python.org/3/library/importlib.metadata.html
10. **auditwheel:** https://github.com/pypa/auditwheel (bundled `.so` detection in wheels)
11. **CycloneDX Python:** https://github.com/CycloneDX/cyclonedx-python (comparison baseline)
12. **sbom4python:** https://pypi.org/project/sbom4python/ (comparison baseline)
13. **pip-sbom (Seth Larson):** https://github.com/sethmlarson/pip-sbom (PEP 710 SBOM generation)
