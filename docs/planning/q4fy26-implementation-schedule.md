# Q4FY26 Sidecar Implementation Schedule

| | |
|---|---|
| **Start date** | 2026-05-05 (Monday) |
| **Q4FY26 scope** | Phase 1 (Java pilot) + Phase 2 (C/C++ pilot) |
| **Working weeks** | 7 weeks across May 5 – July 11, 2026 |
| **Vacation** | **May 17 – June 10** (no work scheduled) |
| **Source documents** | [sidecar-implementation-design.md](../_archived/design-evolution/sidecar-implementation-design.md), [sidecar-refactoring-plan.md](../_archived/design-evolution/sidecar-refactoring-plan.md) |
| **Issue tracker** | [q4fy26-sidecar-issues.md](q4fy26-sidecar-issues.md) |

> **Modes note (historical):** This is a point-in-time Q4FY26 schedule that
> treats standalone as the then-current baseline being migrated to sidecar.
> **Sidecar is now the only supported mode**; standalone is deprecated
> (initial implementation, ~1% embedded corner case). Read the standalone
> references below as that migration context, not as a current option.
>
> **Interception-mechanism note (historical):** Track D below frames the
> C/C++ `CC=`/`CXX=`/`AR=`/`LD=` wrappers as the "sidecar" mechanism. That
> classification is **superseded**: those wrappers modify the build and are
> now classified as *standalone-without-ptrace*. The current truly-sidecar
> C/C++ mechanism is the `LD_PRELOAD` shim (**primary**, injected via
> CI/CD-YAML env vars) with eBPF/audit node-observer fallbacks — see
> `../sidecar/c-cpp/sidecar-design.md`.

---

## Goal

**Java and C/C++ sidecar mode production-ready on enterprise distros (RHEL/CentOS).** No `SYS_PTRACE` capability required. Dual-mode Docker image published.

---

## Phase 1: Infrastructure + Java Pilot (Weeks 1–4: May 5 – May 30)

Phase 1 has **three parallel tracks** with no dependencies between them. All three must complete before the Java pilot is declared ready.

### Track A: Package Resolver (`feat/package-resolver`)

**Why first:** Blocks ALL enterprise deployment. The pipeline currently hardcodes `dpkg`/`dpkg-query` and `pkg:deb/ubuntu/` PURLs. On RHEL (the most common enterprise Linux), every metadata call fails silently.

<table>
<tr>
  <th style="width:5%">#</th>
  <th style="width:40%">Task</th>
  <th style="width:8%">Est.</th>
  <th style="width:12%">Week</th>
  <th style="width:35%">Acceptance Criteria</th>
</tr>
<tr>
  <td>A1</td>
  <td><strong>Create <code>PackageResolver</code> ABC</strong><br>New file: <code>app/spdx/package_resolver.py</code><br>Abstract methods: <code>resolve(file_path) → metadata</code>, <code>purl_scheme() → str</code><br>Design: <a href="sidecar-implementation-design.md#43-package-resolver-abstraction">impl-design §4.3</a></td>
  <td>0.5d</td>
  <td>W1</td>
  <td>ABC importable; <code>mypy</code> passes; 100% test coverage on interface</td>
</tr>
<tr>
  <td>A2</td>
  <td><strong>Implement <code>DpkgResolver</code></strong><br>Extracts current logic from <code>collect_metadata.py</code> lines 111–153 and <code>collect_dynamic_libs.py</code> lines 100–106 into the new class<br>Returns <code>pkg:deb/{distro_codename}/</code></td>
  <td>1d</td>
  <td>W1</td>
  <td>All existing tests pass (zero regression); <code>DpkgResolver</code> unit tests with mocked subprocess; output identical to current hardcoded behavior on Ubuntu</td>
</tr>
<tr>
  <td>A3</td>
  <td><strong>Implement <code>RpmResolver</code></strong><br>Uses <code>rpm -qf</code> for file→package, <code>rpm -qi</code> for metadata<br>Returns <code>pkg:rpm/{distro}/</code> (RHEL, CentOS, Fedora, Rocky, Alma)</td>
  <td>1.5d</td>
  <td>W1–2</td>
  <td>Unit tests with mocked <code>rpm</code> output; handles edge cases (diverted files, multiple providers)</td>
</tr>
<tr>
  <td>A4</td>
  <td><strong>Implement <code>ApkResolver</code></strong><br>Uses <code>apk info --who-owns</code><br>Returns <code>pkg:apk/alpine/</code></td>
  <td>1d</td>
  <td>W2</td>
  <td>Unit tests with mocked <code>apk</code> output</td>
