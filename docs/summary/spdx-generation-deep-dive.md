# SPDX 2.3 SBOM Generation via OmniBOR — Deep Dive

This document provides a detailed technical description of how an SPDX 2.3 SBOM
document is generated in the `omnibor-analysis` project using the OmniBOR/Bomsh
toolchain. It covers every stage of the pipeline, the data flows between tools,
the structure of intermediate artifacts, and the final SPDX output.

---

## Table of Contents

1. [Pipeline Overview](#1-pipeline-overview)
2. [Stage 1: Build Interception with bomtrace3](#2-stage-1-build-interception-with-bomtrace3)
3. [Stage 2: ADG Generation with bomsh_create_bom.py](#3-stage-2-adg-generation-with-bomsh_create_bompy)
4. [Stage 3: SPDX Generation with bomsh_sbom.py](#4-stage-3-spdx-generation-with-bomsh_sbompy)
5. [Stage 4: Metadata Collection](#5-stage-4-metadata-collection)
6. [Stage 5: Per-Binary ADG SPDX Generation](#6-stage-5-per-binary-adg-spdx-generation)
7. [Stage 6: SPDX Validation](#7-stage-6-spdx-validation)
8. [Stage 7: Visualization](#8-stage-7-visualization)
9. [Data Flow Diagram](#9-data-flow-diagram)
10. [Anatomy of the Final SPDX Document](#10-anatomy-of-the-final-spdx-document)
11. [What Each Tool Contributes](#11-what-each-tool-contributes)
12. [Key Files and Paths](#12-key-files-and-paths)
13. [What Makes OmniBOR SBOMs Different](#13-what-makes-omnibor-sboms-different-from-manifest-only-sboms)
14. [Configured Repositories](#14-configured-repositories)

---

## 1. Pipeline Overview

The SPDX generation is not a single step — it is the culmination of a multi-stage
pipeline that begins with source code compilation and ends with a validated SPDX 2.3
JSON document. The pipeline runs inside a Docker container on a native x86_64 Linux
host (DigitalOcean droplet).

```
Source Code
    │
    ▼
┌──────────────────────────────┐
│  bomtrace3 make -j$(nproc)   │  ← Step 4: Build interception via ptrace
│  (instrumented build)        │
└──────────────┬───────────────┘
               │  raw logfile (every compiler/linker invocation)
               ▼
┌──────────────────────────────┐
│  bomsh_create_bom.py         │  ← Parses raw logfile into OmniBOR ADG
│  -r <raw_logfile>            │
│  -b <bom_dir>                │
└──────────────┬───────────────┘
               │  OmniBOR ADG documents + treedb + gitoid mappings
               ▼
┌──────────────────────────────┐
│  bomsh_sbom.py               │  ← Step 5a: SPDX from ADG
│  -b <bom_dir>                │
│  -o <output.spdx.json>       │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  MetadataCollector            │  ← Step 5b: dpkg + ldd metadata
│  collect_metadata.py (once)  │
│  collect_dynamic_libs.py     │
│  (per binary)                │
└──────────────┬───────────────┘
               │  component_metadata.json + dynamic_libs.json
               ▼
┌──────────────────────────────┐
│  AdgSpdxStep                 │  ← Step 5c: Per-binary SPDX from ADG
│  spdx_from_adg.py            │
│  (vendored detection,        │
│   version extraction,        │
│   dynamic lib resolution)    │
└──────────────┬───────────────┘
               │  <binary>_adg.spdx.json + <binary>_adg.spdx.html
               ▼
┌──────────────────────────────┐
│  SpdxValidator               │  ← Step 6: JSON Schema + semantic
│  (jsonschema + spdx-tools)   │
└──────────────────────────────┘
```

Each stage is orchestrated by `app/analyze.py` via the `AnalysisPipeline` facade.

---

## 2. Stage 1: Build Interception with bomtrace3

### What is bomtrace3?

`bomtrace3` is a build interception tool from the [omnibor/bomsh](https://github.com/omnibor/bomsh)
project. It is a modified version of `strace` (specifically, strace v6.11 with custom
patches applied) that intercepts system calls made during a software build.

### How it works

1. **ptrace-based interception**: `bomtrace3` wraps the final build command
   (e.g., `make -j$(nproc)`) and uses the Linux `ptrace` system call to intercept
   every `execve` call made by the build system.

2. **Compiler/linker identification**: For each intercepted process, bomtrace3
   checks whether the executed program is a "watched" program — typically compilers
   (`gcc`, `cc1`, `as`) and linkers (`ld`, `collect2`). This is done by the
   `bomsh_is_watched_program()` function in `bomsh_hook.c`.

3. **Input/output recording**: For each watched program invocation, bomtrace3
   records:
   - The **command line** (full argv)
   - The **input files** (source files, object files being linked)
   - The **output file** (the compiled object or linked binary)
   - The **SHA1 gitoid hash** of every input and output file

4. **Raw logfile output**: All of this data is written to a raw logfile at:
   ```
   /tmp/bomsh_hook_raw_logfile.sha1
   ```

### Raw logfile format

The raw logfile is a text file where each entry represents one compiler/linker
invocation. Each entry contains:

- The process ID and command
- Input file paths with their SHA1 gitoid hashes
- Output file path with its SHA1 gitoid hash
- Build metadata (working directory, timestamps)

### Example entry (simplified)

```
pid: 12345 ppid: 12340
build_cmd: /usr/bin/gcc -c -o src/tool_cb_rea.o src/tool_cb_rea.c
infiles: src/tool_cb_rea.c
infile_checksums: a1b2c3d4e5f6...
outfile: src/tool_cb_rea.o
outfile_checksum: f6e5d4c3b2a1...
```

### Requirements

- **Linux x86_64 only**: bomtrace3 requires native x86_64 execution because it
  depends on `sys/reg.h` for register access via ptrace. It does not work under
  QEMU/Rosetta emulation on Apple Silicon.
- **SYS_PTRACE capability**: The Docker container must run with `--cap-add=SYS_PTRACE`
  and `--security-opt seccomp:unconfined`.

### Configuration

In `config.yaml`:
```yaml
omnibor:
  tracer: bomtrace3
  raw_logfile: /tmp/bomsh_hook_raw_logfile.sha1
```

In `analyze.py`, the `BomtraceBuilder` class runs:
```python
f"{tracer} {make_cmd}"  # e.g., "bomtrace3 make -j$(nproc)"
```

---

## 3. Stage 2: ADG Generation with bomsh_create_bom.py

### What is the ADG?

The **Artifact Dependency Graph (ADG)** is the core OmniBOR data structure. It is a
directed acyclic graph where:

- **Nodes** are software artifacts (source files, object files, libraries, binaries),
  each identified by their cryptographic gitoid hash.
- **Edges** represent "was built from" relationships (e.g., `curl.o` was built from
  `curl.c` and `curl.h`).

The ADG provides **complete cryptographic provenance** — for any output binary, you
can trace back through every intermediate object file to every source file that
contributed to it.

### How bomsh_create_bom.py works

The script is invoked as:
```bash
bomsh_create_bom.py -r /tmp/bomsh_hook_raw_logfile.sha1 -b <output_dir>/omnibor/<repo>
```

It performs the following:

1. **Parses the raw logfile**: Reads every compiler/linker invocation entry from
   the bomtrace3 raw logfile.

2. **Builds the hash-tree database**: Constructs an in-memory graph where each
   output artifact's gitoid maps to the list of input artifact gitoids plus build
   metadata. This is stored in a Python dict:
   ```python
   # { gitoid_of_output => [list_of_input_gitoids + metadata] }
   ```

3. **Generates OmniBOR document files**: For each artifact in the graph, creates
   an OmniBOR document file under:
   ```
   <bom_dir>/.omnibor/objects/<hash_prefix>/<hash>
   ```
   Each OmniBOR document contains the gitoid references to all input artifacts,
   forming the ADG.

4. **Creates the gitoid→bom_id mapping**: Writes a critical JSON file:
   ```
   <bom_dir>/.omnibor/metadata/bomsh/bomsh_omnibor_doc_mapping
   ```
   This file maps each artifact's file gitoid (SHA1 hash of the file content) to
   its OmniBOR **bom_id** (the gitoid of the OmniBOR document that describes its
   inputs). This mapping is what Stage 3 uses to enrich the SPDX document.

### Output directory structure

After `bomsh_create_bom.py` runs, the bom directory looks like:

```
output/omnibor/curl/
└── .omnibor/
    ├── objects/
    │   └── sha1/
    │       ├── a1/
    │       │   └── b2c3d4e5...  (OmniBOR document for one artifact)
    │       ├── f6/
    │       │   └── e5d4c3b2...  (OmniBOR document for another artifact)
    │       └── ...
    └── metadata/
        └── bomsh/
            ├── bomsh_omnibor_doc_mapping    ← KEY FILE: { gitoid → bom_id }
            ├── bomsh_omnibor_treedb         ← full hash-tree database
            └── with-bom-files/
                └── ...                      ← list of files that have OmniBOR docs
```

### The bomsh_omnibor_doc_mapping file

This is the most important intermediate artifact. It is a JSON file with the structure:

```json
{
  "a1b2c3d4e5f6...": "x9y8z7w6v5u4...",
  "f6e5d4c3b2a1...": "p3q2r1s0t9u8..."
}
```

Where:
- **Key**: The SHA1 gitoid of a built artifact (e.g., the `curl` binary)
- **Value**: The OmniBOR bom_id — the gitoid of the OmniBOR document that records
  all the inputs that went into building that artifact

This mapping is what connects a specific binary file to its complete build provenance.

---

## 4. Stage 3: SPDX Generation with bomsh_sbom.py

### Overview

`bomsh_sbom.py` is the tool that actually produces the SPDX 2.3 document. It does
**not** create the SPDX from scratch — instead, it uses a **two-phase approach**:

1. **Phase A**: Internally call Syft to generate a baseline SPDX scaffold for each artifact
2. **Phase B**: Inject OmniBOR `ExternalRef` entries into the generated SPDX

> **Note:** Syft is an internal implementation detail of `bomsh_sbom.py`. It is not
> a user-facing tool in the OmniBOR pipeline. Users interact with `bomsh_sbom.py` and
> `spdx_from_adg.py`, which produce the final SPDX SBOMs. The primary output for
> enterprise use is `<binary>_adg.spdx.json` from `spdx_from_adg.py`.

### Invocation

Our pipeline calls:
```bash
bomsh_sbom.py -b <bom_dir> -o <output.spdx.json>
```

Where:
- `-b <bom_dir>`: Path to the OmniBOR directory containing the ADG and the
  `bomsh_omnibor_doc_mapping` file (output of Stage 2)
- `-o <output.spdx.json>`: Path for the final SPDX output file

### Phase A: Baseline SPDX scaffolding (via Syft internally)

`bomsh_sbom.py` internally calls [Syft](https://github.com/anchore/syft) (an
open-source SBOM generator by Anchore) to create the initial SPDX scaffold.

Syft scans the artifact file and produces a standards-compliant SPDX 2.3 JSON
scaffold containing:

- **Document creation info**: `spdxVersion`, `dataLicense` (CC0-1.0), `SPDXID`,
  `name`, `documentNamespace`, `creationInfo` (tool name, timestamp)
- **Package entries**: For each detected package/component:
  - Package name, version, download location
  - `PackageChecksum` (SHA256 and/or SHA1 of the file)
  - `externalRefs` (e.g., CPE identifiers, package URLs)
  - Supplier, originator information (if detectable)
- **File entries**: Individual file-level information
- **Relationships**: `DESCRIBES`, `CONTAINS`, `DEPENDS_ON` relationships between
  the document, packages, and files

At this point, the SPDX document is a baseline scaffold. It does **not** yet
contain any build provenance or OmniBOR information.

### Phase B: OmniBOR ExternalRef injection

After the baseline scaffold is produced, `bomsh_sbom.py` enriches it:

1. **Reads the OmniBOR doc mapping**: Loads `bomsh_omnibor_doc_mapping` from the
   bom directory to get the `{ file_gitoid → bom_id }` mapping.

2. **Computes the artifact's gitoid**: Calculates the SHA1 hash of the artifact
   file to look up its bom_id in the mapping.

3. **Injects ExternalRef into SPDX packages**: For each package in the SPDX JSON's
   `packages` array, appends an `externalRefs` entry:

   ```json
   {
     "referenceCategory": "PERSISTENT-ID",
     "referenceType": "gitoid",
     "referenceLocator": "gitoid:blob:sha1:<bom_id>"
   }
   ```

   This `ExternalRef` is the critical link between the SPDX SBOM and the OmniBOR
   ADG. Given the `bom_id`, anyone can:
   - Retrieve the OmniBOR document from an OmniBOR repository
   - Reconstruct the complete input tree for that artifact
   - Verify the cryptographic provenance chain

4. **Writes the final SPDX JSON**: The enriched document is saved to the output
   path specified by `-o`.

### The ExternalRef in detail

The injected `ExternalRef` follows the SPDX 2.3 specification for external
references:

| Field | Value | Meaning |
|-------|-------|---------|
| `referenceCategory` | `PERSISTENT-ID` | A persistent, content-addressable identifier |
| `referenceType` | `gitoid` | The identifier type is a Git Object ID |
| `referenceLocator` | `gitoid:blob:sha1:<bom_id>` | The actual OmniBOR document identifier |

The `referenceLocator` format breaks down as:
- `gitoid:` — prefix indicating this is a gitoid
- `blob:` — the Git object type (blob = file content)
- `sha1:` — the hash algorithm used
- `<bom_id>` — the 40-character hex SHA1 hash of the OmniBOR document

This is the **only** OmniBOR-specific addition to the SPDX document. Everything
else in the SPDX comes from the baseline scaffold.

---

## 5. Stage 4: Metadata Collection

After the build, `MetadataCollector` (in `analyze.py`) runs two collection scripts
to gather dpkg package metadata and dynamic library information needed for rich
SPDX generation.

### collect_metadata.py (once per repo)

Reads the bomsh treedb and resolves every system file (libraries, headers, CRT
objects) to its dpkg package:

1. Iterates all treedb entries, filters system files (not under `repos/`)
2. Resolves canonical paths (`os.path.realpath` to handle `/../`)
3. Runs `dpkg -S <path>` for each file to find the owning package
4. Runs `dpkg-query --showformat` to extract full metadata: name, version,
   source package, architecture, maintainer, homepage, section
5. Writes `component_metadata.json` to the metadata directory

**Output:** `output/omnibor/<repo>/metadata/component_metadata.json`

### collect_dynamic_libs.py (per binary)

For each output binary, identifies dynamically linked libraries:

1. Runs `ldd <binary>` to get the full dependency tree (direct + transitive)
2. Runs `readelf -d <binary>` to identify NEEDED entries (direct deps only)
3. For each library found by ldd:
   - Marks as `direct: true/false` based on NEEDED set
   - Resolves the `.so` path to its dpkg package via `dpkg -S`
   - Extracts full dpkg metadata (same as collect_metadata.py)
4. Detects **project-built shared objects** — NEEDED entries that ldd reports
   as "not found" (e.g., `libavcodec.so.62` built by FFmpeg itself)
5. Writes `dynamic_libs.json` to a per-binary metadata directory

**Output:** `output/omnibor/<repo>/metadata/<binary>/dynamic_libs.json`

### Idempotency

Both scripts skip collection if their output files already exist. Delete the
output files to force re-collection.

---

## 6. Stage 5: Per-Binary ADG SPDX Generation

The `AdgSpdxStep` class orchestrates `spdx_from_adg.py` to generate one SPDX
2.3 JSON document per output binary. This is the most sophisticated stage of
the pipeline, producing SBOMs with rich component breakdown.

### Architecture

```
AdgSpdxStep.generate()
  └─► AdgSpdxGenerator (per binary)
        ├─► AdgParser         — parse treedb, classify artifacts
        ├─► ComponentResolver — load dpkg metadata + dynamic libs
        ├─► SpdxEmitter       — detect vendored libs, emit SPDX
        │     ├─► _detect_vendored_groups()
        │     ├─► _split_sub_components()
        │     └─► VendoredVersionDetector
        └─► generate_html()   — D3.js visualization
```

### Vendored Directory Detection

Source files are grouped into vendored libraries by matching path patterns.
Two modes:

- **Generic patterns** (`/deps/`, `/vendor/`, `/third_party/`, `/thirdparty/`,
  `/external/`, `/contrib/`): library name = first path component after the
  pattern. E.g., `/deps/lua/src/lapi.c` → library `lua`
- **Per-repo specific patterns** (from `vendored_dirs` in `config.yaml`):
  library name = the directory name from the pattern itself. E.g.,
  `/liblua/src/lapi.c` with pattern `/liblua/` → library `liblua`

### Vendored Version Detection

`VendoredVersionDetector` scans vendored source directories for version
information using multiple strategies:

1. **VERSION files** — `VERSION`, `version.txt`, etc.
2. **#define macros** — `#define LIB_VERSION "1.2.3"`, `#define MAJOR 1`
3. **Header comments** — `/* libfoo v1.2.3 */`
4. **.pc.in files** — `Version: @VERSION@` patterns

### SPDX Relationship Types

Each component becomes an SPDX package with a relationship to the root binary:

| Relationship | Meaning | Source |
|---|---|---|
| `STATIC_LINK` | Vendored/compiled-in library | Vendored dir detection |
| `DYNAMIC_LINK` | Runtime shared library | ldd + dpkg metadata |
| `BUILD_TOOL_OF` | Compiler/toolchain | gcc version from build |
| `CONTAINS` | Source file belongs to package | Treedb artifact classification |

### direct_only Mode

When a project produces both executables and shared libraries (e.g., curl +
libcurl.so), the executable's SBOM uses `direct_only=True` to avoid duplicating
transitive dependencies that belong to the shared library's SBOM.

---

## 7. Stage 6: SPDX Validation

After generation, all SPDX documents (both bomsh_sbom.py output and ADG SPDX
per-binary outputs) are validated by the `SpdxValidator` class using two checks:

### JSON Schema validation

- Uses the `jsonschema` Python library
- Validates against the official SPDX 2.3 JSON Schema from
  `https://raw.githubusercontent.com/spdx/spdx-spec/development/v2.3.1/schemas/spdx-schema.json`
- Checks structural correctness: required fields present, correct types, valid
  enum values, proper nesting

### Semantic validation

- Uses the `spdx-tools` Python library
- Parses the SPDX document into an internal object model
- Runs `validate_full_spdx_document()` which checks business rules:
  - All `SPDXID` references resolve to actual elements
  - Relationships reference valid package/file IDs
  - License expressions are valid SPDX license identifiers
  - Creator information is properly formatted
  - Document namespace is a valid URI

Both validation phases degrade gracefully — if either library is unavailable, that
phase is skipped with a warning rather than failing the pipeline.

---

## 8. Stage 7: Visualization

Every ADG SPDX output automatically generates an interactive HTML dependency
graph using `spdx_visualize.py`:

- **D3.js force-directed layout** — packages are nodes, relationships are edges
- **Color-coded by type**: purple (root), teal (STATIC_LINK), red (DYNAMIC_LINK),
  yellow (BUILD_TOOL_OF)
- **Node size** scales by source file count
- **Interactive**: drag nodes, zoom/pan, hover for tooltips (version, purpose,
  file count, comments)
- **Standalone HTML** — no server needed, opens in any browser

Output: `output/spdx/<repo>/<binary>_adg.spdx.html`

---

## 9. Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        BUILD PHASE                                  │
│                                                                     │
│  Source files ──► bomtrace3 make ──► Object files ──► Binary        │
│       │                                                    │        │
│       │              ptrace intercepts every               │        │
│       │              compiler/linker call                   │        │
│       │                                                    │        │
│       └──────────────────┬─────────────────────────────────┘        │
│                          │                                          │
│                          ▼                                          │
│              /tmp/bomsh_hook_raw_logfile.sha1                       │
│              (input files, output files, gitoid hashes,             │
│               command lines, PIDs)                                  │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     ADG GENERATION PHASE                            │
│                                                                     │
│  bomsh_create_bom.py                                                │
│       │                                                             │
│       ├──► .omnibor/objects/sha1/<prefix>/<hash>                    │
│       │    (OmniBOR document files — the ADG nodes)                 │
│       │                                                             │
│       └──► .omnibor/metadata/bomsh/bomsh_omnibor_doc_mapping        │
│            { "file_gitoid": "bom_id", ... }                         │
│            (maps each artifact to its OmniBOR provenance doc)       │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     SPDX GENERATION PHASE                           │
│                                                                     │
│  bomsh_sbom.py                                                      │
│       │                                                             │
│       ├──► [internal] baseline SPDX scaffold                        │
│       │    → SPDX 2.3 JSON (packages, files, checksums)            │
│       │                                                             │
│       ├──► Reads bomsh_omnibor_doc_mapping                          │
│       │    → looks up file_gitoid → bom_id                          │
│       │                                                             │
│       └──► Injects ExternalRef into SPDX packages                  │
│            → { "PERSISTENT-ID", "gitoid", "gitoid:blob:sha1:..." } │
│                                                                     │
│       Output: <repo>_omnibor_<timestamp>.spdx.json                  │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     VALIDATION PHASE                                │
│                                                                     │
│  SpdxValidator                                                      │
│       ├──► JSON Schema check (jsonschema library)                   │
│       └──► Semantic check (spdx-tools library)                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 10. Anatomy of the Final SPDX Document

The final SPDX 2.3 JSON document has this structure (simplified):

```json
{
  "spdxVersion": "SPDX-2.3",
  "dataLicense": "CC0-1.0",
  "SPDXID": "SPDXRef-DOCUMENT",
  "name": "curl",
  "documentNamespace": "https://anchore.com/syft/file/curl-<uuid>",
  "creationInfo": {
    "created": "2026-02-12T23:00:00Z",
    "creators": [
      "Tool: syft-1.x.x"
    ],
    "licenseListVersion": "3.23"
  },
  "packages": [
    {
      "SPDXID": "SPDXRef-Package-curl",
      "name": "curl",
      "versionInfo": "8.x.x",
      "downloadLocation": "NOASSERTION",
      "filesAnalyzed": true,
      "checksums": [
        {
          "algorithm": "SHA256",
          "checksumValue": "abcdef1234567890..."
        }
      ],
      "externalRefs": [
        {
          "referenceCategory": "PACKAGE-MANAGER",
          "referenceType": "purl",
          "referenceLocator": "pkg:generic/curl@8.x.x"
        },
        {
          "referenceCategory": "PERSISTENT-ID",
          "referenceType": "gitoid",
          "referenceLocator": "gitoid:blob:sha1:x9y8z7w6v5u4..."
        }
      ],
      "supplier": "NOASSERTION",
      "primaryPackagePurpose": "APPLICATION"
    }
  ],
  "files": [ ... ],
  "relationships": [
    {
      "spdxElementId": "SPDXRef-DOCUMENT",
      "relationshipType": "DESCRIBES",
      "relatedSpdxElement": "SPDXRef-Package-curl"
    }
  ]
}
```

### What the baseline scaffold provides (standard SPDX)

- `spdxVersion`, `dataLicense`, `SPDXID`, `name`, `documentNamespace`
- `creationInfo` (tool identity, timestamp, license list version)
- `packages` array with name, version, checksums, download location, supplier
- `externalRefs` with `PACKAGE-MANAGER` type (purl, CPE)
- `files` array with individual file metadata
- `relationships` array (DESCRIBES, CONTAINS, etc.)

### What OmniBOR/Bomsh adds

- One additional `externalRefs` entry per package:
  ```json
  {
    "referenceCategory": "PERSISTENT-ID",
    "referenceType": "gitoid",
    "referenceLocator": "gitoid:blob:sha1:<bom_id>"
  }
  ```

This single addition is the bridge between the SPDX SBOM and the complete
cryptographic build provenance stored in the OmniBOR ADG.

---

## 11. What Each Tool Contributes

| Tool | Role | Data Produced |
|------|------|---------------|
| **bomtrace3** | Build interception | Raw logfile: every compiler/linker call with input/output file hashes |
| **bomsh_create_bom.py** | ADG generation | OmniBOR document files (the ADG) + `bomsh_omnibor_doc_mapping` (gitoid→bom_id) |
| **bomsh_sbom.py** | SPDX generation | Produces SPDX 2.3 JSON (internally uses Syft for baseline scaffolding) and injects OmniBOR `ExternalRef` (PERSISTENT-ID/gitoid) |
| **collect_metadata.py** | dpkg resolution | `component_metadata.json` — system file → dpkg package mapping |
| **collect_dynamic_libs.py** | Dynamic lib analysis | `dynamic_libs.json` — per-binary ldd/readelf + dpkg metadata |
| **spdx_from_adg.py** | ADG SPDX generation | Per-binary SPDX with vendored/dynamic/build-tool breakdown |
| **spdx_visualize.py** | Visualization | Interactive HTML dependency graph (D3.js) |
| **SpdxValidator** | Validation | Confirms SPDX structural and semantic correctness |

### What is NOT in the SPDX

- The ADG itself is **not** embedded in the SPDX — only a reference to it (the bom_id)
- Individual source file hashes are **not** listed in the SPDX — they are in the ADG
- Build commands are **not** in the SPDX — they are in the raw logfile
- The SPDX does **not** contain vulnerability data or license analysis beyond what
  the baseline scaffold detects

---

## 12. Key Files and Paths

All paths are relative to `/workspace` inside the Docker container, which maps to
`/root/omnibor-analysis` on the droplet.

| File | Path | Description |
|------|------|-------------|
| Config | `app/config.yaml` | Defines repos, build steps, tool paths |
| Raw logfile | `/tmp/bomsh_hook_raw_logfile.sha1` | bomtrace3 output |
| ADG documents | `output/omnibor/<repo>/.omnibor/objects/` | OmniBOR ADG files |
| Doc mapping | `output/omnibor/<repo>/.omnibor/metadata/bomsh/bomsh_omnibor_doc_mapping` | gitoid→bom_id JSON |
| SPDX output | `output/spdx/<repo>/<repo>_omnibor_<ts>.spdx.json` | Final SPDX document |
| Output binaries | `output/binaries/<repo>/<ts>/` | Collected build artifacts |

---

## 13. What Makes OmniBOR SBOMs Different from Manifest-Only SBOMs

Manifest-only SBOM generators scan package metadata (lockfiles, package managers)
but do not observe the actual build. OmniBOR build interception captures what
actually happened during compilation:

| Aspect | Manifest-Only SBOM | OmniBOR Build-Time SBOM |
|--------|-------------------|------------------------|
| Build provenance | None | Full cryptographic chain via OmniBOR ExternalRef |
| Vendored source detection | No | Yes — bomtrace3 sees every `.c` → `.o` → binary |
| Dynamic library resolution | No | Yes — ldd/readelf after build interception |
| OmniBOR ExternalRef | No | Yes — `gitoid:blob:sha1:<bom_id>` |
| Can trace to source files | No | Yes — via bom_id → ADG → input gitoids |
| Reproducibility proof | No | Yes — ADG provides cryptographic evidence |

---

## 14. Configured Repositories

**C/C++ (bomtrace3):**
| Repo | Binaries | Vendored Libs | Dynamic Libs | Build Time | Notes |
|---|---|---|---|---|---|
| **curl** | curl, libcurl.so | — (uses /deps/) | ~10 | ~5 min | Reference target; autoconf + make |
| **redis** | redis-server | 8 (jemalloc, lua, hiredis, ...) | ~5 | ~3 min | Good vendored lib test case |
| **ffmpeg** | ffmpeg, ffprobe, libavcodec.so, ... | — | 20+ | ~24 min | Large build; --enable-shared to avoid bomtrace3 ar overflow |
| **nmap** | nmap, ncat, nping | 7 (liblua, libssh2, libdnet, ...) | 14 | ~3.3 min | Uses vendored_dirs config for top-level lib detection |

**Go (bomtrace2):**
| Repo | Binaries | Direct Deps | Indirect Deps | Build Time | Notes |
|---|---|---|---|---|---|
| **lazygit** | lazygit | 33 | 29 | ~2 min | Terminal UI; stdlib + direct/indirect grouping |
| **pocketbase** | pocketbase | 4 | — | ~1 min | Backend-as-a-service |

**Rust (bomtrace2):**
| Repo | Binaries | Crate Deps | Build Time | Notes |
|---|---|---|---|---|
| **oxipng** | oxipng | 44 | ~1 min | All crates use STATIC_LINK |
| **dura** | dura | 150+ | ~3 min | Large dependency tree |

**Java (strace + bomsh_create_bom_java.py):**
| Repo | Binaries | Direct Deps | Transitive Deps | Build Time | Notes |
|---|---|---|---|---|---|
| **checkstyle** | checkstyle.jar | 10 | 21 | ~1 min | Single module |
| **jsoup** | jsoup.jar | 1 | 0 | ~30s | Minimal deps |
| **dependency-check** | 3 JARs (cli, core, utils) | varies | varies | ~2 min | Multi-module with sibling filtering |
| **crawler4j** | crawler4j.jar | 14 | 12 | ~30s | Single module |

---

## References

- [OmniBOR Specification](https://omnibor.io)
- [omnibor/bomsh GitHub Repository](https://github.com/omnibor/bomsh)
- [SPDX 2.3 Specification](https://spdx.github.io/spdx-spec/v2.3/)
- [SPDX 2.3 JSON Schema](https://github.com/spdx/spdx-spec/blob/development/v2.3.1/schemas/spdx-schema.json)
- [Syft (Anchore)](https://github.com/anchore/syft) — used internally by bomsh_sbom.py
- [spdx-tools Python Library](https://github.com/spdx/tools-python)
