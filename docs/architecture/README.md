# Architecture Documentation

General application architecture and technical documentation. For
sidecar-specific design and per-language build interception diagrams,
see [docs/sidecar/](../sidecar/).

## Pipeline Overview

[![Build-Interception SBOM Generation Workflow](https://raw.githubusercontent.com/tedg-dev/bisbom-gen/main/docs/architecture/bisbom-gen-workflow.png)](https://github.com/tedg-dev/bisbom-gen/blob/main/docs/architecture/bisbom-gen-workflow.png)

> **Click to view full size.** Shows the complete pipeline:
> clone → build → instrument → SPDX generation → visualization.

## Technical Documentation

| Document | Description |
|----------|-------------|
| [Technical Overview](technical-overview.md) | High-level system overview for stakeholders |
| [App Architecture](app-architecture.md) | Pipeline structure, module dependencies, data flow |
| [Standalone Mode](standalone-mode.md) | Deprecated ptrace-based mode (initial implementation; ~1% embedded corner case only) |
| [Platform Support](platform-support.md) | Supported OSes, architectures, container requirements |
| [Analyzed vs Build SBOMs](analyzed-vs-build-sboms.md) | CISA SBOM types and two-file approach rationale |
| [Stable Tag Pinning](stable-tag-pinning.md) | Repo version pinning policy |
| [Vendored Version Detection](vendored-version-detection.md) | Vendored dependency version detection |

## Diagram Sources

All diagrams are maintained as draw.io XML files (`.drawio`). To edit:

1. Open the `.drawio` file in [draw.io](https://app.diagrams.net/) or the desktop app
2. Make changes
3. Export as PNG with the same filename
4. Commit both `.drawio` and `.png` files