</tr>
<tr>
  <td>A5</td>
  <td><strong>Implement <code>auto_detect_resolver()</code></strong><br>Reads <code>/etc/os-release</code> (<code>ID</code> and <code>VERSION_CODENAME</code> fields)<br>Falls back to <code>DpkgResolver</code> if detection fails<br>Logs detected distro at startup</td>
  <td>0.5d</td>
  <td>W2</td>
  <td>Correctly detects Ubuntu 22.04, RHEL 8/9, Alpine 3.18+; unit tests with mocked <code>/etc/os-release</code></td>
</tr>
<tr>
  <td>A6</td>
  <td><strong>Refactor <code>metadata_collector.py</code></strong><br>Replace hardcoded <code>dpkg -S</code> and <code>dpkg-query -W</code> calls with <code>PackageResolver.resolve()</code><br>Inject resolver via parameter (dependency injection)</td>
  <td>1d</td>
  <td>W2–3</td>
  <td>All existing metadata tests pass; <code>collect_metadata.py</code> no longer imports <code>dpkg</code> directly</td>
</tr>
<tr>
  <td>A7</td>
  <td><strong>Refactor <code>collect_dynamic_libs.py</code></strong><br>Same pattern: replace <code>dpkg-query</code> with resolver</td>
  <td>0.5d</td>
  <td>W3</td>
  <td>Dynamic lib metadata resolution uses resolver; tests pass</td>
</tr>
<tr>
  <td>A8</td>
  <td><strong>Refactor <code>resolver.py</code> PURL generation</strong><br>Replace hardcoded <code>pkg:deb/ubuntu/</code> with <code>PackageResolver.purl_scheme()</code><br>Replace Ubuntu-specific version stripping with distro-aware normalization</td>
  <td>1d</td>
  <td>W3</td>
  <td>PURLs use correct scheme per distro; existing golden file tests pass on Ubuntu</td>
</tr>
<tr>
  <td>A9</td>
  <td><strong>Refactor <code>pipeline/validator.py</code></strong><br>Replace <code>dpkg-query -W</code> pre-build check with resolver-based validation</td>
  <td>0.5d</td>
  <td>W3</td>
  <td>Validator works on dpkg, rpm, and apk systems</td>
</tr>
<tr>
  <td>A10</td>
  <td><strong>RPM integration testing</strong><br>Run full pipeline on RHEL 8/9 (EC2 or Docker <code>rockylinux:9</code>)<br>Verify PURLs, metadata, SPDX output</td>
  <td>1d</td>
  <td>W4</td>
  <td>Valid SPDX on RHEL; PURLs are <code>pkg:rpm/rhel/</code>; no <code>dpkg</code> calls in logs</td>
</tr>
<tr>
  <td>A11</td>
  <td><strong>Alpine integration testing</strong><br>Run pipeline in <code>alpine:3.18</code> Docker container</td>
  <td>0.5d</td>
  <td>W4</td>
  <td>Valid SPDX on Alpine; PURLs are <code>pkg:apk/alpine/</code></td>
</tr>
</table>

**Track A totals:** ~9 days (1.8 weeks)

---

### Track B: Java Optimization (`feat/java-dep-tree`)

**Why:** Java already works in sidecar mode via strace, but enterprise security teams block `SYS_PTRACE`. Replacing strace with Maven/Gradle `dep:tree` removes this requirement.

<table>
<tr>
  <th style="width:5%">#</th>
  <th style="width:40%">Task</th>
  <th style="width:8%">Est.</th>
  <th style="width:12%">Week</th>
  <th style="width:35%">Acceptance Criteria</th>
</tr>
<tr>
  <td>B1</td>
  <td><strong>Create <code>MavenDepTreeStrategy</code></strong><br>New class in <code>app/pipeline/interception.py</code><br>Runs <code>mvn dependency:tree -DoutputType=dot</code> after build<br>Parses DOT output into treedb-compatible format<br>Design: <a href="sidecar-implementation-design.md#5-per-language-refactoring-java">impl-design §5.3</a></td>
  <td>2d</td>
  <td>W1</td>
  <td>Unit tests with mocked <code>mvn</code> output; DOT parser handles scope (compile, runtime, provided, test)</td>
