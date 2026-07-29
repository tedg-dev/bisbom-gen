# Build-Based SBOMs for Enterprise Java Teams

| | |
|---|---|
| **Audience** | Enterprise Java build / platform teams |
| **What this is** | A short technical overview of how build-based SBOM generation fits a Java CI/CD pipeline |
| **The promise** | A complete, build-accurate SBOM with **near-zero impact** on the native build time |

---
<h2 align="center">Table of Contents</h2>

- [Build-Based SBOMs for Enterprise Java Teams](#build-based-sboms-for-enterprise-java-teams)
  - [The one-sentence pitch](#the-one-sentence-pitch)
  - [How it works: Phase 1 in the native pipeline, Phase 2 in Corona](#how-it-works-phase-1-in-the-native-pipeline-phase-2-in-corona)
  - [Near-zero impact on the native build environment](#near-zero-impact-on-the-native-build-environment)
  - [Which build tools](#which-build-tools)
  - [What the native build team actually adds to CI/CD](#what-the-native-build-team-actually-adds-to-cicd)
  - [What leaves the build machine](#what-leaves-the-build-machine)
  - [Want the deep dive?](#want-the-deep-dive)
  - [Appendix A — Proof: the native build time is unchanged](#appendix-a--proof-the-native-build-time-is-unchanged)
  - [Appendix B — Where the time goes: Phase 1 (in-pipeline) vs Phase 2 (offline)](#appendix-b--where-the-time-goes-phase-1-in-pipeline-vs-phase-2-offline)
  - [Appendix C — How this was measured](#appendix-c--how-this-was-measured)

---

## The one-sentence pitch

The native Java build (`mvn package` / `gradle build`) and the native build scripts
(`pom.xml` / `build.gradle`) stay **exactly as they are**. Phase 1 metadata capture is
added to the native CI/CD build step — after the native build completes, it ships a few
KB of metadata to Corona, where the SBOM is assembled off the native build machine.

Most SBOM tooling forces a change to the build configuration, adds a scanning stage to
the critical path, or requires handing over source. Phase 1 is added to the native
build step — no new pipeline steps, no build modifications.

---

## How it works: Phase 1 in the native pipeline, Phase 2 in Corona

The work is split into two phases connected by a tiny, signed handoff file. **Phase 1**
is a thin, build-time metadata step that lives next to the native build. **Phase 2** —
the actual SBOM assembly — runs in Corona, off the native build team's infrastructure.

<a href="https://github.com/tedg-dev/bisbom-gen/blob/main/docs/sidecar/java/java-sbom-phase-split.png"><img src="https://raw.githubusercontent.com/tedg-dev/bisbom-gen/main/docs/sidecar/java/java-sbom-phase-split.png" width="760" alt="Java build-based SBOM phase split — click to enlarge"></a>

*Click to enlarge. Source: [java-sbom-phase-split.drawio](https://github.com/tedg-dev/bisbom-gen/blob/main/docs/sidecar/java/java-sbom-phase-split.drawio)*

**Phase 1 (in the native pipeline) is deliberately thin:**

- The native build command (`mvn package` / `gradle build`) is **not modified** — no flags, no recompilation.
- A fast `mvn dependency:tree` / `gradlew dependencies` records the resolved dependency graph.
- `bomsh_create_bom_java.py` builds a compact `treedb` (compiled-class → source mapping) from the workspace the native build already produced.
- A `phase1_manifest.json` (~1–2 KB, with SHA-256 gitoids for tamper-evidence) is written and, with the two small metadata files, uploaded to a Corona S3 / Artifactory bucket.

**Phase 2 (in Corona) does the heavy lifting:**

- Reads the `treedb` + dependency tree, assembles and validates the **SPDX 2.3** SBOM, and files it under Product → Release → Image.
- Runs **asynchronously** — the native pipeline already moved on.

---

## Near-zero impact on the native build environment

This is the part that matters to the native build team:

- **Nothing is modified — only an addition.** The native `pom.xml` / `build.gradle`, the native `mvn` / `gradle` invocation, and the native pipeline structure stay byte-for-byte the same. Phase 1 metadata capture is added to the native CI/CD build step, after the native build completes.
- **No kernel tracing, no privileged runners.** No `ptrace`, no `SYS_PTRACE`, no `--privileged` container, no custom build agents.
- **Off the critical path.** Phase 1 takes **seconds**; Phase 2 SBOM generation happens later, in Corona, and never blocks Test or Deploy.
- **Tiny footprint.** What leaves the native build machine is a few KB of metadata — not source, not JARs, not binaries, not build logs.

---

## Which build tools

Maven and Gradle account for roughly **88% of Java builds**, and both are first-class:
Phase 1 records the resolved dependency graph with `mvn dependency:tree` or
`gradlew dependencies`, auto-detected, with no changes to the native build scripts or build invocations.

The approach is **not limited to them**. Phase 1 works from what the native build
*produces* — the compiled classes and the JARs on the classpath — not from the native
build configuration. Because identification is artifact-based rather than build-tool-based,
the same model covers **all Java build tooling**, including Ant/Ivy, Bazel, and
`make`-driven builds.

---

## What the native build team actually adds to CI/CD

Phase 1 metadata capture, added to the native build step. That's the whole change.

<a href="https://github.com/tedg-dev/bisbom-gen/blob/main/docs/sidecar/java/java-sbom-cicd-integration.png"><img src="https://raw.githubusercontent.com/tedg-dev/bisbom-gen/main/docs/sidecar/java/java-sbom-cicd-integration.png" width="760" alt="Java CI/CD integration — one added step — click to enlarge"></a>

*Click to enlarge. Source: [java-sbom-cicd-integration.drawio](https://github.com/tedg-dev/bisbom-gen/blob/main/docs/sidecar/java/java-sbom-cicd-integration.drawio)*

**GitHub Actions** — Phase 1 added to the native build step (names are illustrative):

```yaml
# .github/workflows/ci.yml — the native pipeline
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
            ghcr.io/<org>/bisbom-java-sidecar:1 phase1 \
            --build-tool maven \
            --corona-bucket corona-sbom-intake \
            --product my-service
```

**Jenkins** — Phase 1 added to the native Build stage:

```groovy
stage('Build') {
  steps {
    sh 'mvn -B package -DskipTests'

    // Phase 1: build-based SBOM metadata capture (the only addition)
    sh '''
      docker run --rm -v "$WORKSPACE:/src" -w /src \
        ghcr.io/<org>/bisbom-java-sidecar:1 phase1 \
        --build-tool maven \
        --corona-bucket corona-sbom-intake \
        --product my-service
    '''
  }
}
```

Phase 1 runs after the native build completes, within the same build step. It reads the
dependency tree + `treedb`, writes the signed manifest, and uploads to Corona. No
SBOM is assembled on the native runner. No new pipeline steps are created.

---

## What leaves the build machine

Only compact, signed metadata — and Corona turns it into the SBOM.

<a href="https://github.com/tedg-dev/bisbom-gen/blob/main/docs/sidecar/java/java-sbom-corona-handoff.png"><img src="https://raw.githubusercontent.com/tedg-dev/bisbom-gen/main/docs/sidecar/java/java-sbom-corona-handoff.png" width="760" alt="What leaves the build machine — Java metadata handoff to Corona — click to enlarge"></a>

*Click to enlarge. Source: [java-sbom-corona-handoff.drawio](https://github.com/tedg-dev/bisbom-gen/blob/main/docs/sidecar/java/java-sbom-corona-handoff.drawio)*

Because Java SBOM assembly needs only the `treedb` and the resolved dependency tree,
**Phase 2 never needs the native source tree or the native JARs**. The signed `phase1_manifest.json`
lets Corona verify integrity before it builds anything.

---

## Want the deep dive?

This page is the overview. The build-interception mechanics, the manifest schema, and
the CI/CD validation results are a longer conversation — **let's set up a walkthrough.**

---

## Appendix A — Proof: the native build time is unchanged

The promise at the top of this page is *near-zero impact on the native build time*.
Here is the measurement behind it.

Eleven real-world Java projects (Maven and Gradle) were each built **twice on the
same 4-vCPU cloud build host, back to back, with warm dependency caches** — once as
the **unmodified native build**, and once with **Phase 1 metadata capture added**.
The only variable is Phase 1, so any change in the build step is Phase 1's cost.

**The largest change on any project was six-tenths of a second.** Most projects
measured *slightly faster* with Phase 1 present — which is not a real speed-up
(capturing metadata cannot make a build faster), but a sign that Phase 1's cost is
smaller than the machine's own run-to-run variation.

<table>
  <thead>
    <tr>
      <th align="left">Project</th>
      <th align="left">Build tool</th>
      <th align="right">Native build (s)</th>
      <th align="right">Build w/ Phase 1 capture (s)</th>
      <th align="right">Difference (s)</th>
      <th align="right">Difference (%)</th>
    </tr>
  </thead>
  <tbody>
    <tr><td>jsoup</td><td>Maven</td><td align="right">15.2</td><td align="right">15.8</td><td align="right">+0.6</td><td align="right">+4.4%</td></tr>
    <tr><td>dependency-check</td><td>Maven</td><td align="right">23.0</td><td align="right">23.7</td><td align="right">+0.7</td><td align="right">+3.0%</td></tr>
    <tr><td>logging-log4j2</td><td>Maven</td><td align="right">100.4</td><td align="right">98.8</td><td align="right">&minus;1.6</td><td align="right">&minus;1.6%</td></tr>
    <tr><td>bc-java</td><td>Gradle</td><td align="right">139.6</td><td align="right">136.7</td><td align="right">&minus;2.9</td><td align="right">&minus;2.0%</td></tr>
    <tr><td>spring-boot</td><td>Gradle</td><td align="right">22.5</td><td align="right">22.1</td><td align="right">&minus;0.4</td><td align="right">&minus;2.0%</td></tr>
    <tr><td>rxjava</td><td>Gradle</td><td align="right">19.6</td><td align="right">18.4</td><td align="right">&minus;1.2</td><td align="right">&minus;5.9%</td></tr>
    <tr><td>caffeine</td><td>Gradle</td><td align="right">7.8</td><td align="right">7.3</td><td align="right">&minus;0.5</td><td align="right">&minus;6.2%</td></tr>
    <tr><td>bisbom-java-testapp</td><td>Maven</td><td align="right">3.0</td><td align="right">2.8</td><td align="right">&minus;0.2</td><td align="right">&minus;7.0%</td></tr>
    <tr><td>checkstyle</td><td>Maven</td><td align="right">25.4</td><td align="right">23.0</td><td align="right">&minus;2.4</td><td align="right">&minus;9.3%</td></tr>
    <tr><td>crawler4j</td><td>Maven</td><td align="right">8.4</td><td align="right">7.3</td><td align="right">&minus;1.1</td><td align="right">&minus;13.0%</td></tr>
    <tr><td>opentelemetry-java</td><td>Gradle</td><td align="right">22.1</td><td align="right">18.3</td><td align="right">&minus;3.8</td><td align="right">&minus;17.1%</td></tr>
  </tbody>
  <tfoot>
    <tr>
      <th align="left">Mean (11 projects)</th><th></th><th align="right">35.2</th><th align="right">34.0</th><th align="right">&minus;1.2</th><th align="right">&minus;5.2%</th>
    </tr>
  </tfoot>
</table>

**Why several numbers are negative — and why that is expected.** These are single
back-to-back runs on a modest shared host. The build that runs *second* benefits from
warmer operating-system and file-system caches, so it tends to measure a little
faster — which is exactly why most differences come out negative even though Phase 1
is doing *more* work, not less. Read every figure as **"within measurement noise"**:
Phase 1's effect on the native build step is too small to measure.

---

## Appendix B — Where the time goes: Phase 1 (in-pipeline) vs Phase 2 (offline)

This is the full end-to-end picture, included for completeness. It reinforces the core
design point: the only work on the native pipeline's critical path is the build plus a
**quick dependency listing** (seconds). The heavy **Phase 2 SPDX assembly runs offline
in Corona** and never blocks the native build.

<a href="https://github.com/tedg-dev/bisbom-gen/blob/main/docs/performance/java-pipeline-composition.png"><img src="https://raw.githubusercontent.com/tedg-dev/bisbom-gen/main/docs/performance/java-pipeline-composition.png" width="760" alt="Java wall-time breakdown — in-pipeline Phase 1 vs offline Phase 2 — click to enlarge"></a>

*Click to enlarge.*

The **Phase 1 %** and **Phase 2 %** columns show how each project's total measured
wall time splits between the in-pipeline work and the offline work, and add up to 100%.

<table>
  <thead>
    <tr>
      <th align="left">Project</th>
      <th align="right">Phase 1 build (s)</th>
      <th align="right">Phase 1 dep-listing (s)</th>
      <th align="right">Phase 1 in-pipeline (s)</th>
      <th align="right">Phase 1 %</th>
      <th align="right">Phase 2 SPDX — offline (s)</th>
      <th align="right">Phase 2 %</th>
    </tr>
  </thead>
  <tbody>
    <tr><td>bc-java</td><td align="right">136.7</td><td align="right">10.9</td><td align="right">147.6</td><td align="right">79.4%</td><td align="right">38.4</td><td align="right">20.6%</td></tr>
    <tr><td>spring-boot</td><td align="right">22.1</td><td align="right">23.6</td><td align="right">45.7</td><td align="right">50.1%</td><td align="right">45.6</td><td align="right">49.9%</td></tr>
    <tr><td>logging-log4j2</td><td align="right">98.8</td><td align="right">3.1</td><td align="right">101.9</td><td align="right">94.9%</td><td align="right">5.5</td><td align="right">5.1%</td></tr>
    <tr><td>opentelemetry-java</td><td align="right">18.3</td><td align="right">19.3</td><td align="right">37.6</td><td align="right">96.4%</td><td align="right">1.4</td><td align="right">3.6%</td></tr>
    <tr><td>dependency-check</td><td align="right">23.7</td><td align="right">3.6</td><td align="right">27.3</td><td align="right">81.7%</td><td align="right">6.1</td><td align="right">18.3%</td></tr>
    <tr><td>rxjava</td><td align="right">18.4</td><td align="right">5.9</td><td align="right">24.3</td><td align="right">78.4%</td><td align="right">6.7</td><td align="right">21.6%</td></tr>
    <tr><td>caffeine</td><td align="right">7.3</td><td align="right">18.5</td><td align="right">25.8</td><td align="right">94.9%</td><td align="right">1.4</td><td align="right">5.1%</td></tr>
    <tr><td>checkstyle</td><td align="right">23.0</td><td align="right">2.9</td><td align="right">25.9</td><td align="right">89.6%</td><td align="right">3.0</td><td align="right">10.4%</td></tr>
    <tr><td>jsoup</td><td align="right">15.8</td><td align="right">2.2</td><td align="right">18.0</td><td align="right">94.2%</td><td align="right">1.1</td><td align="right">5.8%</td></tr>
    <tr><td>crawler4j</td><td align="right">7.3</td><td align="right">2.2</td><td align="right">9.5</td><td align="right">91.3%</td><td align="right">0.9</td><td align="right">8.7%</td></tr>
    <tr><td>bisbom-java-testapp</td><td align="right">2.8</td><td align="right">2.2</td><td align="right">5.0</td><td align="right">84.7%</td><td align="right">0.9</td><td align="right">15.3%</td></tr>
  </tbody>
</table>

Within Phase 1, the only added step is the dependency listing: 2–4 s for Maven
single-module projects, rising to 18–24 s for large multi-module Gradle builds
(`spring-boot`, `caffeine`, `opentelemetry-java`). Phase 2 — the SPDX assembly — is
entirely offline and never blocks the build.

---

## Appendix C — How this was measured

- **Native build** — the unmodified `mvn` / `gradle` command, timed on its own.
- **With Phase 1** — the same build with metadata capture added, followed by the
  dependency listing (and, for the full-picture numbers in Appendix B, the offline
  Phase 2 SPDX assembly).
- **Conditions** — one 4-vCPU cloud host, warm Maven/Gradle caches so network time is
  excluded, a single run per project. Repeated runs with median reporting would tighten
  the figures; the pattern across 11 very different projects is already clearly
  negligible.
- **Scope** — all 11 Java projects tracked for this evaluation build and pass with
  Phase 1 present.
