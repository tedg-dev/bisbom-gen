# Python OmniBOR Support: Detailed Gap Analysis and Design Proposal

> **Purpose:** Determine what changes are needed in bomsh (upstream) and
> omnibor-analysis (downstream) to produce accurate, build-time SPDX SBOMs
> for Python projects — comparable in quality to the C/C++ and Java pipelines.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current State of Python Support in bomsh](#2-current-state-of-python-support-in-bomsh)
3. [What "Build-Time" Means for Each Language](#3-what-build-time-means-for-each-language)
4. [Reference: C/C++ Pipeline (Gold Standard)](#4-reference-cc-pipeline-gold-standard)
5. [Reference: Java Pipeline (Closest Analogue)](#5-reference-java-pipeline-closest-analogue)
6. [Python Build Landscape: Nuances That Affect SBOM Generation](#6-python-build-landscape-nuances-that-affect-sbom-generation)
7. [Gap Analysis: What bomsh_pylib.py Cannot Do](#7-gap-analysis-what-bomsh_pylibpy-cannot-do)
8. [Proposed Architecture: Python OmniBOR Pipeline](#8-proposed-architecture-python-omnibor-pipeline)
9. [Upstream bomsh Changes Required](#9-upstream-bomsh-changes-required)
10. [omnibor-analysis Changes Required](#10-omnibor-analysis-changes-required)
11. [Python Project Categories and Strategies](#11-python-project-categories-and-strategies)
12. [SPDX Relationship Mapping for Python](#12-spdx-relationship-mapping-for-python)
13. [Implementation Priority and Phasing](#13-implementation-priority-and-phasing)
14. [Open Questions](#14-open-questions)

---

## 1. Executive Summary

**Current state:** bomsh has a single Python-related script (`bomsh_pylib.py`)
that performs **static import analysis** — it uses Python's `ast` module to
parse `import` statements and `importlib` to resolve module paths. It produces
a raw_logfile compatible with `bomsh_create_bom.py` and a JSON dependency tree.

**What's missing:** `bomsh_pylib.py` is a **runtime dependency analyzer**, not a
**build-time interceptor**. It answers "what does this script import at rest?"
not "what went into building/installing this package?" The gap between these
two questions is enormous for Python:

<table>
<tr>
  <th style="min-width:220px">Capability</th>
  <th style="min-width:160px">C/C++</th>
  <th style="min-width:160px">Java</th>
  <th style="min-width:140px">Python (today)</th>
  <th style="min-width:200px">Python (needed)</th>
</tr>
<tr>
  <td><strong>Build-time file interception</strong></td>
  <td>bomtrace3 (ptrace)</td>
  <td>strace (openat)</td>
  <td>None</td>
  <td>strace or bomtrace2</td>
</tr>
<tr>
  <td><strong>Dependency graph from build tool</strong></td>
  <td>gcc .d files + ld inputs</td>
  <td><code>mvn dependency:tree</code></td>
  <td>None</td>
  <td><code>pip</code> metadata + <code>importlib.metadata</code></td>
</tr>
<tr>
  <td><strong>Binary artifact → source mapping</strong></td>
  <td>.o → .c via ADG</td>
  <td>.class → .java via javap</td>
  <td>None</td>
  <td>dist-info RECORD file</td>
</tr>
<tr>
  <td><strong>Vendored/compiled extension detection</strong></td>
  <td>bomtrace3 intercepts gcc</td>
  <td>javap SourceFile attr</td>
  <td>None</td>
  <td>strace intercepts gcc/g++ during <code>pip install</code></td>
</tr>
<tr>
  <td><strong>Version detection</strong></td>
  <td>12 strategies</td>
  <td>pom.xml <code>&lt;version&gt;</code></td>
  <td>None</td>
  <td>METADATA <code>Version:</code> field</td>
</tr>
<tr>
  <td><strong>SPDX generation</strong></td>
  <td><code>SpdxEmitter</code></td>
  <td><code>JavaSpdxGenerator</code></td>
  <td>None</td>
  <td>New <code>PythonSpdxGenerator</code></td>
</tr>
<tr>
  <td><strong>OmniBOR ADG</strong></td>
  <td><code>bomsh_create_bom.py</code></td>
  <td><code>bomsh_create_bom_java.py</code></td>
  <td><code>bomsh_pylib.py</code> (partial)</td>
  <td>Enhanced + new script</td>
</tr>
</table>

**Bottom line:** Python support requires work at **three levels:**

1. **Upstream bomsh** — enhance `bomsh_pylib.py` + create `bomsh_create_bom_python.py`
2. **omnibor-analysis pipeline** — add `run_python_pipeline()` + `PythonSpdxGenerator`
3. **Docker container** — add Python build toolchain support

---

## 2. Current State of Python Support in bomsh

### 2.1 What `bomsh_pylib.py` Does

`bomsh_pylib.py` (September 2023, ~400 lines) performs **static AST-based
import analysis**:

1. **Parses** Python source files using `ast.parse()` to find `Import` and
   `ImportFrom` nodes
2. **Resolves** module names to file paths using `importlib.import_module()`
3. **Recursively** follows imports to build a complete dependency tree
4. **Handles** relative imports by converting to absolute module paths
5. **Handles** try/except import patterns (conditional imports)
6. **Hashes** all resolved `.py` files using gitoid format (SHA-1/SHA-256)
7. **Writes** a raw_logfile with `outfile:`/`infile:` format compatible with
   `bomsh_create_bom.py`
8. **Outputs** JSON dependency tree to `bomsh_pylib_jsonfile-result.json`

### 2.2 What `bomsh_pylib.py` Does NOT Do

<table>
<tr>
  <th style="min-width:240px">Missing Capability</th>
  <th>Why It Matters</th>
</tr>
<tr>
  <td><strong>No venv/virtualenv awareness</strong></td>
  <td>Code comment says "will investigate venv later." Cannot analyze installed packages in isolated environments.</td>
</tr>
<tr>
  <td><strong>No <code>pip</code> metadata parsing</strong></td>
  <td>Does not read <code>METADATA</code>, <code>RECORD</code>, or <code>top_level.txt</code> from <code>dist-info/</code> directories. Cannot determine package names, versions, or license info.</td>
</tr>
<tr>
  <td><strong>No C extension detection</strong></td>
  <td>Cannot identify <code>.so</code>/<code>.pyd</code> files compiled from C/C++ source during <code>pip install</code>. These are invisible to AST analysis.</td>
</tr>
<tr>
  <td><strong>No <code>requirements.txt</code> / <code>pyproject.toml</code> parsing</strong></td>
  <td>Cannot distinguish direct vs. transitive dependencies.</td>
</tr>
<tr>
  <td><strong>No wheel/sdist awareness</strong></td>
  <td>Does not understand Python packaging formats at all.</td>
</tr>
<tr>
  <td><strong>No build-time interception</strong></td>
  <td>Only analyzes source files statically — does not intercept <code>pip install</code>, <code>python setup.py build</code>, or <code>setuptools</code>.</td>
</tr>
<tr>
  <td><strong>No SPDX generation</strong></td>
  <td>Produces only a raw_logfile and JSON tree — no SPDX 2.3 document.</td>
</tr>
<tr>
  <td><strong>No package URL (PURL)</strong></td>
  <td>Does not generate <code>pkg:pypi/</code> PURLs for identified packages.</td>
</tr>
<tr>
  <td><strong>Requires modules to be importable</strong></td>
  <td>Uses <code>importlib.import_module()</code> which <strong>actually imports</strong> the module. This means: (a) all dependencies must be installed, (b) side effects of import execute, (c) modules with C extensions that fail to load are missed.</td>
</tr>
</table>

### 2.3 bomsh Scripts Inventory (Python-relevant)

<table>
<tr>
  <th style="min-width:220px">Script</th>
  <th style="min-width:240px">Role</th>
  <th>Python Support</th>
</tr>
<tr>
  <td><code>bomsh_pylib.py</code></td>
  <td>Runtime dependency tree for <code>.py</code> files</td>
  <td>Partial — import analysis only</td>
</tr>
<tr>
  <td><code>bomsh_create_bom.py</code></td>
  <td>Raw logfile → ADG + treedb</td>
  <td>Can consume <code>bomsh_pylib.py</code> output</td>
</tr>
<tr>
  <td><code>bomsh_create_bom_java.py</code></td>
  <td>Java-specific ADG from strace + javap</td>
  <td>Template for a Python equivalent</td>
</tr>
<tr>
  <td><code>bomsh_hook2.py</code></td>
  <td>bomtrace2 hook (Go/Rust)</td>
  <td>No Python-specific handlers</td>
</tr>
<tr>
  <td><code>bomsh_sbom.py</code></td>
  <td>ADG → basic OmniBOR SPDX</td>
  <td>Generic, could work with Python ADG</td>
</tr>
<tr>
  <td><code>bomsh_spdx_deb.py</code></td>
  <td>Deb package → SPDX with OmniBOR refs</td>
  <td>Template for pip-based SPDX</td>
</tr>
<tr>
  <td><code>bomsh_search_cve.py</code></td>
  <td>CVE search against ADG</td>
  <td>Would work with Python ADG</td>
</tr>
<tr>
  <td><code>bomsh_dynlib.py</code></td>
  <td>ELF dynamic library tree</td>
  <td>Relevant for Python C extensions</td>
</tr>
</table>

---

## 3. What "Build-Time" Means for Each Language

The concept of "build time" differs fundamentally across languages:

### C/C++: Compilation is the Build

```text
source.c → [gcc] → source.o → [ld] → binary
```

- Every input/output relationship is a **compiler/linker invocation**
- bomtrace3 intercepts `execve()` for gcc, ld, ar
- **100% of runtime code** passes through the build pipeline
- Build-time == the complete picture

### Java: Compilation + Packaging

```text
Source.java → [javac] → Source.class → [jar] → app.jar
                                          ↑
                        Maven deps -------|  (copied at package time)
```

- javac compiles `.java` → `.class` (strace traces file opens)
- Maven downloads pre-compiled JARs and links them at package time
- `bomsh_create_bom_java.py` uses `javap -v` to map `.class` → `.java`
- `mvn dependency:tree` provides the full dependency graph
- Build-time captures both compiled code AND declared dependencies

### Python: Installation IS the Build

```text
# Pure Python package:
source.py → [pip install] → site-packages/pkg/source.py (COPY)
                          → site-packages/pkg.dist-info/METADATA
                          → site-packages/pkg.dist-info/RECORD

# Package with C extensions:
source.c + setup.py → [pip install] → [gcc] → ext.cpython-311-x86_64-linux-gnu.so
                                     → site-packages/pkg/ext.so
                                     → site-packages/pkg.dist-info/METADATA
```

**This is the fundamental insight:** For Python, `pip install` IS the build
command. It:

1. **Downloads** wheels or sdists from PyPI
2. **Compiles** C/C++ extensions (if sdist with native code)
3. **Copies** `.py` files into `site-packages/`
4. **Writes** `dist-info/METADATA` (package name, version, license, deps)
5. **Writes** `dist-info/RECORD` (SHA-256 hash of every installed file)

**The `RECORD` file is Python's equivalent of a raw_logfile.** It already
contains the gitoid-compatible hash of every file in the package:

```text
../requests/__init__.py,sha256=abc123def456...,4567
../requests/api.py,sha256=789ghi012jkl...,2345
../requests/models.py,sha256=mno345pqr678...,8901
```

---

## 4. Reference: C/C++ Pipeline (Gold Standard)

The C/C++ pipeline is the most mature and provides the baseline for comparison:

```text
┌─────────────────────────────────────────────────────────┐
│ C/C++ Pipeline (bomtrace3)                              │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ 1. Clone repo          git clone --branch <tag>         │
│ 2. Syft SBOM           syft scan (manifest-based)       │
│ 3. Validate deps       apt-get check (system libs)      │
│ 4. Instrumented build  bomtrace3 make -j$(nproc)        │
│    ├─ ptrace intercepts every execve(gcc/ld/ar)         │
│    ├─ Hashes every input/output file (gitoid SHA-256)   │
│    └─ Writes raw_logfile with outfile:/infile: records  │
│ 5a. bomsh_create_bom.py                                 │
│    ├─ Parses raw_logfile → ADG + treedb                 │
│    └─ treedb maps gitoid → file path                    │
│ 5b. AdgParser classifies artifacts                      │
│    ├─ system_lib, system_header, project_source          │
│    ├─ build_intermediate, crt_object                     │
│    └─ go_stdlib (for Go builds)                         │
│ 5c. VendoredVersionDetector (12 strategies)             │
│ 5d. DynamicLibCollector (ldd analysis)                  │
│ 5e. SpdxEmitter → SPDX 2.3 JSON                        │
│    ├─ Analyzed: STATIC_LINK + CONTAINS only             │
│    └─ Build: + DYNAMIC_LINK + BUILD_TOOL_OF             │
│ 6. SpdxValidator (JSON schema + semantic checks)        │
│ 7. BinaryCollector (copy binaries to output/)           │
│ 8. HTML visualization (D3.js force graph)               │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### What makes C/C++ strong:

- **Every file relationship is captured** — gcc reads source.c + headers →
  writes object.o. bomtrace3 records all of them
- **Vendored libraries are detected** — source files under `deps/` or
  `third_party/` are grouped into SPDX packages with versions
- **Dynamic libraries are identified** — ldd reveals runtime deps
- **Build tools are recorded** — gcc, ld appear as BUILD_TOOL_OF
- **12 version detection strategies** — configure.ac, CMakeLists.txt,
  `#define VERSION`, Makefile, git tags, etc.

---

## 5. Reference: Java Pipeline (Closest Analogue)

Java is the **closest analogue to Python** because:

1. Both have a package manager (Maven/pip) that downloads pre-compiled deps
2. Both have a compilation step that may or may not produce native code
3. Both need to map the final artifact back to source files

```text
┌─────────────────────────────────────────────────────────┐
│ Java Pipeline (strace + bomsh_create_bom_java.py)       │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ 1. Clone repo                                           │
│ 2. Syft SBOM                                            │
│ 3. Instrumented build                                   │
│    strace -f -e trace=openat mvn package -DskipTests    │
│    ├─ strace captures every file opened by javac        │
│    └─ Records: which .java files were read              │
│ 4. bomsh_create_bom_java.py                             │
│    ├─ Scans workspace for .java, .class, .jar files     │
│    ├─ Uses `javap -v` to read SourceFile attribute      │
│    │   from each .class → maps .class → .java           │
│    ├─ Unpacks JARs, hashes contents (gitoid)            │
│    └─ Produces treedb: gitoid → file path mapping       │
│ 5. JavaSpdxGenerator                                    │
│    ├─ Parses mvn dependency:tree for dep graph          │
│    ├─ Reads pom.xml for groupId:artifactId:version      │
│    ├─ Maps each JAR to its source files via treedb      │
│    ├─ Generates pkg:maven/ PURLs                        │
│    └─ Produces analyzed + build SPDX per JAR            │
│ 6. Validate + collect + visualize                       │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Key insight from Java pipeline:

The Java pipeline combines **two data sources**:

1. **Build-time interception** (strace openat) — which files were actually
   read/written during compilation
2. **Build tool metadata** (mvn dependency:tree, pom.xml) — declared
   dependency relationships and versions

This dual approach is **exactly what Python needs**, using:

1. **Build-time interception** (strace openat during `pip install`) — which
   files were actually installed, which C extensions were compiled
2. **Package manager metadata** (pip's `dist-info/METADATA` + `RECORD`) —
   declared dependencies, versions, licenses

---

## 6. Python Build Landscape: Nuances That Affect SBOM Generation

### 6.1 Python Package Types

<table>
<tr>
  <th style="min-width:140px">Type</th>
  <th style="min-width:80px">Extension</th>
  <th style="min-width:200px">Contents</th>
  <th style="min-width:140px">C Extensions?</th>
  <th>Build Needed?</th>
</tr>
<tr>
  <td><strong>Wheel</strong> (binary)</td>
  <td><code>.whl</code></td>
  <td>Pre-compiled <code>.py</code> + <code>.so</code></td>
  <td>Pre-built</td>
  <td>No — just unzip</td>
</tr>
<tr>
  <td><strong>Wheel</strong> (pure)</td>
  <td><code>.whl</code></td>
  <td><code>.py</code> only</td>
  <td>None</td>
  <td>No — just unzip</td>
</tr>
<tr>
  <td><strong>sdist</strong></td>
  <td><code>.tar.gz</code></td>
  <td>Source code + <code>setup.py</code>/<code>pyproject.toml</code></td>
  <td>May need compilation</td>
  <td>Yes — runs build</td>
</tr>
<tr>
  <td><strong>Editable install</strong></td>
  <td>N/A</td>
  <td>Symlinks to source</td>
  <td>May need compilation</td>
  <td><code>pip install -e .</code></td>
</tr>
</table>

### 6.2 Python Build Backends

Modern Python packages declare their build backend in `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=64", "wheel"]
build-backend = "setuptools.build_meta"
```

Common backends:

<table>
<tr>
  <th style="min-width:120px">Backend</th>
  <th style="min-width:120px">Usage</th>
  <th style="min-width:140px">Compiles C?</th>
  <th>How</th>
</tr>
<tr>
  <td><strong>setuptools</strong></td>
  <td>~70% of PyPI</td>
  <td>Yes (via <code>Extension()</code>)</td>
  <td>Invokes gcc/g++</td>
</tr>
<tr>
  <td><strong>flit</strong></td>
  <td>~10%</td>
  <td>No</td>
  <td>Pure Python only</td>
</tr>
<tr>
  <td><strong>poetry-core</strong></td>
  <td>~10%</td>
  <td>No</td>
  <td>Pure Python only</td>
</tr>
<tr>
  <td><strong>maturin</strong></td>
  <td>~5% (growing)</td>
  <td>Yes (Rust via cargo)</td>
  <td>Invokes rustc</td>
</tr>
<tr>
  <td><strong>scikit-build</strong></td>
  <td>~2%</td>
  <td>Yes (CMake)</td>
  <td>Invokes cmake + gcc</td>
</tr>
<tr>
  <td><strong>meson-python</strong></td>
  <td>~1%</td>
  <td>Yes (Meson)</td>
  <td>Invokes meson + gcc</td>
</tr>
</table>

### 6.3 Installed Package Metadata (dist-info)

After `pip install requests`, the following exists in `site-packages/`:

```text
requests/
├── __init__.py
├── api.py
├── models.py
├── ...
requests-2.31.0.dist-info/
├── METADATA          ← Package name, version, license, dependencies
├── RECORD            ← SHA-256 hash of every installed file
├── WHEEL             ← Wheel format version
├── INSTALLER         ← "pip"
├── top_level.txt     ← "requests"
└── LICENSE           ← License text
```

**`METADATA` file** (RFC 822 format):

```text
Metadata-Version: 2.1
Name: requests
Version: 2.31.0
Summary: Python HTTP for Humans.
License: Apache-2.0
Requires-Python: >=3.7
Requires-Dist: charset-normalizer <4,>=2
Requires-Dist: idna <4,>=2.5
Requires-Dist: urllib3 <3,>=1.21.1
Requires-Dist: certifi >=2017.4.17
Requires-Dist: PySocks !=1.5.7,>=1.5.6 ; extra == "socks"
```

**`RECORD` file** (CSV: path, hash, size):

```text
requests/__init__.py,sha256=ZPxPEGJEFMM-5NzXBOihJhHPxi...,4321
requests/api.py,sha256=qLYDXNaJCZnEz1BW0ZJZgK7OXJF...,6543
requests/models.py,sha256=mH5NxBPrV3lhHk1KWJx9V...,28901
```

### 6.4 C Extension Compilation During pip install

When pip installs an sdist with C extensions:

```text
pip install numpy  (from sdist)
  → downloads numpy-1.26.4.tar.gz
  → extracts to /tmp/pip-build-xxxx/numpy/
  → runs: python setup.py build_ext
    → gcc -shared -fPIC numpy/core/src/multiarray/... -o numpy/core/_multiarray_umath.cpython-311-x86_64-linux-gnu.so
    → gcc -shared -fPIC numpy/random/... -o numpy/random/_common.cpython-311-x86_64-linux-gnu.so
  → copies everything to site-packages/numpy/
  → writes dist-info/ with METADATA + RECORD
```

If we strace this `pip install`, we capture:

- Every `.c` → `.o` → `.so` compilation (gcc invocations)
- Every `.py` file copy
- The METADATA and RECORD writes

This is **exactly analogous to the Java pipeline** where strace captures
javac reading `.java` files.

### 6.5 Virtual Environments

Python projects use virtual environments to isolate dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

All packages install to `.venv/lib/python3.x/site-packages/`.
The `dist-info/` directories are all here.

### 6.6 Lock Files

<table>
<tr>
  <th style="min-width:100px">Tool</th>
  <th style="min-width:200px">Lock File</th>
  <th>Contains</th>
</tr>
<tr>
  <td><strong>pip</strong></td>
  <td><code>requirements.txt</code> (pinned)</td>
  <td>Package==version (no hashes by default)</td>
</tr>
<tr>
  <td><strong>pip-tools</strong></td>
  <td><code>requirements.txt</code> (compiled)</td>
  <td>Package==version + hashes</td>
</tr>
<tr>
  <td><strong>poetry</strong></td>
  <td><code>poetry.lock</code></td>
  <td>Full dependency tree + hashes</td>
</tr>
<tr>
  <td><strong>pipenv</strong></td>
  <td><code>Pipfile.lock</code></td>
  <td>Full dependency tree + hashes</td>
</tr>
<tr>
  <td><strong>pdm</strong></td>
  <td><code>pdm.lock</code></td>
  <td>Full dependency tree + hashes</td>
</tr>
<tr>
  <td><strong>uv</strong></td>
  <td><code>uv.lock</code></td>
  <td>Full dependency tree + hashes</td>
</tr>
</table>

**Key difference from other languages:** Python has no single standard lock
file. `requirements.txt` is the de facto standard but varies in format.
`poetry.lock` and `uv.lock` are richer but not universal.

---

## 7. Gap Analysis: What bomsh_pylib.py Cannot Do

### 7.1 Comparison Matrix

<table>
<tr>
  <th style="min-width:200px">Capability</th>
  <th style="min-width:160px">C/C++ (bomtrace3)</th>
  <th style="min-width:180px">Java (strace+bomsh_java)</th>
  <th style="min-width:160px">Python (bomsh_pylib.py)</th>
  <th style="min-width:80px">Gap</th>
</tr>
<tr>
  <td>Intercept build commands</td>
  <td>✅ ptrace execve</td>
  <td>✅ strace openat</td>
  <td>❌</td>
  <td><strong>Critical</strong></td>
</tr>
<tr>
  <td>Map source → artifact</td>
  <td>✅ .c → .o → binary</td>
  <td>✅ .java → .class → JAR</td>
  <td>❌</td>
  <td><strong>Critical</strong></td>
</tr>
<tr>
  <td>C extension compilation</td>
  <td>✅ (native)</td>
  <td>N/A</td>
  <td>❌</td>
  <td><strong>High</strong></td>
</tr>
<tr>
  <td>Package name extraction</td>
  <td>✅ dpkg, vendored dir</td>
  <td>✅ pom.xml groupId:artifactId</td>
  <td>❌</td>
  <td><strong>Critical</strong></td>
</tr>
<tr>
  <td>Version extraction</td>
  <td>✅ 12 strategies</td>
  <td>✅ pom.xml version</td>
  <td>❌</td>
  <td><strong>Critical</strong></td>
</tr>
<tr>
  <td>License detection</td>
  <td>✅ via dpkg</td>
  <td>✅ via pom.xml</td>
  <td>❌</td>
  <td><strong>Medium</strong></td>
</tr>
<tr>
  <td>Direct vs transitive deps</td>
  <td>✅ via ADG depth</td>
  <td>✅ via mvn dependency:tree</td>
  <td>❌</td>
  <td><strong>High</strong></td>
</tr>
<tr>
  <td>PURL generation</td>
  <td>✅ pkg:deb/</td>
  <td>✅ pkg:maven/</td>
  <td>❌</td>
  <td><strong>Critical</strong></td>
</tr>
<tr>
  <td>SPDX document output</td>
  <td>✅ SpdxEmitter</td>
  <td>✅ JavaSpdxGenerator</td>
  <td>❌</td>
  <td><strong>Critical</strong></td>
</tr>
<tr>
  <td>Dynamic library detection</td>
  <td>✅ ldd</td>
  <td>N/A (JVM)</td>
  <td>❌ (for .so extensions)</td>
  <td><strong>Medium</strong></td>
</tr>
<tr>
  <td>Import analysis</td>
  <td>N/A</td>
  <td>N/A</td>
  <td>✅ (only capability)</td>
  <td>—</td>
</tr>
<tr>
  <td>venv support</td>
  <td>N/A</td>
  <td>N/A</td>
  <td>❌ (TODO in source)</td>
  <td><strong>High</strong></td>
</tr>
<tr>
  <td>Operates without executing imports</td>
  <td>✅</td>
  <td>✅</td>
  <td>❌ (uses importlib)</td>
  <td><strong>High</strong></td>
</tr>
</table>

### 7.2 The "importlib.import_module()" Problem

`bomsh_pylib.py` actually imports every module it encounters:

```python
pylib = importlib.import_module(module)
```

This means:

1. **All dependencies must be installed** — cannot analyze a project before
   installing its deps
2. **Side effects execute** — modules with `__init__.py` that perform I/O
   at import time
3. **C extensions must be loadable** — if `.so` fails to load (wrong
   platform, missing lib), the dep is silently missed
4. **Cannot analyze in isolation** — must run in the target environment

A better approach would use `importlib.metadata` (Python 3.8+) to read
installed package metadata **without importing the package code**.

---

## 8. Proposed Architecture: Python OmniBOR Pipeline

### 8.1 Two-Phase Approach (matching Java pattern)

```text
┌─────────────────────────────────────────────────────────┐
│ Python Pipeline (proposed)                               │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Phase 1: Instrumented Install (strace)                  │
│                                                         │
│ 1. Clone repo          git clone --branch <tag>         │
│ 2. Create venv         python -m venv .venv             │
│ 3. Syft SBOM           syft scan (manifest-based)       │
│ 4. Instrumented install                                 │
│    strace -f -e trace=openat,execve \                   │
│      pip install -r requirements.txt                    │
│    ├─ Captures every pip download + extract             │
│    ├─ Captures every gcc invocation (C extensions)      │
│    └─ Captures every .py file copy to site-packages     │
│ 5. bomsh_create_bom_python.py  (NEW upstream script)    │
│    ├─ Scans .venv/lib/python3.x/site-packages/         │
│    ├─ Reads METADATA from every dist-info/              │
│    ├─ Reads RECORD for file → hash mapping              │
│    ├─ Parses requirements.txt for direct deps           │
│    ├─ Builds dependency tree from Requires-Dist         │
│    └─ Produces treedb: gitoid → file path               │
│                                                         │
│ Phase 2: SPDX Generation (omnibor-analysis)             │
│                                                         │
│ 6. PythonSpdxGenerator  (NEW omnibor-analysis class)    │
│    ├─ Reads treedb from Phase 1                         │
│    ├─ Reads dist-info/METADATA for each package         │
│    ├─ Generates pkg:pypi/ PURLs                         │
│    ├─ Classifies: direct vs transitive                  │
│    ├─ Detects C extensions (.so files in RECORD)        │
│    └─ Produces analyzed + build SPDX per artifact       │
│ 7. Validate + collect + visualize                       │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 8.2 Why strace + pip Metadata (Not Just bomsh_pylib.py)

<table>
<tr>
  <th style="min-width:180px">Approach</th>
  <th style="min-width:220px">What It Captures</th>
  <th>Accuracy</th>
</tr>
<tr>
  <td><strong>bomsh_pylib.py alone</strong></td>
  <td>Python import graph at rest</td>
  <td>Low — misses installed-but-not-imported deps, C extensions, extras</td>
</tr>
<tr>
  <td><strong>pip metadata alone</strong></td>
  <td>Declared deps + installed files</td>
  <td>High for pure Python — misses build-time C compilation details</td>
</tr>
<tr>
  <td><strong>strace + pip metadata</strong></td>
  <td>Actual file I/O during install + declared deps</td>
  <td><strong>Highest</strong> — captures both what was installed AND what was compiled</td>
</tr>
</table>

The strace approach is essential for C extensions. When `pip install numpy`
compiles C code, strace captures:

```text
execve("/usr/bin/gcc", ["gcc", "-shared", "-fPIC", "numpy/core/src/multiarray/arrayobject.c", ...])
openat(AT_FDCWD, "numpy/core/src/multiarray/arrayobject.c", O_RDONLY)
openat(AT_FDCWD, "numpy/core/_multiarray_umath.cpython-311-x86_64-linux-gnu.so", O_WRONLY|O_CREAT)
```

This gives us the same `.c → .so` relationship data that bomtrace3 captures
for C/C++ projects.

---

## 9. Upstream bomsh Changes Required

### 9.1 Enhance `bomsh_pylib.py`

**Priority: 2 (Medium)**
**Estimated effort: ~100 lines of changes**

<table>
<tr>
  <th style="min-width:220px">Change</th>
  <th>Description</th>
</tr>
<tr>
  <td><strong>Add venv support</strong></td>
  <td>Accept <code>--venv</code> flag pointing to <code>.venv/</code> directory. Add venv's <code>site-packages/</code> to <code>sys.path</code> before analysis.</td>
</tr>
<tr>
  <td><strong>Add <code>importlib.metadata</code> parsing</strong></td>
  <td>Use <code>importlib.metadata.distributions()</code> to enumerate installed packages without importing them.</td>
</tr>
<tr>
  <td><strong>Add package grouping</strong></td>
  <td>Group resolved <code>.py</code> files by their owning package (from <code>top_level.txt</code>).</td>
</tr>
<tr>
  <td><strong>Detect <code>.so</code> extensions</strong></td>
  <td>Scan <code>dist-info/RECORD</code> for <code>.so</code>/<code>.pyd</code> files and flag them.</td>
</tr>
<tr>
  <td><strong>Remove import side effects</strong></td>
  <td>Replace <code>importlib.import_module()</code> with <code>importlib.util.find_spec()</code> for path resolution (no code execution).</td>
</tr>
</table>

### 9.2 Create `bomsh_create_bom_python.py` (NEW)

**Priority: 1 (Highest)**
**Estimated effort: ~500 lines**

This script is the Python equivalent of `bomsh_create_bom_java.py`. It:

1. **Scans `site-packages/`** for all `dist-info/` directories
2. **Reads `METADATA`** from each to extract:
   - `Name` → package name
   - `Version` → package version
   - `License` → SPDX license identifier
   - `Requires-Dist` → dependency declarations (with extras and markers)
3. **Reads `RECORD`** from each to get:
   - File path → SHA-256 hash mapping (already in gitoid-compatible format!)
   - File sizes
4. **Parses `requirements.txt`** (or `poetry.lock`/`uv.lock`) to determine
   which packages are direct dependencies
5. **Optionally parses strace log** to identify:
   - Which files were actually opened during install
   - Which gcc invocations compiled C extensions
6. **Builds treedb** JSON mapping gitoid hashes to file paths and package
   ownership
7. **Produces raw_logfile** with `outfile:`/`infile:` format:
   - Each package is an `outfile:` (the wheel/sdist archive)
   - Its installed files are `infile:` entries

**Output format (treedb):**

```json
{
  "gitoid:sha256:abc123...": {
    "file_path": ".venv/lib/python3.11/site-packages/requests/api.py",
    "package": "requests",
    "version": "2.31.0",
    "purl": "pkg:pypi/requests@2.31.0"
  },
  "gitoid:sha256:def456...": {
    "file_path": ".venv/lib/python3.11/site-packages/requests/models.py",
    "package": "requests",
    "version": "2.31.0",
    "purl": "pkg:pypi/requests@2.31.0"
  }
}
```

### 9.3 Enhance `bomsh_hook2.py` for Python Awareness (Optional)

**Priority: 4 (Low — only for build-from-source scenarios)**
**Estimated effort: ~200 lines**

Add Python-specific handlers to `bomsh_hook2.py`:

<table>
<tr>
  <th style="min-width:280px">Handler</th>
  <th style="min-width:200px">Detects</th>
  <th>Records</th>
</tr>
<tr>
  <td><code>is_python_build(prog)</code></td>
  <td><code>python setup.py build_ext</code></td>
  <td><code>.c</code> → <code>.so</code> relationships</td>
</tr>
<tr>
  <td><code>is_pip_install(prog)</code></td>
  <td><code>pip install</code></td>
  <td>Download → extract → install</td>
</tr>
<tr>
  <td><code>get_all_subfiles_in_setuptools_cmdline(argv)</code></td>
  <td><code>setup.py build_ext</code> invocations</td>
  <td>Extension module compilation</td>
</tr>
</table>

This is **only needed for packages built from source** (sdists with C
extensions). For pre-built wheels (the common case), pip metadata is
sufficient.

### 9.4 Create `bomsh_spdx_pypi.py` (Optional upstream SPDX)

**Priority: 3 (Low — omnibor-analysis has its own SPDX generator)**
**Estimated effort: ~500 lines**

This would be a standalone upstream script (like `bomsh_spdx_deb.py`) that
generates SPDX directly from pip metadata. However, since omnibor-analysis
already has a rich SPDX generation framework (`SpdxEmitter`,
`JavaSpdxGenerator`), the downstream `PythonSpdxGenerator` is likely
sufficient. This script is only needed if bomsh wants standalone Python SPDX
without omnibor-analysis.

---

## 10. omnibor-analysis Changes Required

### 10.1 Config Changes

Add to `app/config.yaml`:

```yaml
# Python target repository example
repos:
  httpie:
    url: https://github.com/httpie/cli.git
    branch: 3.2.4
    language: python
    build_steps:
      - pip install -r requirements.txt
    clean_cmd: pip uninstall -y -r requirements.txt
    description: Modern HTTP client CLI (~15 direct deps)
    output_binaries:
      - .venv/bin/http       # or entrypoint script
    requirements_file: requirements.txt  # NEW field

# Python-specific omnibor config
omnibor_python:
  strace_opts: -f -s99999 --seccomp-bpf -e trace=openat,execve -qqq
  create_bom_script: bomsh_create_bom_python.py
  strace_logfile: /tmp/strace_python_logfile
```

### 10.2 New Pipeline Runner: `run_python_pipeline()`

Add to `app/pipeline/lang_runners.py`:

```python
def run_python_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_python_cfg, run_ts,
):
    """Python pipeline: venv creation, strace-instrumented
    pip install, bomsh_create_bom_python.py, SPDX generation.
    """
    # Step 3: Create venv
    # Step 4: Instrumented pip install (strace)
    # Step 5a: bomsh_create_bom_python.py → treedb
    # Step 5b: PythonSpdxGenerator → SPDX
    # Step 6: Validate
    # Step 7: Collect
```

### 10.3 New Builder Method: `build_python()`

Add to `app/pipeline/builder.py`:

```python
def build_python(self, repo_name, repo_cfg, ...):
    """Python build: create venv, strace pip install, generate treedb.

    1. Create .venv in repo directory
    2. Run: strace -f -e openat,execve pip install -r requirements.txt
    3. Run: bomsh_create_bom_python.py -r <repo_dir> -j <treedb>
    """
```

### 10.4 New SPDX Generator: `PythonSpdxGenerator`

Create `app/spdx/python_generator.py` (~400 lines), modeled on
`JavaSpdxGenerator`:

<table>
<tr>
  <th style="min-width:220px">Method</th>
  <th>Purpose</th>
</tr>
<tr>
  <td><code>generate()</code></td>
  <td>Main entry point — produces analyzed + build SPDX</td>
</tr>
<tr>
  <td><code>_parse_pip_metadata()</code></td>
  <td>Read all dist-info/METADATA in site-packages</td>
</tr>
<tr>
  <td><code>_parse_requirements()</code></td>
  <td>Read requirements.txt for direct dep classification</td>
</tr>
<tr>
  <td><code>_build_dependency_tree()</code></td>
  <td>From Requires-Dist fields → transitive graph</td>
</tr>
<tr>
  <td><code>_classify_packages()</code></td>
  <td>Direct vs transitive, pure-python vs C-extension</td>
</tr>
<tr>
  <td><code>_generate_purl()</code></td>
  <td><code>pkg:pypi/{name}@{version}</code></td>
</tr>
<tr>
  <td><code>_detect_c_extensions()</code></td>
  <td>Scan RECORD for <code>.so</code>/<code>.pyd</code> files</td>
</tr>
<tr>
  <td><code>_emit_spdx()</code></td>
  <td>Produce SPDX 2.3 JSON</td>
</tr>
</table>

### 10.5 AdgParser Enhancement

Add Python artifact classification to `app/spdx/parser.py`:

```python
# Python classification rules:
if fp.endswith(".dist-info/METADATA"):  → package_metadata
elif fp.startswith(site_packages):
    if fp.endswith(".so") or fp.endswith(".pyd"):  → c_extension
    elif fp.endswith(".py"):  → python_source
elif fp.startswith(venv_dir):  → venv_infrastructure
```

### 10.6 Docker Container Changes

Add to `docker/Dockerfile`:

```dockerfile
# Python build support (for C extension compilation tracing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-venv \
    python3-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*
```

### 10.7 Version Detection

Add Python-specific strategies to `app/version_detection.py`:

<table>
<tr>
  <th style="min-width:180px">Strategy</th>
  <th style="min-width:200px">Pattern</th>
  <th>Source</th>
</tr>
<tr>
  <td><code>dist-info/METADATA</code></td>
  <td><code>Version: x.y.z</code></td>
  <td>Installed package metadata</td>
</tr>
<tr>
  <td><code>pyproject.toml</code></td>
  <td><code>version = "x.y.z"</code></td>
  <td>Project source</td>
</tr>
<tr>
  <td><code>setup.cfg</code></td>
  <td><code>version = x.y.z</code></td>
  <td>Legacy setup</td>
</tr>
<tr>
  <td><code>setup.py</code></td>
  <td><code>version="x.y.z"</code></td>
  <td>Legacy setup</td>
</tr>
<tr>
  <td><code>__version__</code></td>
  <td><code>__version__ = "x.y.z"</code></td>
  <td>Source code convention</td>
</tr>
</table>

---

## 11. Python Project Categories and Strategies

### 11.1 Category A: Pure Python Application (e.g., httpie, black, ruff)

**Characteristics:** All deps are pure Python wheels. No C compilation.
**Strategy:** pip metadata only. No strace needed for deps (strace optional for
 validation).
**Data sources:**

- `requirements.txt` or `pyproject.toml` → direct deps
- `dist-info/METADATA` → version, license, transitive deps
- `dist-info/RECORD` → file hashes
- `dist-info/top_level.txt` → package directory names

### 11.2 Category B: Python Application with C Extensions (e.g., Django + psycopg2)

**Characteristics:** Some deps compile C code during install (psycopg2, lxml,
cryptography).
**Strategy:** strace during `pip install` + pip metadata.
**Data sources:**

- All of Category A, PLUS:
- strace log → gcc invocations during extension compilation
- `.so` files in RECORD → identify compiled extensions
- Can produce bomtrace3-style `.c → .so` relationship data

### 11.3 Category C: Python Library (e.g., requests, flask)

**Characteristics:** The "output binary" IS the installed package in
site-packages.
**Strategy:** pip metadata for the package itself + its declared deps.
**SPDX root package:** The library wheel/sdist.

### 11.4 Category D: Python with Rust Extensions (e.g., pydantic-core, ruff)

**Characteristics:** Uses maturin or setuptools-rust to compile Rust code.
**Strategy:** strace captures `cargo build --release` invocations during pip
install. Combine with bomtrace2 Rust interception for full `.rs → .so` graph.
**Note:** This is the most complex case — a Python package that embeds a Rust
binary.

### 11.5 Category E: Data Science Stack (e.g., numpy, scipy, pandas)

**Characteristics:** Heavy C/Fortran extensions, often installed from wheels
(pre-compiled).
**Strategy:**

- If wheel: pip metadata only (C extensions are pre-compiled, no source
  available)
- If sdist: strace captures gcc/gfortran invocations

---

## 12. SPDX Relationship Mapping for Python

<table>
<tr>
  <th style="min-width:260px">Python Concept</th>
  <th style="min-width:200px">SPDX Relationship</th>
  <th>Notes</th>
</tr>
<tr>
  <td>Direct dependency (in requirements.txt)</td>
  <td><code>DEPENDS_ON</code></td>
  <td>App → direct dep</td>
</tr>
<tr>
  <td>Transitive dependency</td>
  <td><code>DEPENDS_ON</code></td>
  <td>Direct dep → transitive dep</td>
</tr>
<tr>
  <td>Python source file in package</td>
  <td><code>CONTAINS</code></td>
  <td>Package → .py file</td>
</tr>
<tr>
  <td>C extension .so in package</td>
  <td><code>CONTAINS</code></td>
  <td>Package → .so file</td>
</tr>
<tr>
  <td>C source → .so compilation</td>
  <td><code>GENERATED_FROM</code></td>
  <td>.so → .c files (if strace captured)</td>
</tr>
<tr>
  <td>pip (installer)</td>
  <td><code>BUILD_TOOL_OF</code></td>
  <td>pip → installed package</td>
</tr>
<tr>
  <td>setuptools/maturin (build backend)</td>
  <td><code>BUILD_TOOL_OF</code></td>
  <td>Backend → compiled extensions</td>
</tr>
<tr>
  <td>gcc (for C extensions)</td>
  <td><code>BUILD_TOOL_OF</code></td>
  <td>gcc → .so file</td>
</tr>
<tr>
  <td>Python interpreter</td>
  <td><code>BUILD_TOOL_OF</code></td>
  <td>python3 → all packages (build SPDX only)</td>
</tr>
<tr>
  <td>Wheel from PyPI</td>
  <td><code>DISTRIBUTION_ARTIFACT</code></td>
  <td>Wheel → installed package</td>
</tr>
<tr>
  <td>Extra dependency (optional)</td>
  <td><code>OPTIONAL_DEPENDENCY_OF</code></td>
  <td>Extra dep → base package</td>
</tr>
</table>

### PURL Format

```text
pkg:pypi/requests@2.31.0
pkg:pypi/numpy@1.26.4
pkg:pypi/django@5.0.1
```

Per the PURL spec:

- Type: `pypi`
- Name: PyPI normalized name (lowercase, hyphens → hyphens)
- Version: exact installed version
- No namespace (PyPI is flat)

---

## 13. Implementation Priority and Phasing

### Phase 1: Metadata-Only Pipeline (MVP)

**Goal:** Generate accurate SPDX for pure Python projects.
**Effort:** ~2 weeks
**No strace required.**

1. Create `bomsh_create_bom_python.py` (upstream) — reads `dist-info/`
2. Create `PythonSpdxGenerator` (omnibor-analysis) — generates SPDX 2.3
3. Add `run_python_pipeline()` + `build_python()` to pipeline
4. Add `omnibor_python` config section
5. Docker: add `python3-venv`, `python3-dev`
6. Test with a pure Python project (e.g., httpie, black)

**Deliverable:** SPDX SBOMs comparable to Java for pure Python projects.

### Phase 2: strace Integration (C Extension Support)

**Goal:** Capture C extension compilation during `pip install`.
**Effort:** ~1 week

1. Add strace instrumentation to `build_python()`
2. Parse strace log for gcc/g++ invocations
3. Map `.c → .so` relationships in treedb
4. Enhance `PythonSpdxGenerator` to include `GENERATED_FROM` relationships
5. Test with numpy, psycopg2, or cryptography (sdist build)

**Deliverable:** Full SPDX for Python projects with C extensions.

### Phase 3: Enhanced bomsh_pylib.py

**Goal:** Runtime import analysis without side effects.
**Effort:** ~1 week

1. Replace `importlib.import_module()` with `importlib.util.find_spec()`
2. Add venv support (`--venv` flag)
3. Add package grouping via `importlib.metadata`
4. Integrate with `bomsh_create_bom_python.py` output for cross-validation

**Deliverable:** Safe runtime analysis that complements build-time data.

### Phase 4: Advanced Scenarios

**Goal:** Rust extensions (maturin), Fortran, editable installs.
**Effort:** ~2 weeks

1. Detect maturin builds (strace sees `cargo build`)
2. Chain Python strace with bomtrace2 Rust interception
3. Handle `pip install -e .` (editable mode — symlinks, no RECORD)
4. Handle Fortran extensions (scipy)

---

## 14. Open Questions

1. **Which Python project to start with?**
   Recommend a pure Python CLI tool (httpie, black, or ruff) for Phase 1,
   and a C-extension project (cryptography, psycopg2) for Phase 2.

2. **Should `bomsh_create_bom_python.py` be upstream or downstream?**
   Recommend upstream (in `omnibor/bomsh`) to follow the Java pattern.
   The SPDX generator stays in omnibor-analysis.

3. **Lock file format?**
   Recommend supporting `requirements.txt` first (de facto standard), with
   `poetry.lock` and `uv.lock` as future additions.

4. **What is the "output binary" for a Python project?**
   - For CLI tools: the entry point script (e.g., `.venv/bin/http`)
   - For libraries: the wheel file or the installed package directory
   - For applications: the main script (e.g., `app.py`, `manage.py`)
   This needs a `output_type` field in config.yaml.

5. **How to handle pre-compiled wheels vs. sdist builds?**
   Pre-compiled wheels have no C source → `.so` relationship data.
   SPDX should note this: "Binary wheel from PyPI — C extension source
   not available for build-time analysis."

6. **Should we intercept `pip install` or `python setup.py`?**
   `pip install` is correct — it's the standard entry point that handles
   both wheels and sdists. `setup.py` is legacy.

---

*Document version: April 2026*
*Based on: bomsh master branch (April 2026), omnibor-analysis main branch*