</tr>
<tr>
  <td>B2</td>
  <td><strong>Maven shade/assembly plugin detection</strong><br>Parse <code>pom.xml</code> for shade and assembly plugins<br>Log warning when detected: "SPDX may not reflect uber-JAR contents"<br>Add <code>comment</code> to SPDX <code>creationInfo</code></td>
  <td>1d</td>
  <td>W1–2</td>
  <td>Warning logged for shade plugin; SPDX comment field populated</td>
</tr>
<tr>
  <td>B3</td>
  <td><strong>Create <code>GradleDepTreeStrategy</code></strong><br>Runs <code>./gradlew dependencies --configuration runtimeClasspath</code><br>Parses tree output into dependency graph</td>
  <td>1.5d</td>
  <td>W2</td>
  <td>Parses Gradle dependency tree; handles multi-project builds; unit tests with fixture output</td>
</tr>
<tr>
  <td>B4</td>
  <td><strong>Wire strategies into Java pipeline</strong><br>Modify <code>lang_runners.py</code> <code>run_java_pipeline()</code> to use strategy<br>Config selects: strace (standalone), dep:tree (sidecar)</td>
  <td>1d</td>
  <td>W2–3</td>
  <td><code>--mode sidecar</code> uses dep:tree; <code>--mode standalone</code> uses strace; backward compatible</td>
</tr>
<tr>
  <td>B5</td>
  <td><strong>Integration test: jsoup (Maven) without strace</strong><br>Build jsoup 1.22.1 using dep:tree strategy<br>Compare SPDX to strace golden file</td>
  <td>0.5d</td>
  <td>W3</td>
  <td>SPDX structurally equivalent: same dependency names, same relationship types, package count within ±5%</td>
</tr>
<tr>
  <td>B6</td>
  <td><strong>Integration test: checkstyle (Maven, shade plugin)</strong><br>Build checkstyle using dep:tree strategy<br>Verify shade plugin warning is emitted</td>
  <td>0.5d</td>
  <td>W3</td>
  <td>Warning logged; SPDX comment mentions shade plugin</td>
</tr>
<tr>
  <td>B7</td>
  <td><strong>Integration test: Java on RHEL</strong><br>Run Java pipeline on RHEL (via Docker or EC2)<br>Uses dep:tree + RpmResolver together</td>
  <td>1d</td>
  <td>W4</td>
  <td>Valid SPDX; no strace, no <code>SYS_PTRACE</code>, no <code>dpkg</code></td>
</tr>
</table>

**Track B totals:** ~7.5 days (1.5 weeks)

---

### Track C: Config + Infrastructure (`feat/config-mode-schema`, `feat/dual-mode-docker`)

**Why:** All wrapper-based strategies need `CommandRunner.run()` env support. All languages need mode selection. Enterprise teams need a delivery mechanism (sidecar Docker image).

<table>
<tr>
  <th style="width:5%">#</th>
  <th style="width:40%">Task</th>
  <th style="width:8%">Est.</th>
  <th style="width:12%">Week</th>
  <th style="width:35%">Acceptance Criteria</th>
</tr>
<tr>
  <td>C1</td>
  <td><strong><code>CommandRunner.run()</code> env support</strong><br>Add <code>env</code> parameter that merges with <code>os.environ</code><br><code>env=None</code> preserves existing behavior<br>Design: <a href="sidecar-implementation-design.md#41-commandrunner--environment-variable-support">impl-design §4.1</a></td>
  <td>0.5d</td>
  <td>W1</td>
  <td>All existing tests pass; new test verifies env vars propagated to subprocess</td>
</tr>
<tr>
  <td>C2</td>
  <td><strong>Config schema mode selection</strong><br>Add <code>mode: standalone|sidecar</code> top-level key to <code>config.yaml</code><br>Implement <code>resolve_omnibor_cfg(config, language)</code><br>Backward compatible with legacy flat format<br>Design: <a href="sidecar-implementation-design.md#42-config-schema--mode-selection">impl-design §4.2</a></td>
  <td>1.5d</td>
  <td>W1–2</td>
  <td>New nested config works; old flat config still works; unit tests for both paths</td>
</tr>
<tr>
  <td>C3</td>
  <td><strong><code>InterceptionStrategy</code> ABC + <code>PtraceStrategy</code></strong><br>New file: <code>app/pipeline/interception.py</code><br><code>PtraceStrategy</code> encapsulates current <code>bomtrace3 {cmd}</code> behavior exactly<br>Design: <a href="sidecar-implementation-design.md#45-interception-strategy-interface">impl-design §4.5</a></td>
  <td>1d</td>
  <td>W2</td>
  <td><code>PtraceStrategy.instrument_command()</code> returns identical command to current builder; all existing tests pass</td>
