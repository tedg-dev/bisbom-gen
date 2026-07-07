# Build-Based SBOMs for Enterprise Java Teams

| | |
|---|---|
| **Audience** | Enterprise Java build / platform teams |
| **What this is** | A short technical overview of how build-based SBOM generation fits a Java CI/CD pipeline |
| **The promise** | A complete, build-accurate SBOM with **near-zero impact** on your build time |

---

## The one-sentence pitch

Your Java build (`mvn package` / `gradle build`) and your build scripts (`pom.xml` /
`build.gradle`) stay **exactly as they are**. Phase 1 metadata capture is added to your
existing CI/CD build step — after your build completes, it ships a few KB of metadata
to Corona, where the SBOM is assembled off your build machine.

Most SBOM tooling makes you change your build configuration, add a scanning stage to
your critical path, or hand over source. Phase 1 is added to your existing build step
— no new pipeline steps, no build modifications.

---

## How it works: Phase 1 in your pipeline, Phase 2 in Corona

The work is split into two phases connected by a tiny, signed handoff file. **Phase 1**
is a thin, build-time metadata step that lives next to your build. **Phase 2** — the
actual SBOM assembly — runs in Corona, off your infrastructure.

<a href="https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/sidecar/java/java-sbom-phase-split.png"><img src="https://raw.githubusercontent.com/tedg-dev/omnibor-analysis/main/docs/sidecar/java/java-sbom-phase-split.png" width="760" alt="Java build-based SBOM phase split — click to enlarge"></a>

*Click to enlarge. Source: [java-sbom-phase-split.drawio](https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/sidecar/java/java-sbom-phase-split.drawio)*

**Phase 1 (in your pipeline) is deliberately thin:**

- Your build command (`mvn package` / `gradle build`) is **not modified** — no flags, no recompilation.
- A fast `mvn dependency:tree` / `gradlew dependencies` records the resolved dependency graph.
- `bomsh_create_bom_java.py` builds a compact `treedb` (compiled-class → source mapping) from the workspace your build already produced.
- A `phase1_manifest.json` (~1–2 KB, with SHA-256 gitoids for tamper-evidence) is written and, with the two small metadata files, uploaded to a Corona S3 / Artifactory bucket.

**Phase 2 (in Corona) does the heavy lifting:**

- Reads the `treedb` + dependency tree, assembles and validates the **SPDX 2.3** SBOM, and files it under Product → Release → Image.
- Runs **asynchronously** — your pipeline already moved on.

---

## Near-zero impact on your build environment

This is the part that matters to a build team:

- **Nothing is modified — only an addition.** Your `pom.xml` / `build.gradle`, your `mvn` / `gradle` invocation, and your pipeline structure stay byte-for-byte the same. Phase 1 metadata capture is added to your existing CI/CD build step, after the build completes.
- **No kernel tracing, no privileged runners.** No `ptrace`, no `SYS_PTRACE`, no `--privileged` container, no custom build agents.
- **Off the critical path.** Phase 1 takes **seconds**; Phase 2 SBOM generation happens later, in Corona, and never blocks Test or Deploy.
- **Tiny footprint.** What leaves your machine is a few KB of metadata — not source, not JARs, not binaries, not build logs.

---

## Which build tools

Maven and Gradle account for roughly **88% of Java builds**, and both are first-class:
Phase 1 records the resolved dependency graph with `mvn dependency:tree` or
`gradlew dependencies`, auto-detected, with no changes to your build scripts or build invocations.

The approach is **not limited to them**. Phase 1 works from what your build
*produces* — the compiled classes and the JARs on your classpath — not from your build
configuration. Because identification is artifact-based rather than build-tool-based,
the same model covers **all Java build tooling**, including Ant/Ivy, Bazel, and
`make`-driven builds.

---

## What your team actually adds to CI/CD

Phase 1 metadata capture, added to your existing build step. That's the whole change.

<a href="https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/sidecar/java/java-sbom-cicd-integration.png"><img src="https://raw.githubusercontent.com/tedg-dev/omnibor-analysis/main/docs/sidecar/java/java-sbom-cicd-integration.png" width="760" alt="Java CI/CD integration — one added step — click to enlarge"></a>

*Click to enlarge. Source: [java-sbom-cicd-integration.drawio](https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/sidecar/java/java-sbom-cicd-integration.drawio)*

**GitHub Actions** — Phase 1 added to your build step (names are illustrative):

```yaml
# .github/workflows/ci.yml — your existing pipeline
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: "17"

      - name: Build
        run: |
          mvn -B package -DskipTests

          # --- Phase 1: build-based SBOM metadata capture (the only addition) ---
          docker run --rm \
            -v "${{ github.workspace }}:/src" -w /src \
            ghcr.io/your-org/omnibor-java-sidecar:1 phase1 \
            --build-tool maven \
            --corona-bucket corona-sbom-intake \
            --product my-service
```

**Jenkins** — Phase 1 added to your Build stage:

```groovy
stage('Build') {
  steps {
    sh 'mvn -B package -DskipTests'

    // Phase 1: build-based SBOM metadata capture (the only addition)
    sh '''
      docker run --rm -v "$WORKSPACE:/src" -w /src \
        ghcr.io/your-org/omnibor-java-sidecar:1 phase1 \
        --build-tool maven \
        --corona-bucket corona-sbom-intake \
        --product my-service
    '''
  }
}
```

Phase 1 runs after your build completes, within the same build step. It reads the
dependency tree + `treedb`, writes the signed manifest, and uploads to Corona. No
SBOM is assembled on your runner. No new pipeline steps are created.

---

## What leaves the build machine

Only compact, signed metadata — and Corona turns it into the SBOM.

<a href="https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/sidecar/java/java-sbom-corona-handoff.png"><img src="https://raw.githubusercontent.com/tedg-dev/omnibor-analysis/main/docs/sidecar/java/java-sbom-corona-handoff.png" width="760" alt="What leaves the build machine — Java metadata handoff to Corona — click to enlarge"></a>

*Click to enlarge. Source: [java-sbom-corona-handoff.drawio](https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/sidecar/java/java-sbom-corona-handoff.drawio)*

Because Java SBOM assembly needs only the `treedb` and the resolved dependency tree,
**Phase 2 never needs your source tree or your JARs**. The signed `phase1_manifest.json`
lets Corona verify integrity before it builds anything.

---

## Want the deep dive?

This page is the overview. The build-interception mechanics, the manifest schema, and
the CI/CD validation results are a longer conversation — **let's set up a walkthrough.**
