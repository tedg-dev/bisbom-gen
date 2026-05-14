# Architecture Documentation

This directory contains architecture diagrams and technical documentation for the omnibor-analysis project.

## Pipeline Overview

[![OmniBOR Analysis Workflow](https://raw.githubusercontent.com/tedg-dev/omnibor-analysis/main/docs/architecture/omnibor-analysis-workflow.png)](https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/architecture/omnibor-analysis-workflow.png)

> **Click to view full size.** Shows the complete analysis pipeline: clone → build → instrument → SPDX generation → visualization.

## Build Interception Diagrams

These diagrams show how OmniBOR/bomsh intercepts the build process for each supported language and generates SPDX SBOMs.

| C/C++ | Rust |
|:-----:|:----:|
| [![C/C++ Build Interception](https://raw.githubusercontent.com/tedg-dev/omnibor-analysis/main/docs/architecture/c-cpp-build-interception.png)](https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/architecture/c-cpp-build-interception.png) | [![Rust Build Interception](https://raw.githubusercontent.com/tedg-dev/omnibor-analysis/main/docs/architecture/rust-build-interception.png)](https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/architecture/rust-build-interception.png) |
| bomtrace3 (strace-based) | bomtrace2 (ptrace-based) |

| Go | Java |
|:--:|:----:|
| [![Go Build Interception](https://raw.githubusercontent.com/tedg-dev/omnibor-analysis/main/docs/architecture/go-build-interception.png)](https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/architecture/go-build-interception.png) | [![Java Build Interception](https://raw.githubusercontent.com/tedg-dev/omnibor-analysis/main/docs/architecture/java-build-interception.png)](https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/architecture/java-build-interception.png) |
| bomtrace2 + bomtrace_go.conf | strace + post-build analysis |

> **Click any diagram to view full size.**

## Technical Documentation

| Document | Description |
|----------|-------------|
| [Technical Overview](technical-overview.md) | High-level system overview for stakeholders |
| [App Architecture](app-architecture.md) | Pipeline structure, module dependencies, data flow |
| [Standalone Mode](standalone-mode.md) | Legacy ptrace-based mode (golden files, isolated builds) |
| [Platform Support](platform-support.md) | Supported OSes, architectures, container requirements |
| [Analyzed vs Build SBOMs](../features/analyzed-vs-build-sboms.md) | CISA SBOM types and two-file approach rationale |
| [Phase Isolation](../features/phase-isolation/sidecar-phase-isolation-infrastructure.md) | Sidecar two-phase architecture (baseline) |

## Diagram Sources

All diagrams are maintained as draw.io XML files (`.drawio`) in this directory. To edit:

1. Open the `.drawio` file in [draw.io](https://app.diagrams.net/) or the desktop app
2. Make changes
3. Export as PNG with the same filename
4. Commit both `.drawio` and `.png` files