</tr>
<tr>
  <td>C4</td>
  <td><strong>Refactor <code>builder.py</code> to use strategy</strong><br><code>BomtraceBuilder.build()</code> accepts <code>strategy</code> parameter<br>Delegates to <code>strategy.instrument_command()</code> + <code>strategy.generate_adg()</code><br>Design: <a href="sidecar-implementation-design.md#45-interception-strategy-interface">impl-design §4.5 (builder refactoring)</a></td>
  <td>1d</td>
  <td>W2–3</td>
  <td>Builder delegates to strategy; <code>PtraceStrategy</code> produces identical behavior; all tests pass</td>
</tr>
<tr>
  <td>C5</td>
  <td><strong>Path abstraction layer</strong><br>Move 14 hardcoded paths into <code>config.yaml</code> <code>paths:</code> section<br>Auto-detect from env vars (<code>GOROOT</code>, <code>CARGO_HOME</code>)<br>Design: <a href="sidecar-implementation-design.md#44-path-abstraction-layer">impl-design §4.4</a></td>
  <td>1.5d</td>
  <td>W3</td>
  <td>No hardcoded <code>/workspace/</code>, <code>/opt/bomsh/</code>, <code>/usr/local/go</code> paths in Python code; paths configurable via config + env vars</td>
</tr>
<tr>
  <td>C6</td>
  <td><strong><code>analyze.py --mode</code> CLI flag</strong><br>Add <code>--mode sidecar|standalone</code> argument<br>Overrides config file <code>mode:</code> key</td>
  <td>0.5d</td>
  <td>W3</td>
  <td><code>analyze.py --help</code> shows mode flag; CLI overrides config</td>
</tr>
<tr>
  <td>C7</td>
  <td><strong>Dual-mode Dockerfile</strong><br>Multi-stage Dockerfile: <code>standalone</code> stage (full), <code>sidecar</code> stage (tools only)<br><code>FROM omnibor-env:standalone</code> extensibility for Standalone (custom)<br>Design: <a href="sidecar-refactoring-plan.md#52-dual-mode-container-image">refactoring-plan §5.2</a></td>
  <td>1.5d</td>
  <td>W3–4</td>
  <td>Two image tags buildable; sidecar image &lt;300MB; standalone image unchanged; <code>FROM omnibor-env:standalone</code> works for custom images</td>
</tr>
<tr>
  <td>C8</td>
  <td><strong>End-to-end standalone regression test</strong><br>Run full pipeline for all existing repos in standalone mode<br>Compare against golden files<br>Zero regressions allowed</td>
  <td>1d</td>
  <td>W4</td>
  <td>All existing golden file tests pass; coverage ≥97%</td>
</tr>
</table>

**Track C totals:** ~8.5 days (1.7 weeks)

---

### Phase 1 Milestone: Java Pilot Ready (End of Week 4 — May 30)

**Exit criteria:**

- [ ] `analyze.py --repo jsoup --mode sidecar` produces valid SPDX on RHEL
- [ ] Package resolution works on Ubuntu, RHEL 8/9, Alpine 3.18+
- [ ] PURLs use correct scheme per distro
- [ ] `SYS_PTRACE` not required for Java sidecar builds
- [ ] Docker Hub has `omnibor-env:sidecar` and `omnibor-env:standalone` tags
- [ ] All existing standalone tests pass (zero regressions)
- [ ] Coverage ≥97%

---

## Phase 2: C/C++ Pilot (Weeks 5–7: June 2 – June 20)

Phase 2 depends on Phase 1 infrastructure (Track A + Track C).

**Upstream dependency:** C/C++ wrapper binaries (`gcc-wrapper`, `g++-wrapper`, `ar-wrapper`, `ld-wrapper`) must be available from bomsh by Week 5. **Request upstream work to begin Week 1 of Phase 1** so wrappers are ready.

### Track D: C/C++ Sidecar (`feat/cc-sidecar`)

<table>
<tr>
  <th style="width:5%">#</th>
  <th style="width:40%">Task</th>
  <th style="width:8%">Est.</th>
  <th style="width:12%">Week</th>
  <th style="width:35%">Acceptance Criteria</th>
