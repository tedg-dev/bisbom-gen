# OmniBOR Analysis — Meeting Agenda

## Overview

**OmniBOR** intercepts compiler/linker calls during build via ptrace to create cryptographically-linked Artifact Dependency Graphs (ADGs). **omnibor-analysis** wraps these tools into an automated pipeline that generates per-binary SPDX 2.3 SBOMs with interactive visualizations.

## Topics

1. **Build Interception by Language**
   - C/C++: bomtrace3 (patched strace) → gcc/g++/ld tracking
   - Rust/Go: bomtrace2 → cargo/go build interception
   - Java: strace + javap → JAR/class file mapping + Maven deps

2. **Pipeline Flow**
   ```
   Clone → Validate deps → bomtrace build → ADG → SPDX → Visualize
   ```

3. **Visualization Demo**
   - Force-directed D3.js graph per binary
   - Color-coded by dependency depth and relationship type
   - Click-to-highlight, search, tooltips

4. **Architecture Walkthrough**
   - [View diagram](https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/architecture/omnibor-analysis-workflow.png)

## Resources

- [Technical Overview](https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/architecture/omnibor-analysis-technical-overview.md)
- [Architecture Diagram](https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/architecture/omnibor-analysis-workflow.png)
- Sample visualization HTML (optional)
