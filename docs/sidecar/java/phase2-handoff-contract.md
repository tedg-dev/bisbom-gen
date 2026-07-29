# Java Phase 2 SBOM-Generation Output & Output Manifest

| | |
|---|---|
| **Audience** | bisbom-gen maintainers (producers) and any downstream consumer of the generated SBOM set |
| **Owner (producer side)** | bisbom-gen (USER + Cascade) |
| **Scope specified** | Phase 2 **SBOM-generation output set** (consumer-agnostic) |
| **Example consumer** | Corona SBOM filing / storage layer (other team) — one possible downstream, NOT part of Phase 2 |
| **Out of scope** | How / where Phase 2 runs (the wrapper environment); transport / delivery / intake |
| **Related issue** | `#11004` (A2), sub-issue of `#11002` |
| **Status** | Draft for peer-team review — schema is a proposal, open to adjustment |
| **Last updated** | 2026-07-09 |

---

## Purpose

**Phase 2 is SBOM generation, full stop.** It consumes Phase 1 metadata and
emits SPDX SBOMs per production JAR. It does not transport, file, or deliver
anything, and it is agnostic to **how or where** it runs — the wrapper
environment (Corona, a build host, a container, the test-app harness) is a
**secondary concern** that sits *around* the generator, not inside it.

This document specifies the **producer-side output contract**: the artifact
set Phase 2 generates and the `sbom_handoff_manifest.json` that enumerates and
makes it verifiable. The manifest is a **consumer-agnostic output descriptor**
— any downstream (Corona included) can ingest the set without reading the
source tree, the JARs, or any bisbom-gen internals.

It is **design-first**: the schema below is proposed for review by peer teams
that consume the output (e.g. the Corona delivery layer). Field names and
shapes may be adjusted to match what a consumer already expects before
implementation.

---

## What this specifies (and what it does not)

The Java build-based SBOM flow spans a Phase 1 metadata capture and Phase 2
SBOM generation. This document specifies **only the output of Phase 2
generation** — not any transport or delivery step.

| Item | What it is | Manifest | Specified here |
|---|---|---|---|
| Phase 1 metadata capture | Build-machine capture of treedb + dependency metadata | `phase1_manifest.json` (`app/pipeline/manifest.py`) | No |
| **Phase 2 generation output** | The SBOM set Phase 2 emits from Phase 1 metadata | `sbom_handoff_manifest.json` (this doc) | **Yes** |
| Wrapper / delivery | How/where Phase 2 runs; moving the output to a consumer (e.g. Corona) | — | No (secondary, separate concern) |

For the Phase 1 capture and the overall phase split, see
[`enterprise-sbom.md`](enterprise-sbom.md) and the
[java-sbom-phase-split](java-sbom-phase-split.png) diagram. This document does
not define **how or where** Phase 2 runs, nor how its output reaches any
consumer — it defines only **what** Phase 2 generates.

---

## What Phase 2 owns (and what is not Phase 2)

