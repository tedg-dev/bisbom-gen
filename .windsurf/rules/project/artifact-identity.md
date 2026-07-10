---
description: Every artifact's SPDX identity MUST carry its OmniBOR gitOID (SHA-256) and a valid raw SHA. Design of record.
---

# Artifact Identity (OmniBOR Core) — Design of Record

Recording the OmniBOR identity of **every** artifact is the entire point of
OmniBOR. This rule is the **design of record** and supersedes any earlier
statement (in this file or elsewhere) that the SPDX checksum is the bomsh
`SHA1` treedb value, or that we must not re-hash artifacts. Both were mistakes
and are corrected below.

This rule is **language-agnostic**: it applies to every current and future
language (C/C++, Go, Rust, Java, Python, and any added later).

## 1. Principle: Capture Once, Render Per SPDX Version

We compute the full identity for every artifact — leaf source files,
intermediate objects (`.o`, `.class`), and built packages (executable, shared
library, JAR, wheel, module) — and store it in a version-agnostic model. A
per-version renderer emits whatever the target SPDX version supports. SPDX
3.0.1 is the end-goal; SPDX 2.3 is the current output.

## 2. The Three Identity Values

Every artifact carries up to three distinct values — different things, not
alternate encodings of one value:

| Value | Definition | Applies to |
|---|---|---|
| **raw hash** | `SHA-256` of the raw file content | files, objects, packages |
| **artifact gitOID** | `gitoid:blob:sha256` of the artifact (git-blob framing + `SHA-256`) | files, objects, packages |
| **Input Manifest gitOID (OMID)** | gitOID of the OmniBOR Input Manifest — the provenance identifier | built artifacts (packages) only |

The raw hash and the artifact gitOID are **not** the same number: the gitOID
prepends the git object header (`blob <len>\0`) before hashing. NEVER store the
gitOID under a `SHA` checksum label — that was the original bug.

## 3. Hash Algorithm: SHA-256, With Agility

`SHA-256` is **mandated**, not merely preferred:

- The OmniBOR specification permits **only** `SHA-256` for Artifact IDs.
- NIST has formally retired `SHA-1`; full transition away is required by 2030,
  and `SHA-1` is disallowed for new signatures now.
- git's `SHA-1` is actually `SHA-1DC` (collision-detecting), which breaks the
  universal reproducibility OmniBOR requires.

The identity model MUST be **parameterized by hash algorithm** (default
`SHA-256`), never hardcoded, so a future migration (e.g. if `SHA-256` is
broken) is a config change — mirroring OmniBOR's own `HashAlgorithm` design.

## 4. Topology vs Identity — Why C/C++ Is Automatic and Java Isn't

The asymmetry between languages lives **only** in bomsh's hashing step, not in
whether the dependency graph can be captured:

| | C/C++ | Java |
|---|---|---|
| **Interception** | `bomtrace3` (syscall-level) sees every `gcc`/`ld` call and its exact inputs/outputs | `bomsh_create_bom_java.py` uses `strace` of `javac` + JAR packaging |
| **bomsh ID computation** | `bomsh_create_bom.py` supports `--hashtype sha256` natively | `SHA-1` only; no `--hashtype` |

The fix is to **separate topology from identity**:

- **Topology (edges: output ← inputs)** — language-specific, and bomsh already
  produces it for every language (`bomtrace3` for C, `strace` for Java,
  `bomtrace2` for Go/Rust). We keep using bomsh for this.
- **Identity (`SHA-256` gitOIDs + raw hashes + Input Manifests)** — pure,
  language-agnostic computation. We lift it **out** of bomsh into our own layer
  and compute it uniformly.

Once identity is our responsibility, bomsh's per-language `--hashtype` support
is irrelevant and Java becomes as automatic as C:

1. Take bomsh's captured topology (Java: `strace` `.java`→`.class`→`.jar`, plus
   Maven/Gradle `dep:tree` for external deps). The treedb maps `sha1 → path`.
2. For every node, read the file at its path and compute `gitoid:blob:sha256`
   and the raw `SHA-256`.
3. Build each built artifact's Input Manifest per the OmniBOR spec and compute
   its OMID as the `SHA-256` git-blob of that manifest, re-keying bomsh's
   `SHA-1` nodes to our `SHA-256` IDs by joining on file path.

bomsh's `SHA-1` treedb is used **only** as a topology bridge and never surfaces
in the SBOM.

### 4.1 Java-Specific Requirements

- **Hash while intermediates exist.** `.class`/`.o` files must be hashed during
  or immediately after the instrumented build, before workspace cleanup —
  intermediates are not collected into offline Phase 2 today.
- **Validate topology completeness.** `strace`-based Java capture is more
  fragile than `bomtrace3`; every `.class` in the JAR must trace back to a
  `.java`. Flag gaps rather than emit a silently-incomplete manifest.
- **Maven/Gradle dependencies are leaves.** We did not build them; identify
  them by their JAR's artifact gitOID (+ `purl`). This is correct OmniBOR
  behavior for externally-built artifacts.

## 5. Per-Version SPDX Rendering

| Artifact | SPDX 2.3 (current) | SPDX 3.0.1 (end-goal) |
|---|---|---|
| **File / object** | `checksums: [SHA-1 raw (spec-mandated), SHA-256 raw]`; per-file gitOID has no native slot, retained in the model | `verifiedUsing: [SHA-256]` + `contentIdentifier: gitoid:blob:sha256` |
| **Built package** | `checksums: [SHA-256 raw]` + `externalRefs: [gitoid = OMID]` | `verifiedUsing: [SHA-256]` + `contentIdentifier: gitoid` + `externalIdentifier: gitoid = OMID` |

