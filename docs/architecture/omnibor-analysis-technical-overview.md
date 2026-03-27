# OmniBOR Analysis: Technical Overview

## 1. How OmniBOR Works (Build Interception)

OmniBOR intercepts compiler/linker invocations during build to create an **Artifact Dependency Graph (ADG)** — a cryptographic record of every input→output relationship.

| Language | Tracer | Mechanism | What's Captured |
|----------|--------|-----------|-----------------|
| **C/C++** | `bomtrace3` | Patched strace v6.11; intercepts `execve()` for gcc/g++/ld | Every `.c`/`.h` → `.o` → binary relationship |
| **Rust** | `bomtrace2` | ptrace wrapper around `cargo build --release` | Crate compilation, `rustc` invocations, static linking |
| **Go** | `bomtrace2` + `bomtrace_go.conf` | Intercepts `go build -a` with openat syscall tracing | Module compilation, stdlib inclusion |
| **Java** | `bomsh_create_bom_java.py` | strace + JAR inspection via `javap` | `.java` → `.class` → JAR packaging, Maven dependencies |

**Output:** `bomsh_omnibor_treedb` — a JSON database mapping gitoid hashes (SHA-1 of file contents) to their build relationships.

---

## 2. omnibor-analysis Integration

**omnibor-analysis** wraps OmniBOR/bomsh tools into a reproducible pipeline:

```
Clone → Validate deps → bomtrace build → ADG → SPDX → Validate → Visualize
```

| Component | Source | Role |
|-----------|--------|------|
| `bomtrace3/bomtrace2` | omnibor/bomsh | Build interception (ptrace-based) |
| `bomsh_create_bom.py` | omnibor/bomsh | Raw log → ADG treedb |
| `bomsh_sbom.py` | omnibor/bomsh | ADG → basic OmniBOR SPDX |
| `app/spdx/generator.py` | omnibor-analysis | ADG → enriched per-binary SPDX with dpkg metadata |
| `app/spdx/java_generator.py` | omnibor-analysis | Java: ADG + `mvn dependency:tree` → SPDX |
| `app/version_detection/` | omnibor-analysis | 12 strategies for vendored library version detection |
| `app/spdx_visualize.py` | omnibor-analysis | SPDX → interactive D3.js HTML |

**Environment:** Docker container on AWS EC2 (Ubuntu 22.04 x86_64) with `SYS_PTRACE` capability.

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

See: [`omnibor-analysis-workflow.png`](omnibor-analysis-workflow.png)

Pipeline visualization showing:
- AWS EC2 + Docker container environment
- bomtrace3/bomtrace2 build interception flow
- ADG generation → SPDX generation → HTML visualization
- Output artifacts (analyzed + build SPDX JSON/HTML per binary)

---

*Document version: March 2026*