</tr>
<tr>
  <td>D1</td>
  <td><strong>Implement <code>CcWrapperStrategy</code></strong><br>Sets <code>CC</code>, <code>CXX</code>, <code>AR</code>, <code>LD</code> env vars pointing to wrapper binaries<br>Supports <code>wrapper_chain</code> config for ccache/distcc delegation<br>Design: <a href="sidecar-implementation-design.md#45-interception-strategy-interface">impl-design §4.5</a></td>
  <td>1.5d</td>
  <td>W5</td>
  <td>Unit tests; <code>instrument_command()</code> returns unmodified build command + correct env dict</td>
</tr>
<tr>
  <td>D2</td>
  <td><strong>Wire <code>CcWrapperStrategy</code> into C/C++ pipeline</strong><br>Modify <code>lang_runners.py</code> <code>run_c_cpp_pipeline()</code><br>Config selects: ptrace (standalone), CC= wrappers (sidecar)</td>
  <td>0.5d</td>
  <td>W5</td>
  <td><code>--mode sidecar</code> sets wrapper env vars; standalone unchanged</td>
</tr>
<tr>
  <td>D3</td>
  <td><strong>Refactor <code>emitter.py</code> compiler info</strong><br>Replace hardcoded "GCC" <code>BUILD_TOOL_OF</code> with strategy-provided compiler info<br>Detect actual compiler from wrapper output or config</td>
  <td>1d</td>
  <td>W5</td>
  <td>SPDX <code>BUILD_TOOL_OF</code> reflects actual compiler; not hardcoded to GCC</td>
</tr>
<tr>
  <td>D4</td>
  <td><strong>Integration test: curl sidecar on Ubuntu</strong><br>Build curl 8.19.0 with <code>CC=</code> wrappers<br>Compare SPDX to standalone golden file</td>
  <td>1d</td>
  <td>W6</td>
  <td>SPDX structurally equivalent; package count within ±5%; same relationship types</td>
</tr>
<tr>
  <td>D5</td>
  <td><strong>Integration test: ffmpeg sidecar on Ubuntu</strong><br>Build ffmpeg with wrappers (multi-binary project)</td>
  <td>0.5d</td>
  <td>W6</td>
  <td>All 5 ffmpeg binaries appear in SPDX; same root package structure</td>
</tr>
<tr>
  <td>D6</td>
  <td><strong>Integration test: C/C++ sidecar on RHEL</strong><br>Build curl on RHEL 8/9<br>Uses <code>CC=</code> wrappers + <code>RpmResolver</code> together</td>
  <td>1d</td>
  <td>W6–7</td>
  <td>Valid SPDX on RHEL; PURLs are <code>pkg:rpm/</code>; no ptrace, no dpkg</td>
</tr>
<tr>
  <td>D7</td>
  <td><strong>Wrapper chaining test: ccache + OmniBOR wrapper</strong><br>Verify <code>wrapper_chain: [ccache]</code> config works<br>Test: build with ccache warm cache, verify SPDX still correct</td>
  <td>0.5d</td>
  <td>W7</td>
  <td>Build succeeds with ccache; SPDX identical to non-ccache build</td>
</tr>
<tr>
  <td>D8</td>
  <td><strong>End-to-end regression: all languages, both modes</strong><br>Run full pipeline for all repos in standalone AND sidecar<br>Compare all outputs</td>
  <td>1d</td>
  <td>W7</td>
  <td>Zero regressions; sidecar output structurally equivalent to standalone; coverage ≥97%</td>
</tr>
</table>

**Track D totals:** ~7 days (1.4 weeks)

---

### Phase 2 Milestone: C/C++ Pilot Ready (End of Week 7 — June 20)

**Exit criteria:**

- [ ] `analyze.py --repo curl --mode sidecar` produces valid SPDX
- [ ] `CC=` / `CXX=` / `AR=` / `LD=` injection via `CommandRunner` env support
- [ ] `SYS_PTRACE` not required for C/C++ sidecar builds
- [ ] Sidecar SPDX matches standalone within ≤5% package count
- [ ] Wrapper chaining with ccache verified
- [ ] All languages work in both modes (zero standalone regressions)

---

## GitHub Issue Structure

Each task maps 1:1 to a GitHub issue. Issues use the following conventions:

**Labels:**

| Label | Purpose |
|-------|---------|
| `phase-1` | Phase 1 (Weeks 1–4) |
| `phase-2` | Phase 2 (Weeks 5–7) |
| `track-a-resolver` | Package resolver abstraction |
| `track-b-java` | Java optimization |
| `track-c-infra` | Config + infrastructure |
| `track-d-cc-sidecar` | C/C++ sidecar |
| `blocker` | Blocks other work |
| `upstream-dep` | Depends on upstream bomsh deliverable |

