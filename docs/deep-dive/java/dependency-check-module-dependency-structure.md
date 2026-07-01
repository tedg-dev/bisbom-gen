# DependencyCheck Inter-Module Dependency Structure — Deep Dive

| | |
|---|---|
| **Date** | 2026-06-18 |
| **Authors** | Ted G. (architect), Cascade AI |
| **Status** | Reference — validated on EC2 (sidecar mode, v9.2.0) |
| **Applies to** | `dependency-check` target repo (OWASP DependencyCheck) |
| **Related** | `docs/_archived/performance/bomsh-java-performance-optimization.md`, `docs/deep-dive/phase-isolation/phase2-binary-artifact-dependencies.md` |

---

## Table of Contents

1. [Why This Matters](#1-why-this-matters)
2. [The Three Module JARs](#2-the-three-module-jars)
3. [Two SBOM Views: `_analyzed` vs `_build`](#3-two-sbom-views-analyzed-vs-build)
4. [The Real Dependency Structure](#4-the-real-dependency-structure)
5. [Evidence — Not a Flattened Graph](#5-evidence--not-a-flattened-graph)
6. [Code Improvement: The Third (Correct) JAR](#6-code-improvement-the-third-correct-jar)
7. [Talking Points for the Team](#7-talking-points-for-the-team)
8. [How to Reproduce](#8-how-to-reproduce)

---

<a id="1-why-this-matters"></a>

## 1. Why This Matters

OWASP DependencyCheck builds as a **multi-module Maven reactor**. A single
build produces several JARs, and a common misconception is that they are
either independent artifacts or form a simple chain. Neither is true.

This document records the exact inter-module relationships, how our two
SBOM views represent them, and a correctness improvement in our tooling
that now captures a JAR the previous implementation silently dropped.

The build is driven entirely by config (no repo-specific code):

```yaml
build_steps:
- mvn package -DskipTests -q -pl cli -am
output_binaries:
- '**/target/*.jar'
```

`-pl cli -am` means "build the `cli` module **and** the modules it
depends on", so the reactor compiles `cli`, `core`, and `utils`. The
`output_binaries` glob then matches every produced JAR.

---

<a id="2-the-three-module-jars"></a>

## 2. The Three Module JARs

| JAR (artifact) | Role | Reactor relationship |
|---|---|---|
| `dependency-check` (cli) | CLI entry point — the shipped tool | top of the reactor |
| `dependency-check-core` | Core analysis engine | middle |
| `dependency-check-utils` | Shared low-level utilities | leaf (base) |

These are **three separate JARs on the classpath**. None physically
bundles another — each ships independently and is resolved at runtime.

---

<a id="3-two-sbom-views-analyzed-vs-build"></a>

## 3. Two SBOM Views: `_analyzed` vs `_build`

For every JAR we emit two SPDX documents, following the CISA SBOM
taxonomy. They answer different questions and this is the source of most
confusion.

The `_analyzed` SBOM contains **only the source files physically compiled
into that one JAR**:

| JAR | `_analyzed` packages | `_analyzed` files |
|---|---|---|
| `dependency-check` (cli) | 1 | 7 |
| `dependency-check-core` | 1 | 582 |
| `dependency-check-utils` | 1 | 48 |

The `_build` SBOM contains the **full Maven dependency graph** the JAR was
built against (direct dependencies plus their transitives):

| JAR | `_build` packages | `_build` relationships |
|---|---|---|
| `dependency-check` (cli) | 13 | 20 |
| `dependency-check-core` | 78 | 660 |
| `dependency-check-utils` | 12 | 60 |

**Key takeaway:**

In the `_analyzed` view the three JARs look independent (the cli JAR holds
only 7 of its own files). In the `_build` view their dependency
relationships are fully captured. The two views are complementary —
`_analyzed` = "what is inside this artifact", `_build` = "what this
artifact was built against".

---

<a id="4-the-real-dependency-structure"></a>

## 4. The Real Dependency Structure

The cli module declares **both** sibling modules directly; it is **not** a
pure `utils -> core -> cli` chain.

| Module | Directly depends on (sibling modules) |
|---|---|
| `dependency-check` (cli) | `dependency-check-core` **and** `dependency-check-utils` |
| `dependency-check-core` | `dependency-check-utils` |
| `dependency-check-utils` | none (external libraries only) |

So `dependency-check-utils` is a **direct** dependency of **both**
`dependency-check-core` **and** `dependency-check` (cli) — it is not merely
transitive through `core`. The cli genuinely compiles against utils in
addition to core.

This is confirmed by the Maven pom declarations (ground truth):

`cli/pom.xml` declares both:

- `dependency-check-core`
- `dependency-check-utils`

`core/pom.xml` declares:

- `dependency-check-utils`

One nuance in `core/pom.xml`: it carries
`<excludeArtifactIds>dependency-check-utils</excludeArtifactIds>` inside a
plugin configuration. That only prevents *bundling* utils into core's JAR
(utils ships as its own JAR); it does **not** remove the compile/runtime
dependency.

---

<a id="5-evidence--not-a-flattened-graph"></a>

## 5. Evidence — Not a Flattened Graph

Our `_build` SBOM preserves the real hierarchy rather than flattening every
transitive dependency onto the root. The cli (`dependency-check`) package
has exactly these 10 direct `DEPENDS_ON` edges:

- `annotations`
- `ant`
- `commons-cli`
- `dependency-check-core`
- `dependency-check-utils`
- `jsr305`
- `logback-classic`
- `logback-core`
- `slf4j-api`
- `spotbugs-annotations`

Crucially, the cli root does **not** point to core's transitive
dependencies (lucene, httpclient5, jackson, and so on) — those appear only
under `dependency-check-core` in core's own SBOM. Because the graph is
tree-structured, a `cli -> utils` edge exists **only** because utils is a
directly declared dependency of cli, not as an artifact of flattening.

The relationship types in the cli `_build` SBOM:

| Relationship type | Count |
|---|---|
| `DESCRIBES` | 1 |
| `CONTAINED_BY` | 7 |
| `BUILD_TOOL_OF` | 2 |
| `DEPENDS_ON` | 10 |

---

<a id="6-code-improvement-the-third-correct-jar"></a>

## 6. Code Improvement: The Third (Correct) JAR

**This is the headline finding for the team.**

The previous implementation (and the prior golden baseline) produced SBOMs
for only **two** JARs — `dependency-check-core` and
`dependency-check-utils`. The main shipped artifact, the cli JAR
`dependency-check-9.2.0.jar`, was **silently skipped**.

The root cause was in the class-to-source mapping built into the bomsh
treedb. The cli module's classes were not mapped to their sources, so when
`get_jar_source_files()` looked up the cli JAR it found no entries and the
JAR was dropped (the "no treedb match -> skip JAR" path).

The Java fast-path rewrite fixed this. The two relevant modules are:

- `bomsh_java_fast_classreader.py` — a pure-Python class-file reader that
  replaces per-class `javap` subprocess calls and reliably extracts the
  `SourceFile` attribute (and therefore the class-to-source mapping) for
  every class, including the cli module's classes.
- `bomsh_java_fast_io.py` — pure-Python replacements for `git hash-object`,
  `diff`, and `find`. Its `find_suffix_files()` also **sorts** its output,
  making treedb construction deterministic instead of filesystem-order
  dependent.

With the correct mapping in place, the cli JAR now resolves to its real
sources and receives a proper SBOM pair:

| New SBOM | Files | Notable contents |
|---|---|---|
| `dependency-check-9.2.0_analyzed.spdx.json` | 7 | `App.java`, `CliParser.java`, `package-info.java` (+ their `.class` files) |
| `dependency-check-9.2.0_build.spdx.json` | 7 files, 13 packages | direct deps incl. `dependency-check-core` and `dependency-check-utils` |

**Why this is a correctness fix, not a regression:**

The `core` and `utils` JARs remained **structurally byte-identical** to the
prior golden (582 / 48 files, 78 / 12 packages, all relationship counts
unchanged). If the new hashing or class reading had drifted, those would
have changed too. The only delta is the **additive** capture of a
legitimate build output that was previously missing. The cli JAR is the
artifact users actually run, so omitting its SBOM was a real gap.

As a bonus, the treedb build step for this repo dropped from roughly
**244 s to 19.5 s** (about 12x faster) — see
`docs/_archived/performance/bomsh-java-performance-optimization.md`.

---

<a id="7-talking-points-for-the-team"></a>

## 7. Talking Points for the Team

When discussing DependencyCheck SBOMs, lead with these points:

- **Three JARs, not one.** A single DependencyCheck build emits `cli`,
  `core`, and `utils` artifacts, each with its own SBOM pair.
- **Read the right view.** Use `_analyzed` for "what is inside this JAR"
  and `_build` for "what it depends on". Inter-module links live only in
  `_build`.
- **cli depends on core *and* utils directly.** It is not a simple chain;
  the cli pom declares both siblings.
- **utils is a direct dependency of both core and cli.** It is the leaf
  module and pulls in no sibling modules itself.
- **Our graph is hierarchical, not flattened.** A root only lists its
  direct dependencies, so the topology is meaningful for impact analysis.
- **We now capture the cli JAR.** The shipped CLI artifact finally has a
  complete SBOM; earlier tooling dropped it.

---

<a id="8-how-to-reproduce"></a>

## 8. How to Reproduce

Run the analysis in sidecar mode and compare against the golden baseline:

```bash
docker compose -f docker/docker-compose.yml run --rm omnibor-sidecar \
  bash -c "cd /workspace && python3 app/analyze.py \
  --repo dependency-check --mode sidecar --skip-clone"

python3 scripts/compare_golden.py \
  tests/golden/spdx/java/dependency-check \
  output/spdx/java/dependency-check/<run_ts>
```

Inspect the inter-module edges in any `_build` SBOM by filtering its
`relationships` array for `DEPENDS_ON` entries whose source and target are
both packages. The cli `_build` document shows the cli root depending on
both `dependency-check-core` and `dependency-check-utils`.
