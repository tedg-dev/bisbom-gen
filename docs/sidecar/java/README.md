# Java Sidecar

All Java-specific sidecar and phase isolation documentation.

## Design Documents

Peer- and user-facing documents. Read these first.

| Document | Description |
|---|---|
| [sidecar-design.md](sidecar-design.md) | **Canonical** Java sidecar design (read this first) |
| [enterprise-sbom.md](enterprise-sbom.md) | Java build-based SBOM for enterprise |
| [phase2-handoff-contract.md](phase2-handoff-contract.md) | Phase 1 → Phase 2 artifact-set + manifest contract (peer delivery team) |

## Reference (detailed)

Deep-detail design, decision, and reference material — consult when you need
to refresh the rationale behind a decision. Lives in [`reference/`](reference/).

| Document | Description |
|---|---|
| [reference/gradle-dependency-capture.md](reference/gradle-dependency-capture.md) | Gradle dependency-graph capture mechanism, version matrix, and fixtures |
| [reference/inline-hashing-explained.md](reference/inline-hashing-explained.md) | Inline-hashing design proof with four diagrams |
| [reference/inline-hashing-interception-design.md](reference/inline-hashing-interception-design.md) | Inline-hashing interception design of record |
| [reference/phase1-build-speed-design.md](reference/phase1-build-speed-design.md) | Phase 1 build speed optimization design |
| [reference/nonmaven-gradle-adapter.md](reference/nonmaven-gradle-adapter.md) | Non-Maven/Gradle build tool adapter design |
| [reference/dependency-check-modules.md](reference/dependency-check-modules.md) | Dependency-check module dependency structure |

## Diagrams

| Diagram | Description |
|---|---|
| [java-build-interception](java-build-interception.png) | Phase 1 sidecar build interception flow |
| [java-sbom-phase-split](java-sbom-phase-split.png) | Phase 1 / Phase 2 split |
| [java-sbom-cicd-integration](java-sbom-cicd-integration.png) | CI/CD integration |
| [java-sbom-corona-handoff](java-sbom-corona-handoff.png) | Corona handoff flow |

The `java-inline-*` diagrams that accompany the inline-hashing docs live in
[`reference/`](reference/) alongside those documents.

## Key Facts

- Java sidecar does **NOT** use strace (standalone mode only)
- Your Java build (`mvn package` / `gradle build`) and build scripts (`pom.xml` / `build.gradle`) are **unchanged**
- Phase 1 metadata capture is **added to your existing CI/CD build step** — no new pipeline steps, no build modifications
- No strace, no `SYS_PTRACE`, no privileged container
- All metadata capture is **post-build**:

  1. `bomsh_create_bom_java.py` scans `.class` `SourceFile` attributes
  2. `mvn dependency:tree` / `gradlew dependencies` captures the dep graph
