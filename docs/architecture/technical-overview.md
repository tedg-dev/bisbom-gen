# Build-Interception SBOM Generation: Technical Overview

> Also referred to by its short name, **bisbom-gen**.

## 1. How Build Interception Works

**bisbom-gen** intercepts compiler/linker invocations during the build to
create an **Artifact Dependency Graph (ADG)** — a cryptographic record of
every input→output relationship.

### Artifact Identity — gitOID + SHA-256

Every artifact (leaf source files, intermediate objects, and built
packages) carries two distinct `SHA-256` values, plus a third for built
packages:

| Value | What | Applies to |
|-------|------|------------|
| **raw hash** | `SHA-256` of the file bytes | files, objects, packages |
| **artifact gitOID** | `gitoid:blob:sha256` (git-blob framing + `SHA-256`) | files, objects, packages |
| **Input Manifest gitOID** | gitOID of the Input Manifest (provenance identifier) | built packages only |

All artifact identity uses `SHA-256`. The **topology** of the ADG (which
inputs feed which output) is captured during build interception per
language, but the **identity** values are computed by bisbom-gen
uniformly across all languages — so the interception layer's internal
`SHA-1` values never surface in the SBOM. This is the design of record;
see `.windsurf/rules/project/artifact-identity.md`.

**Sidecar is the only supported execution mode** (no `SYS_PTRACE`
required), used for all enterprise CI/CD SBOM generation and as the
golden-file baseline:

| Mode | Mechanism | Requires `SYS_PTRACE` | Status |
|------|-----------|:---------------------:|--------|
| **Sidecar** | Language-specific strategies (dep:tree, `-toolexec`, `RUSTC_WRAPPER`, `LD_PRELOAD`) | No | **Supported (only mode)** |
| **Standalone** | `bomtrace3`/`bomtrace2` ptrace-based tracing | Yes | **Deprecated** — initial implementation; ~1% embedded corner case only |

### Sidecar Mode — Per-Language Strategies

| Language | Strategy | What's Captured |
|----------|----------|-----------------|
| **Java** | `MavenDepTreeStrategy` / `GradleDepTreeStrategy` | Maven/Gradle dependency graph, `.java` → `.class` → JAR |
| **C/C++** | `CC=` compiler wrapper (planned) | Every `.c`/`.h` → `.o` → binary relationship |
| **Go** | `-toolexec` wrapper (planned) | Module compilation, stdlib inclusion |
| **Rust** | `RUSTC_WRAPPER` (planned) | Crate compilation, `rustc` invocations |

For the deprecated standalone mode (embedded corner case only), see
[Standalone Mode](standalone-mode.md).

---

## 2. bisbom-gen Integration

**bisbom-gen** wraps build-interception tooling into a reproducible
two-phase pipeline:

- **Phase 1 (Build Interception)** — runs in the customer's build
  environment, produces build artifacts + `phase1_manifest.json`
- **Phase 2 (SPDX Generation)** — runs in a separate environment,
  reads the manifest, generates SPDX SBOMs

| Component | Source | Role |
|-----------|--------|------|
| `app/pipeline/facade.py` | bisbom-gen | Pipeline orchestration |
| `app/pipeline/manifest.py` | bisbom-gen | Phase 1/2 manifest + gitoid verification |
| `app/spdx/generator.py` | bisbom-gen | ADG → enriched per-binary SPDX |
| `app/spdx/java_generator.py` | bisbom-gen | Java: dep:tree → SPDX |
| `app/version_detection/` | bisbom-gen | Root version + 12 vendored detection strategies |
| `app/spdx_visualize.py` | bisbom-gen | SPDX → interactive D3.js HTML |

**Environment:** Docker container (Ubuntu 22.04 x86_64). Sidecar mode
does not require `SYS_PTRACE`.

For the full phase isolation architecture, see
[Sidecar Phase Isolation Infrastructure](../sidecar/infrastructure.md).

---

## 3. Why Two SPDX Files: Analyzed vs. Build (CISA Taxonomy)

Per CISA's [SBOM Types](https://www.cisa.gov/sbom) guidance, different consumers need different views:

| SPDX Type | Contents | Use Case |
|-----------|----------|----------|
| **Analyzed** | Only statically linked / vendored components embedded in the binary | Vulnerability scanning of shipped artifact |
| **Build** | Analyzed + dynamic libraries + build tools (compilers, Maven plugins) | Full provenance for reproducibility audits |

**Relationship types used:**
- `STATIC_LINK` — vendored/compiled-in dependencies
- `DYNAMIC_LINK` — runtime shared libraries (`.so` files)
- `BUILD_TOOL_OF` — compilers, build plugins (e.g., Maven `provided` scope)
- `DEPENDS_ON` — Java/Go module dependencies
- `CONTAINS` — source files within a package

---

## 4. Visualization: Data Sources & Benefits

Each HTML visualization is a **force-directed D3.js graph** showing the binary's dependency structure.

### Data Sources by Language

| Element | C/C++ | Rust | Go | Java |
|---------|-------|------|-----|------|
| **Node names** | dpkg package name or vendored dir | Crate name from Cargo.lock | Module path from go.sum | Maven artifactId from pom.xml |
| **Versions** | dpkg-query or VERSION file detection | Cargo.lock | go.sum | pom.xml / dependency:tree |
| **Relationships** | ADG (static) + ldd (dynamic) | ADG (all STATIC_LINK) | ADG + go.sum classification | ADG + mvn dependency:tree |
| **File counts** | CONTAINS relationships in SPDX | CONTAINS | CONTAINS | CONTAINS |

### Visual Encoding

- **Node color** — depth in dependency tree (purple=root, teal=direct, blue=transitive)
- **Node size** — number of source files (CONTAINS count)
- **Edge color** — relationship type (teal=STATIC, red=DYNAMIC, yellow=BUILD_TOOL)
- **Special rings** — orange dashed = vendored; purple solid = sibling module (Java multi-module)

### Benefits

1. **Immediate comprehension** of dependency depth and complexity
2. **Click-to-highlight** isolates a component's upstream/downstream
3. **Search** locates specific packages instantly
4. **Legend** quantifies relationship types at a glance
5. **Hover tooltips** show version, file count, and package URL

---

## 5. Architecture Diagram

See: [bisbom-gen-workflow.png](https://github.com/tedg-dev/bisbom-gen/blob/main/docs/architecture/bisbom-gen-workflow.png)

Pipeline visualization showing:
- AWS EC2 + Docker container environment
- Build interception flow
- ADG generation → SPDX generation → HTML visualization
- Output artifacts (analyzed + build SPDX JSON/HTML per binary)

---

*Document version: June 2026*
