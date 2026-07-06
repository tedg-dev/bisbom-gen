# Java Sidecar

All Java-specific sidecar and phase isolation documentation.

## Design Documents

| Document | Description |
|---|---|
| [sidecar-design.md](sidecar-design.md) | **Canonical** Java sidecar design (read this first) |
| [phase1-build-speed-design.md](phase1-build-speed-design.md) | Phase 1 build speed optimization design |
| [enterprise-sbom.md](enterprise-sbom.md) | Java build-based SBOM for enterprise |
| [nonmaven-gradle-adapter.md](nonmaven-gradle-adapter.md) | Non-Maven/Gradle build tool adapter design |
| [dependency-check-modules.md](dependency-check-modules.md) | Dependency-check module dependency structure |

## Diagrams

| Diagram | Description |
|---|---|
| [java-build-interception](java-build-interception.png) | Phase 1 sidecar build interception flow |
| [java-sbom-phase-split](java-sbom-phase-split.png) | Phase 1 / Phase 2 split |
| [java-sbom-cicd-integration](java-sbom-cicd-integration.png) | CI/CD integration |
| [java-sbom-corona-handoff](java-sbom-corona-handoff.png) | Corona handoff flow |

## Key Facts

- Java sidecar does **NOT** use strace (standalone mode only)
- Build runs **unmodified** — no strace prefix, no `SYS_PTRACE`
- All metadata capture is **post-build**:

  1. `bomsh_create_bom_java.py` scans `.class` `SourceFile` attributes
  2. `mvn dependency:tree` / `gradlew dependencies` captures the dep graph
