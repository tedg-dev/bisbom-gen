# Sub-Issue Draft — Support Non-Maven/Gradle Java Builds

| | |
|---|---|
| **Main issue** | Phase 1 Build-Speed & Efficiency (Java) — capture coverage |
| **Epic** | Single epic — this main issue is added to it later by the issues team |
| **Index label** | A9 (see `../README.md`) |
| **Relationship** | Extends Java Phase 1 dependency capture beyond Maven/Gradle; complements the Java Phase 2 main issue (`../java-phase2-consume-dep-capture-subissue.md`) |
| **Applies to** | Java builds using Ant, Ivy, Bazel, or `make`/`javac` |
| **Author** | Ted G. |
| **Drafted** | 2026-06-29 (Cascade) |
| **Status** | Step 0 (real-repo validation) done — see design §13; no code yet |
| **Detailed design** | `../../sidecar/java/reference/nonmaven-gradle-adapter.md` (integration points, capture contract, Ivy/Bazel parsers, artifact-only path) |

---

## Background

Maven and Gradle account for roughly **88% of Java builds** and are fully
supported today. The remaining tail uses Ant (often with Ivy), Bazel, or a
hand-rolled `make`/`javac` build. The Java charter is to be **accurate for
all Java build tooling**, so this sub-issue closes the gap.

`sbt` is intentionally **out of scope**: it is a Scala-first tool, and a
pure-Java `sbt` project is rare — covering it would test Scala, not Java.

---

## Approach: artifact-based first, declared-graph second

Identification is **build-tool-agnostic** because it reads what the build
*produces*, not how it was configured:

1. **Universal (works for any build):** the compiled `.class` files and the
   JARs on the classpath are hashed (GitOID) and resolved via the same
   treedb path used today. This already gives component-level provenance
   regardless of build tool.
2. **Per-ecosystem declared-graph adapter (accuracy boost):** where the build
   tool produces a resolved dependency graph, parse it to enrich
   coordinates/scopes — mirroring `maven_dep_tree_parser.py` /
   `gradle_dep_tree_parser.py`:
   - **Ivy** — parse the Ivy resolution report (XML).
   - **Bazel** — parse `rules_jvm_external`'s `maven_install.json` lockfile.
   - **Ant (no Ivy) / `make`** — no declared graph; rely on the universal
     artifact-based path.

---

## Verifier repos (to add to `config.yaml`)

Each verifies a real build path and gets golden SBOMs (golden files require
USER review — never auto-generated/updated).

Finalized from Step 0 real-artifact validation (see design §13.4):

| Build tool | Repo | Pin | Status / why |
|---|---|---|---|
| Ant + Ivy | `apache/ant-ivy` | `2.5.2` | **Confirmed** (§13.3): `ivy:retrieve` produces a real resolution report; unforked `<javac>`. Build: `ant jar`. |
| Plain `make`/`javac` | new `omnibor-java-make-testapp` | `main` (we own it) | **To create**: controlled `Makefile` -> `javac` -> `jar`; exercises the §8.1 PATH shim |
| Bazel + lockfile | candidate `bazelbuild/examples` — **exact path TBD** | commit SHA | `rules_jvm_external` + `maven_install.json` (§13.1). Prior `java-maven` path 404'd; re-confirm. **Gated on Bazel toolchain decision.** |
| Ant (no Ivy) | optional `apache/ant` | release tag | Lower priority — heavier bootstrap; artifact-only path also covered by the `make` test app |

---

## Toolchain implications (decision needed before Docker changes)

- Ant + Ivy: modest additions to the analysis image.
- **Bazel: heavyweight** — large, slow dependency to add to the image and CI.
  **Confirm with USER before adding Bazel** to the Docker image; the Ant/Ivy
  and `make` paths can land first.

---

## Acceptance Criteria

- Given an Ant+Ivy build, when Phase 1 runs, then components are captured and
  the Ivy resolution report enriches the dependency coordinates.
- Given a Bazel `rules_jvm_external` build, when Phase 1 runs, then components
  are captured and `maven_install.json` enriches the coordinates.
- Given an Ant-only or `make`/`javac` build with no declared graph, when
  Phase 1 runs, then component-level provenance is still produced from the
  artifacts.
- Given any of the above, when the SBOM is produced, then it is reviewed
  against a USER-approved golden baseline (no auto-generated goldens).
- Given the changes, when verified locally, then project gates pass (import,
  `flake8`, `pytest`, coverage thresholds); generic/config-driven, no
  repo-specific logic.

---

## Proposed work breakdown

0. **Investigate real repositories (design research + validation).** Before
   any parser code, examine **actual build artifacts** from real repos to
   validate every design assumption and finalize the verifier-repo list:
   - a real Ivy resolution-report XML (`apache/ant-ivy`) — confirm element
     names (`organisation`/`name`/`revision`/`conf`) and report location;
   - a real `maven_install.json` (`bazelbuild/bazel`, `rules_jvm_external`) —
     confirm structure and direct/transitive edges;
   - `apache/ant` — confirm unforked `<javac>` (drives §8.1 of the design);
   - candidate `make`/`javac` Java layouts.
   This step supplements, and is a prerequisite to, the parser designs below
   (no parser is finalized against an assumed format).
1. **Verifier repos + `make` test app** — add the (investigation-confirmed)
   repos; create `omnibor-java-make-testapp`.
2. **Confirm Bazel toolchain decision** — gate the Bazel verifier.
3. **Ivy adapter** — parse the Ivy resolution report (format validated in 0).
4. **Bazel adapter** — parse `maven_install.json` (format validated in 0).
5. **Validate artifact-only path** for Ant-only and `make`/`javac`.
6. **Golden review** — present SBOMs to the USER; never auto-update goldens.

---

## Open questions

- **Bazel in the image?** Confirm before adding the heavyweight toolchain.
- **`make` test app shape** — minimal `Makefile` + `javac` + `jar` with 1–2
  external JARs placed on the classpath manually; confirm scope.
- **Build-tool detection** — extend the existing detector to recognize
  `build.xml`/`ivy.xml`, `WORKSPACE`/`BUILD.bazel`, and `Makefile`-driven
  Java; config can override.