| Concern | Part of Phase 2? |
|---|---|
| Generating the SBOM artifact set (`_build` + `_analyzed` per JAR) | Yes — bisbom-gen |
| Writing the `sbom_handoff_manifest.json` output descriptor | Yes — bisbom-gen |
| Digest computation (SHA-256 + OmniBOR GitOID) over the output | Yes — bisbom-gen |
| How / where Phase 2 is invoked (the wrapper environment) | **Not Phase 2** (secondary concern) |
| Corona intake mechanism (S3 bucket vs API) and data model | **Not Phase 2** (a consumer's concern) |
| Product / Release / Image pathing inside Corona | **Not Phase 2** (a consumer's concern) |
| Authentication / authorization to any consumer | **Not Phase 2** |
| Network transport, upload client, retry / delivery semantics | **Not Phase 2** |
| Non-Java languages | Out of this doc (shared SI-5) |

---

## The output artifact set

Per successful Phase 2 run, for **each production JAR**, Phase 2 emits a pair
of SPDX 2.3 documents following the CISA SBOM-type taxonomy:

| File | SBOM type | Contents | Indexed in manifest |
|---|---|---|---|
| `{jar_stem}_build.spdx.json` | Build SBOM | Full resolved dependency graph (Maven/Gradle `DEPENDS_ON`, `BUILD_TOOL_OF`), `test`-scope excluded | Yes |
| `{jar_stem}_analyzed.spdx.json` | Analyzed SBOM | Only the source files packaged in the JAR | Yes |
| `{jar_stem}_build.spdx.html` | — | Interactive D3.js visualization of the build SBOM | No (informational) |
| `{jar_stem}_analyzed.spdx.html` | — | Interactive D3.js visualization of the analyzed SBOM | No (informational) |

Where `{jar_stem}` is the JAR filename with the `.jar` suffix removed
(e.g. JAR `bisbom-java-testapp-1.0.0.jar` -> stem
`bisbom-java-testapp-1.0.0`).

### Directory layout

The output set is written to a **config-driven** location (no hardcoded
paths). The default, mirroring the current pipeline, is:

```text
<output_dir>/spdx/java/<repo_name>/<run_ts>/
├── sbom_handoff_manifest.json                        <- the output descriptor (this contract)
├── bisbom-java-testapp-1.0.0_build.spdx.json
├── bisbom-java-testapp-1.0.0_analyzed.spdx.json
├── bisbom-java-testapp-1.0.0_build.spdx.html        (informational)
└── bisbom-java-testapp-1.0.0_analyzed.spdx.html     (informational)
```

For a multi-module project, each production JAR contributes its own
`_build` / `_analyzed` pair in the same run directory.

---

## The output manifest

A single machine-readable index, `sbom_handoff_manifest.json`, is written at
the root of the run directory. It lets any consumer enumerate and verify the
generated set without scanning the directory or parsing SPDX.

### Location and versioning

- **Filename:** `sbom_handoff_manifest.json`
- **Location:** the root of the output set directory (alongside the SPDX files)
- **Version field:** `version` carries the contract schema version, starting at
  `"1.0"`, following semantic versioning (a breaking schema change bumps the
  major).

### Schema (proposed, v1.0)

Top-level object:

| Field | Type | Required | Description |
|---|---|---|---|
| `version` | string | yes | Contract schema version (`"1.0"`) |
| `generated_ts` | string | yes | ISO-8601 UTC timestamp of manifest creation |
| `producer` | object | yes | Producer identity (see below) |
| `repo_name` | string | yes | Repository name |
| `language` | string | yes | Always `"java"` for this contract |
| `commit_sha` | string | yes | Source commit SHA (from `phase1_manifest.json`) |
| `vcs_uri` | string | yes | VCS location the source was obtained from |
| `build_id` | string | yes | Config-driven build / release identifier |
| `source_manifest` | string | no | Relative path to the `phase1_manifest.json` this run consumed, when available |
| `sboms` | array | yes | One entry per production JAR (see below) |

`producer` object:

| Field | Type | Required | Description |
|---|---|---|---|
| `tool` | string | yes | Producing tool (`"bisbom-gen"`) |
| `phase` | string | yes | `"phase2"` |
| `mode` | string | yes | `"sidecar"` or `"standalone"` |

Each `sboms[]` entry:

| Field | Type | Required | Description |
|---|---|---|---|
| `artifact` | object | yes | The JAR the SBOMs describe (see below) |
| `build` | object | yes | The build SBOM file record |
| `analyzed` | object | yes | The analyzed SBOM file record |

`artifact` object:

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | JAR filename (e.g. `bisbom-java-testapp-1.0.0.jar`) |
| `sha256` | string | yes | Plain SHA-256 of the JAR (hex), sourced from Phase 1 metadata |
| `gitoid` | string | yes | OmniBOR GitOID of the JAR, `gitoid:blob:sha256:<hex>` |

Each SBOM file record (`build`, `analyzed`):

| Field | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | Path **relative to the manifest** |
| `sha256` | string | yes | Plain SHA-256 of the SBOM file (hex) |
| `gitoid` | string | yes | OmniBOR GitOID of the SBOM file, `gitoid:blob:sha256:<hex>` |

### Example

```json
{
  "version": "1.0",
  "generated_ts": "2026-06-29T23:12:04Z",
  "producer": {
    "tool": "bisbom-gen",
    "phase": "phase2",
    "mode": "sidecar"
  },
  "repo_name": "bisbom-java-testapp",
  "language": "java",
  "commit_sha": "0a1b2c3d4e5f60718293a4b5c6d7e8f901234567",
  "vcs_uri": "https://github.com/tedg-dev/bisbom-java-testapp.git",
  "build_id": "2026-06-29_2312",
  "source_manifest": "phase1_manifest.json",
  "sboms": [
    {
      "artifact": {
        "name": "bisbom-java-testapp-1.0.0.jar",
        "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "gitoid": "gitoid:blob:sha256:a94a8fe5ccb19ba61c4c0873d391e987982fbbd3"
      },
      "build": {
        "path": "bisbom-java-testapp-1.0.0_build.spdx.json",
        "sha256": "b1946ac92492d2347c6235b4d2611184a1b2c3d4e5f60718293a4b5c6d7e8f90",
        "gitoid": "gitoid:blob:sha256:2ef7bde608ce5404e97d5f042f95f89f1c232871"
      },
      "analyzed": {
        "path": "bisbom-java-testapp-1.0.0_analyzed.spdx.json",
        "sha256": "c2c53d66948214258a26ca9ca845d7ac0c17f8e7a5f2b3c4d5e6f708192a3b4c",
        "gitoid": "gitoid:blob:sha256:3f786850e387550fdab836ed7e6dc881de23001b"
      }
    }
  ]
}
```

The digest values above are illustrative, not real.

---

## Digest conventions

Two digests are provided for every referenced file so the delivery team can
choose either verification scheme:

- **`sha256`** — plain SHA-256 over the file bytes, lowercase hex. Verify with
  any standard tool (e.g. `sha256sum`).
- **`gitoid`** — OmniBOR GitOID (Artifact ID), SHA-256 flavor, in canonical
  IRI form `gitoid:blob:sha256:<hex>`. Computed as SHA-256 over the git blob
  encoding `"blob " + <byte-length> + "\0" + <content>`, matching the existing
  Phase 1 gitoid computation (`_sha256_gitoid` in `app/pipeline/manifest.py`).

The **JAR (`artifact`) digests are sourced from the Phase 1 metadata**
(`phase1_manifest.json` records binary paths and gitoids), so Phase 2 does
**not** re-read the build workspace to compute them. The **SBOM file digests**
are computed over the files Phase 2 itself just wrote.

> Note: `phase1_manifest.json` stores gitoids as bare hex internally. This
> external contract uses the canonical `gitoid:blob:sha256:<hex>` prefixed form
> for clarity and OmniBOR alignment.

---

## Guarantees

- **Self-consistent** — every path in the manifest is relative to the manifest,
  and every referenced file exists at its stated path.
- **No source-tree reads** — the set is produced solely from Phase 1 metadata,
  consistent with `#11003`. Nothing is read from the build workspace.
- **Deterministic naming** — filenames derive from the JAR stem; the manifest
  fully enumerates the set (no directory scanning required by the consumer).
- **Tamper-evident** — digests let any consumer verify integrity independently.

---

## Consuming the output (any downstream)

These steps read only the Phase 2 output; they are the same regardless of the
consumer. Corona is used below purely as an example.

1. Read `sbom_handoff_manifest.json` from the run directory.
2. Check `version` is a supported major.
3. For each `sboms[]` entry, resolve `build.path` / `analyzed.path` relative to
   the manifest and verify `sha256` (or `gitoid`).
4. Bind each SBOM pair to its `artifact` via the artifact `gitoid` / `sha256`.
5. (Consumer-specific, **not** Phase 2) e.g. file under Corona's Product /
   Release / Image model using `repo_name`, `commit_sha`, and `build_id` —
   this mapping is owned by the consumer, not by Phase 2.

---

## Explicitly out of scope

- **How and where Phase 2 runs** — the wrapper environment (Corona, a build
  host, a container, the test-app harness) is a separate secondary concern.
- The Corona intake mechanism (S3 bucket vs API) and its data model.
- Product / Release / Image pathing inside Corona.
- Authentication / authorization to any consumer.
- Network transport, upload client, retry / delivery semantics.
- Cryptographic signing of the manifest (may be added in a later contract
  version if a consumer requires it — see open questions).
- Non-Java languages (tracked under shared SI-5).

---

## Open questions for consuming teams

- **Schema field names** — does a consumer (e.g. Corona) already expect a
  specific manifest shape or field naming? If so, we align to it before
  implementing.
- **Signing** — should the manifest carry a detached signature? Signing is
  currently out of scope.
- **Artifact co-delivery** — should the JARs be referenced by digest only
  (current assumption), or co-located with the SBOM set? (A delivery/wrapper
  concern, not Phase 2 generation.)
- **Build id source** — what should populate `build_id` (CI run id, release
  tag, image digest)? It is config-driven on our side.
- **Multi-module grouping** — is a flat `sboms[]` list sufficient, or is
  module/parent grouping metadata wanted?

---

## Relationship to `#11003`

`#11003` (A1) made Phase 2 **generate** the Java SBOM set from Phase 1 metadata
without the source tree. This contract (A2 / `#11004`) makes Phase 2
**describe** that generated set with a consumer-agnostic output manifest. Both
are squarely within Phase 2 = SBOM generation; neither concerns how the
output is transported or where Phase 2 runs.