SPDX 3.0.1 authority (`ContentIdentifierType`): gitOIDs on artifacts
(File/Snippet/Package) go in `contentIdentifier`; the Input Manifest gitOID
(OMID) goes in `externalIdentifier`.

### 5.1 SPDX 2.3 File SHA-1 Mandate (Spec Conformance, Not Identity)

SPDX 2.3 **requires** every `File` to carry exactly one raw `SHA-1`
checksum (Clause 8.4, Table 39: cardinality `1..1` for SHA1, `0..*` for
all other algorithms). This is enforced by every conformant validator
(e.g. the `spdx-tools` `validate_full_spdx_document`) and by the Go
`tools-golang` model. A `File` with only `SHA-256` is **not** valid
SPDX 2.3.

Therefore, for SPDX 2.3 output, File entries emit **both** the
spec-mandated raw `SHA-1` **and** the raw `SHA-256` identity hash. The
raw `SHA-1` is a legacy corruption-detection checksum (RFC 3174 hash of
the file bytes, what `sha1sum` produces) — it is **NOT** an identity
value, **NOT** a git-blob value, and **NOT** the mislabeled gitOID that
§7 corrects. Artifact identity remains `SHA-256` (raw + gitOID)
everywhere.

**Packages** carry no such mandate (Clause 7.10, Table 22: Required No,
cardinality `0..*`), so built-package `checksums` stay `SHA-256`-only
plus the gitOID `externalRef`.

SPDX 3.0.1 removes the File SHA-1 mandate entirely — `verifiedUsing`
accepts `sha256` alone (the official 3.0.1 example verifies both files
and packages with `sha256` only). So the SHA-1 File entry is **dropped**
when we render 3.0.1; the SHA-256 raw + gitOID values are reused
unchanged. This is why the SHA-1 lives in a dedicated SPDX-2.3-only
helper (`spdx_2_3_file_checksums`) and never in the identity layer.

SPDX 2.3 constraint: the checksum `algorithm` enum has no gitoid, and
files cannot carry `externalRefs` — so a per-file gitOID is retained in
the model and surfaced only when we move to 3.0.1.

## 6. Data Sources

- **Edges/topology** — bomsh treedb (`bomsh_omnibor_treedb`, `sha1 → path`),
  raw logfile, `strace` log, and Maven/Gradle `dep:tree`.
- **Identity** — **we compute it** by reading each artifact once (git-blob
  `SHA-256` + raw `SHA-256`). This **reverses** the earlier "do not re-hash the
  workspace" instruction: re-hashing in `SHA-256` is required because bomsh's
  treedb is `SHA-1` and cannot supply the mandated algorithm.
- **OMID** — the OmniBOR Input Manifest, computed canonically per the OmniBOR
  spec (validated against the reference libraries), not read from bomsh's
  `SHA-1` doc-mapping.

## 7. History of the Bug This Corrects

Two distinct mistakes were made and are corrected by this rule:

1. The Java generator originally emitted only a `purl` on the root JAR and
   dropped the JAR's own identity entirely.
2. Once identity was added, every language stored the bomsh `SHA-1` **git-blob**
   value under a `"SHA1"` checksum label on files and packages. That value is
   the artifact's gitOID, **not** its raw `SHA-1` — a consumer verifying the
   checksum gets a mismatch. The raw hash was never stored, and the gitOID was
   `SHA-1` rather than the OmniBOR-mandated `SHA-256`.

## Enforcement

- **Every language emitter** MUST attach, to every artifact it emits, a valid
  raw `SHA-256`, and (for built packages) the OMID gitOID; per-file artifact
  gitOIDs are retained for 3.0.1. A built package without identity is a
  **critical correctness failure**, not a cosmetic gap.
- **Every language's test suite** MUST assert the built-artifact package has a
  non-empty `checksums` (raw `SHA-256`) AND a `gitoid` `externalRef`, and that
  file entries carry a valid raw `SHA-256` (never a git-blob value). For SPDX
  2.3 output, file entries MUST also carry the spec-mandated raw `SHA-1`
  (see §5.1); this SHA-1 is dropped when rendering SPDX 3.0.1.
- The `SHA-256` identity layer is language-agnostic and shared — do not
  reimplement it per language.
- When adding a new language (see `project/supported-languages.md`), this
  requirement is part of "done" — an emitter is not complete without it.

## Golden Files

Moving from `SHA-1` git-blob values to raw `SHA-256` + `SHA-256` gitOIDs WILL
change every language's golden SPDX. Follow `cascade/golden-file-policy.md`:
report every diff, never auto-update, wait for USER approval.

## Implementation Status

The raw `SHA-256` + `SHA-256` gitOID identity model is **implemented** across
the C/C++ and Java emitters: built packages carry a raw `SHA-256` checksum and
their `SHA-256` gitOID `externalRef`; file entries carry a raw `SHA-256` (plus
the SPDX 2.3-mandated raw `SHA-1`, see §5.1). The bomsh `SHA-1` treedb is used
only as a topology bridge and is never surfaced in the SBOM.

Still pending: the Input Manifest gitOID (OMID) canonical computation per the
OmniBOR spec, and the SPDX 3.0.1 renderer (`verifiedUsing` + `contentIdentifier`,
no SHA-1). Golden SPDX regeneration for the identity change is sequenced under
USER review per `cascade/golden-file-policy.md`.