**Issue title format:** `[TRACK-ID] Task title`

Example: `[A1] Create PackageResolver ABC`

**Issue body template:**

```markdown
## Task
[description]

## Design Reference
[link to implementation design section]

## Files to Modify
- [ ] `app/spdx/package_resolver.py` (new)
- [ ] `tests/test_package_resolver.py` (new)

## Acceptance Criteria
- [ ] [criterion 1]
- [ ] [criterion 2]

## Branch
`feat/package-resolver`

## Depends On
- #[issue number] (if any)
```

**Milestones:**

| Milestone | Target Date |
|-----------|-------------|
| Phase 1: Java Pilot Ready | 2026-05-30 |
| Phase 2: C/C++ Pilot Ready | 2026-06-20 |

---

## Dependency Graph

<a href="../sidecar/sidecar-dependency-graph.png"><img src="../sidecar/sidecar-dependency-graph.png" width="600" alt="Sidecar Priority Dependency Graph — click to enlarge"></a>

*Click image to enlarge. Source: [sidecar-dependency-graph.drawio](../sidecar/sidecar-dependency-graph.drawio)*

---

## Upstream Coordination

<table>
<tr>
  <th style="width:25%">Upstream Deliverable</th>
  <th style="width:12%">Needed By</th>
  <th style="width:10%">Owner</th>
  <th style="width:53%">Notes</th>
</tr>
<tr>
  <td><code>gcc-wrapper</code>, <code>g++-wrapper</code></td>
  <td>Week 5 (Jun 23)</td>
  <td>bomsh team</td>
  <td>Request start Week 1. 3.5-week vacation provides extra lead time. Written in C, ~200 lines each. Must hash inputs/outputs and write raw_logfile entries.</td>
</tr>
<tr>
  <td><code>ar-wrapper</code>, <code>ld-wrapper</code></td>
  <td>Week 5 (Jun 23)</td>
  <td>bomsh team</td>
  <td>Archive and link-step tracking. ~150–200 lines each.</td>
</tr>
<tr>
  <td><code>as-wrapper</code>, <code>ranlib-wrapper</code></td>
  <td>Week 6 (Jun 30)</td>
  <td>bomsh team</td>
  <td>Lower priority — not all builds exercise <code>as</code> or <code>ranlib</code> directly.</td>
</tr>
</table>

**Action item for Week 1:** File upstream issue/request for C/C++ wrapper binaries with the specification from [implementation design §10](sidecar-implementation-design.md#10-upstream-bomsh-changes).

---

## Risk Register (Q4-Scoped)

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Upstream C/C++ wrappers delayed | Phase 2 slips | Medium | Start upstream request Week 1; have fallback plan to write minimal wrappers ourselves (~1 week) |
| RPM edge cases on RHEL (diverted files, multi-arch) | Invalid PURLs on enterprise distros | Medium | Budget 1 day for RPM edge case testing (task A10); use Rocky Linux 9 Docker for testing |
| Maven dep:tree diverges from strace output | Java SPDX less accurate | Low | dep:tree is industry standard (CycloneDX pattern); log warning for shade/assembly plugins |
| Path abstraction breaks existing pipeline | Standalone regression | Low | Run full golden file regression (task C8) before merging |

---

## Week-by-Week Summary

| Week | Dates | Track A (Resolver) | Track B (Java) | Track C (Infra) | Track D (C/C++) |
|------|-------|-------------------|---------------|----------------|----------------|
| **1** | May 5–9 | A1, A2, A3 | B1, B2 | C1, C2 | — |
| **2** | May 12–16 | A3, A4, A5 | B3, B4 | C3, C4 | — |
| | **May 17 – Jun 10** | **VACATION** | **VACATION** | **VACATION** | **VACATION** |
| **3** | Jun 11–13 | A6, A7, A8, A9 | B5, B6 | C5, C6 | — |
| **4** | Jun 16–20 | A10, A11 | B7 | C7, C8 | — |
| **5** | Jun 23–27 | — | — | — | D1, D2, D3 |
| **6** | Jun 30 – Jul 3 | — | — | — | D4, D5, D6 |
| **7** | Jul 7–11 | — | — | — | D6, D7, D8 |

---

*Generated: 2026-05-01 from [sidecar-implementation-design.md](sidecar-implementation-design.md) and [sidecar-refactoring-plan.md](sidecar-refactoring-plan.md)*
