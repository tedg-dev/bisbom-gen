---
description: Every built artifact's SPDX package MUST carry its OmniBOR Artifact ID and checksum
---

# Artifact Identity Requirement (OmniBOR Core)

Recording the OmniBOR Artifact ID (GitOID) of the built artifact is the
**entire point** of OmniBOR. An SBOM that describes a binary but omits that
binary's own Artifact ID has failed its core purpose. This rule is
**language-agnostic** and applies to every current and future language
implementation (C/C++, Go, Rust, Java, and any added later).

## The Rule

For **every** SPDX document we emit (`_build` and `_analyzed`, standalone and
sidecar), the **root / target-artifact package** — the package that represents
the thing the build produced (executable, shared library, JAR, wheel, module,
etc.) — MUST include **both**:

1. **A checksum** in the SPDX `checksums` array, using the digest algorithm
   the tracer actually computed (e.g. `SHA1` for the bomsh treedb).
2. **An OmniBOR GitOID** as an SPDX `externalRefs` entry:

   | Field | Value |
   |-------|-------|
   | `referenceCategory` | `PERSISTENT-ID` |
   | `referenceType` | `gitoid` |
   | `referenceLocator` | `gitoid:blob:<algo>:<hex>` |

The `<algo>` in the GitOID locator MUST match the flavor the treedb computed
(`sha1` for the current bomsh treedb). Do NOT invent a digest we did not
actually compute.

## Data Source (do not re-hash the workspace)

The identity is already computed by the tracer — never re-read the build
workspace to recompute it. Pull it from the established sources:

- **Checksum / GitOID key** — the artifact's digest is the treedb key in
  `bomsh_omnibor_treedb`.
- **GitOID value** — the `sha1 -> omnibor doc id` map in
  `bomsh_omnibor_doc_mapping`, exposed via `AdgParser.load_doc_mapping()`.

The C/C++ emitter is the reference implementation of this pattern
(`app/spdx/emitter.py`, root-package construction): it appends the GitOID
`externalRef` and the `SHA1` checksum to the target-binary package. Every
other language emitter MUST do the same for its produced artifact(s).

## Why This Exists

The Java generator originally emitted only a `purl` on the root JAR package
and dropped the JAR's own SHA1/GitOID, even though both were sitting in the
treedb and `doc_mapping`. Source/class files carried checksums but the
**produced artifact did not** — omitting the one identifier OmniBOR exists to
provide. This rule prevents that class of omission in any language.

## Enforcement

- **Every language emitter** MUST attach checksum + GitOID to its produced
  artifact package(s). A missing checksum or GitOID on a root artifact package
  is a **critical correctness failure**, not a cosmetic gap.
- **Every language's test suite** MUST include a regression test asserting the
  root artifact package has a non-empty `checksums` array AND a `gitoid`
  `externalRef`.
- When adding a new language (see `project/supported-languages.md`), this
  requirement is part of "done" — an emitter is not complete without it.

## Golden Files

Adding artifact identity to an emitter that lacked it WILL change that
language's golden SPDX files. Follow `cascade/golden-file-policy.md`: report
every diff, never auto-update, wait for USER approval.
