# Sidecar and Phase Isolation

All documentation for sidecar-based build interception and phase
isolation lives here. General (cross-language) documents are at the
root; language-specific documents are in subdirectories.

## General Documents

| Document | Description |
|---|---|
| [infrastructure.md](infrastructure.md) | Sidecar phase-isolation infrastructure design |
| [strategy-evaluation.md](strategy-evaluation.md) | Sidecar strategy evaluation and comparison |
| [async-spdx-architecture.md](async-spdx-architecture.md) | Async SPDX generation architecture |
| [cicd-workspace-lifecycle.md](cicd-workspace-lifecycle.md) | CI/CD workspace lifecycle for phase isolation |
| [phase-isolation-gap-analysis.md](phase-isolation-gap-analysis.md) | Gap analysis for phase isolation |
| [phase2-consume-dep-capture.md](phase2-consume-dep-capture.md) | Phase 2 dependency capture consumption design |
| [phase2-binary-artifact-deps.md](phase2-binary-artifact-deps.md) | Phase 2 binary artifact dependencies |
| [phase-isolation-system-test.md](phase-isolation-system-test.md) | Phase isolation system test documentation |
| [phase-isolation-cicd-results.md](phase-isolation-cicd-results.md) | Phase isolation CI/CD test results |
| [ebpf-investigation.md](ebpf-investigation.md) | eBPF investigation report |
| [ebpf-and-bpf.md](ebpf-and-bpf.md) | eBPF and BPF in OmniBOR |

## General Diagrams

| Diagram | Description |
|---|---|
| [sidecar-target-architecture](sidecar-target-architecture.png) | Target sidecar architecture |
| [sidecar-standalone-architecture](sidecar-standalone-architecture.png) | Standalone vs sidecar architecture |
| [sidecar-strategy-pattern](sidecar-strategy-pattern.png) | Strategy pattern for sidecar selection |
| [sidecar-critical-path](sidecar-critical-path.png) | Critical path analysis |
| [sidecar-dependency-graph](sidecar-dependency-graph.png) | Sidecar dependency graph |
| [strategy-selection-decision-tree](strategy-selection-decision-tree.png) | Strategy selection decision tree |
| [phase-isolation-ci-cd](phase-isolation-ci-cd.png) | Phase isolation CI/CD integration |
| [sidecar-two-phase-corona](sidecar-two-phase-corona-p1.png) | Two-phase Corona handoff |

## Language-Specific

| Language | Directory | Canonical Design Doc |
|---|---|---|
| **Java** | [java/](java/) | [java/sidecar-design.md](java/sidecar-design.md) |
| **C/C++** | [c-cpp/](c-cpp/) | [c-cpp/sidecar-design.md](c-cpp/sidecar-design.md) |
| **Go** | [go/](go/) | [go/sidecar-design.md](go/sidecar-design.md) |
| **Rust** | [rust/](rust/) | [rust/sidecar-design.md](rust/sidecar-design.md) |
| **Python** | [python/](python/) | [python/sidecar-design.md](python/sidecar-design.md) |
