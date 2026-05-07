# SPDX `filesAnalyzed` Semantics

The current behavior is correct per the SPDX 2.3 specification (§7.8). Here's why:

## What `filesAnalyzed` means

Per SPDX 2.3, `filesAnalyzed` indicates whether the files within a package were actually analyzed and enumerated in the SPDX document:

- **`true`** — we inspected the package contents, and the `files` section lists what we found
- **`false`** — we know the package exists but did NOT inspect its contents

## What's in the SPDX output

| Package | `filesAnalyzed` | Why |
|---------|----------------|-----|
| **jsoup** (root JAR) | `true` | bomsh traced JAR→class→source provenance. The 500+ files in the `files` section belong to this package. |
| **jspecify** (dependency) | `false` | Discovered via `mvn dependency:tree`. We know it's a dependency but never opened the jspecify JAR to inspect its contents. |
| **re2j** (dependency) | `false` | Same — declared dependency from Maven, not analyzed. |

This is the correct semantic distinction. We **built and analyzed** jsoup (traced every `.java` → `.class` file). We did **not** analyze the third-party dependency JARs — we only know they exist because Maven's dependency graph told us.

Setting `filesAnalyzed: true` on jspecify/re2j would be a **spec violation** — it would claim we analyzed files we never looked at.

## Industry Standard Practice

This is the norm across SPDX tooling (Syft, Trivy, CycloneDX generators, etc.):

- **`filesAnalyzed: true`** for packages **you built** (you have source provenance)
- **`filesAnalyzed: false`** for packages **you consumed** (declared dependencies from a package manager)

Dependency JARs from Maven Central are identified by their GAV coordinates (groupId:artifactId:version) and PURL — that's sufficient for vulnerability tracking, license compliance, and supply chain auditing. Nobody cracks open every transitive JAR to enumerate `.class` files.

If a consumer needs file-level analysis of jspecify or re2j, they analyze those projects independently with their own SPDX documents. That's what SPDX `ExternalDocumentRef` is designed for — linking to a dependency's own SBOM rather than duplicating the analysis.
