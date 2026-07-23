# Q4FY26 Sidecar — GitHub Issues by Phase & Track

| | |
|---|---|
| **Start date** | 2026-05-05 (Monday) |
| **Q4FY26 scope** | Phase 1 (Java pilot) + Phase 2 (C/C++ pilot) |
| **Working weeks** | 7 weeks across May 5 – July 11, 2026 |
| **Vacation** | **May 17 – June 10** (no work scheduled) |
| **Total issues** | 30 work items + 4 tracking epics |
| **Milestones** | [Phase 1: Java Pilot Ready](https://github.com/tedg-dev/omnibor-analysis/milestone/1) (Jun 20) · [Phase 2: C/C++ Pilot Ready](https://github.com/tedg-dev/omnibor-analysis/milestone/2) (Jul 11) |
| **Schedule detail** | [q4fy26-implementation-schedule.md](q4fy26-implementation-schedule.md) |
| **Source docs** | [sidecar-implementation-design.md](../_archived/design-evolution/sidecar-implementation-design.md), [sidecar-refactoring-plan.md](../_archived/design-evolution/sidecar-refactoring-plan.md) |

> **Modes note (historical):** This is a point-in-time Q4FY26 issue plan that
> treats standalone as the then-current baseline being migrated to sidecar.
> **Sidecar is now the only supported mode**; standalone is deprecated
> (initial implementation, ~1% embedded corner case). Read the standalone
> references below as that migration context, not as a current option.

---

## Phase 1: Infrastructure + Java Pilot (Weeks 1–4)

| | |
|---|---|
| **Weeks 1–2** | May 5–16 (pre-vacation) |
| **Vacation** | May 17 – June 10 — no work scheduled |
| **Weeks 3–4** | June 11–20 (post-vacation) |

**Goal:** Java sidecar mode production-ready on RHEL. No `SYS_PTRACE`
required. Package resolution works on Ubuntu, RHEL, and Alpine.

Three parallel tracks with no inter-track dependencies until Week 4
integration testing.

---

### Phase 1 / Track A: Package Resolver Abstraction

**Epic:** [#129](https://github.com/tedg-dev/omnibor-analysis/issues/129)
· **Branch:** `feat/package-resolver` · **Effort:** ~9 days

> **Why first:** Blocks ALL enterprise deployment. Pipeline hardcodes
> `dpkg`/`pkg:deb/ubuntu/`. On RHEL, every metadata call fails silently.

| Issue | Title | Est. | Week | Depends On |
|-------|-------|------|------|-----------|
| [#95](https://github.com/tedg-dev/omnibor-analysis/issues/95) | [A1] Create PackageResolver ABC | 0.5d | W1 | — |
| [#96](https://github.com/tedg-dev/omnibor-analysis/issues/96) | [A2] Implement DpkgResolver | 1d | W1 | #95 |
| [#97](https://github.com/tedg-dev/omnibor-analysis/issues/97) | [A3] Implement RpmResolver | 1.5d | W1–2 | #95 |
| [#98](https://github.com/tedg-dev/omnibor-analysis/issues/98) | [A4] Implement ApkResolver | 1d | W2 | #95 |
| [#99](https://github.com/tedg-dev/omnibor-analysis/issues/99) | [A5] Implement auto_detect_resolver() | 0.5d | W2 | #96, #97, #98 |
| | **— VACATION: May 17 – Jun 10 —** | | | |
| [#100](https://github.com/tedg-dev/omnibor-analysis/issues/100) | [A6] Refactor collect_metadata.py | 1d | W3 | #96, #99 |
| [#101](https://github.com/tedg-dev/omnibor-analysis/issues/101) | [A7] Refactor collect_dynamic_libs.py | 0.5d | W3 | #96, #99 |
| [#102](https://github.com/tedg-dev/omnibor-analysis/issues/102) | [A8] Refactor resolver.py PURL generation | 1d | W3 | #99 |
| [#103](https://github.com/tedg-dev/omnibor-analysis/issues/103) | [A9] Refactor pipeline/validator.py | 0.5d | W3 | #99 |
| [#104](https://github.com/tedg-dev/omnibor-analysis/issues/104) | [A10] RPM integration testing (RHEL 8/9) | 1d | W4 | #97, #100, #102 |
| [#105](https://github.com/tedg-dev/omnibor-analysis/issues/105) | [A11] Alpine integration testing | 0.5d | W4 | #98, #100, #102 |

---

### Phase 1 / Track B: Java dep:tree Optimization

**Epic:** [#130](https://github.com/tedg-dev/omnibor-analysis/issues/130)
· **Branch:** `feat/java-dep-tree` · **Effort:** ~7.5 days

> **Why:** Java already works via strace, but enterprise security blocks
> `SYS_PTRACE`. dep:tree removes this last privilege requirement.

| Issue | Title | Est. | Week | Depends On |
|-------|-------|------|------|-----------|
| [#106](https://github.com/tedg-dev/omnibor-analysis/issues/106) | [B1] Create MavenDepTreeStrategy | 2d | W1 | — |
| [#107](https://github.com/tedg-dev/omnibor-analysis/issues/107) | [B2] Maven shade/assembly plugin detection | 1d | W1–2 | #106 |
| [#108](https://github.com/tedg-dev/omnibor-analysis/issues/108) | [B3] Create GradleDepTreeStrategy | 1.5d | W2 | — |
| [#109](https://github.com/tedg-dev/omnibor-analysis/issues/109) | [B4] Wire dep:tree strategies into Java pipeline | 1d | W2 | #106, #108 |
| | **— VACATION: May 17 – Jun 10 —** | | | |
| [#110](https://github.com/tedg-dev/omnibor-analysis/issues/110) | [B5] Integration test: jsoup Maven sidecar | 0.5d | W3 | #109 |
| [#111](https://github.com/tedg-dev/omnibor-analysis/issues/111) | [B6] Integration test: checkstyle shade plugin | 0.5d | W3 | #109, #107 |
| [#112](https://github.com/tedg-dev/omnibor-analysis/issues/112) | [B7] Integration test: Java on RHEL | 1d | W4 | #109, #97 |

---

### Phase 1 / Track C: Config + Infrastructure

**Epic:** [#131](https://github.com/tedg-dev/omnibor-analysis/issues/131)
· **Branches:** `feat/config-mode-schema`, `feat/dual-mode-docker`
· **Effort:** ~8.5 days

> **Why:** All wrapper strategies need env support. All languages need
> mode selection. Enterprise teams need a sidecar Docker image.

| Issue | Title | Est. | Week | Depends On |
|-------|-------|------|------|-----------|
| [#113](https://github.com/tedg-dev/omnibor-analysis/issues/113) | [C1] CommandRunner.run() env support | 0.5d | W1 | — |
| [#114](https://github.com/tedg-dev/omnibor-analysis/issues/114) | [C2] Config schema mode selection | 1.5d | W1–2 | — |
| [#115](https://github.com/tedg-dev/omnibor-analysis/issues/115) | [C3] InterceptionStrategy ABC + PtraceStrategy | 1d | W2 | — |
| [#116](https://github.com/tedg-dev/omnibor-analysis/issues/116) | [C4] Refactor builder.py to use strategy | 1d | W2 | #113, #115 |
| | **— VACATION: May 17 – Jun 10 —** | | | |
| [#117](https://github.com/tedg-dev/omnibor-analysis/issues/117) | [C5] Path abstraction layer (14 hardcoded paths) | 1.5d | W3 | #114 |
| [#118](https://github.com/tedg-dev/omnibor-analysis/issues/118) | [C6] analyze.py --mode CLI flag | 0.5d | W3 | #114 |
| [#119](https://github.com/tedg-dev/omnibor-analysis/issues/119) | [C7] Dual-mode Dockerfile | 1.5d | W3–4 | — |
| [#120](https://github.com/tedg-dev/omnibor-analysis/issues/120) | [C8] End-to-end standalone regression gate | 1d | W4 | #116, #117, #118 |

---

### Phase 1 Milestone: Java Pilot Ready — June 20

- [ ] `analyze.py --repo jsoup --mode sidecar` produces valid SPDX on RHEL
- [ ] Package resolution works on Ubuntu, RHEL 8/9, Alpine 3.18+
- [ ] PURLs use correct scheme per distro
- [ ] `SYS_PTRACE` not required for Java sidecar builds
- [ ] Docker Hub has `omnibor-env:sidecar` and `omnibor-env:standalone` tags
- [ ] All existing standalone tests pass (zero regressions)
- [ ] Coverage ≥97%

---

## Phase 2: C/C++ Pilot (Weeks 5–7: June 23 – July 11)

**Goal:** C/C++ sidecar mode production-ready. Wrappers replace
bomtrace3. No `SYS_PTRACE` required.

**Prerequisite:** Phase 1 complete (Tracks A + C).

---

### Phase 2 / Track D: C/C++ Sidecar

**Epic:** [#132](https://github.com/tedg-dev/omnibor-analysis/issues/132)
· **Branch:** `feat/cc-sidecar` · **Effort:** ~7 days

> **Upstream dependency:** C/C++ wrapper binaries (`gcc-wrapper`,
> `g++-wrapper`, `ar-wrapper`, `ld-wrapper`) must be available from
> bomsh by Week 5 (Jun 23). Request upstream work to begin Week 1.
> The 3.5-week vacation provides extra lead time for upstream delivery.

| Issue | Title | Est. | Week | Depends On |
|-------|-------|------|------|-----------|
| [#121](https://github.com/tedg-dev/omnibor-analysis/issues/121) | [D1] Implement CcWrapperStrategy | 1.5d | W5 | #113, #115 |
| [#122](https://github.com/tedg-dev/omnibor-analysis/issues/122) | [D2] Wire CcWrapperStrategy into C/C++ pipeline | 0.5d | W5 | #121 |
| [#123](https://github.com/tedg-dev/omnibor-analysis/issues/123) | [D3] Refactor emitter.py compiler info | 1d | W5 | #121 |
| [#124](https://github.com/tedg-dev/omnibor-analysis/issues/124) | [D4] Integration test: curl sidecar Ubuntu | 1d | W6 | #122 |
| [#125](https://github.com/tedg-dev/omnibor-analysis/issues/125) | [D5] Integration test: ffmpeg sidecar multi-binary | 0.5d | W6 | #122 |
| [#126](https://github.com/tedg-dev/omnibor-analysis/issues/126) | [D6] Integration test: C/C++ sidecar on RHEL | 1d | W6–7 | #122, #97 |
| [#127](https://github.com/tedg-dev/omnibor-analysis/issues/127) | [D7] Wrapper chaining test: ccache + OmniBOR | 0.5d | W7 | #122 |
| [#128](https://github.com/tedg-dev/omnibor-analysis/issues/128) | [D8] End-to-end regression: all languages, both modes | 1d | W7 | #122, #109, #120 |

---

### Phase 2 Milestone: C/C++ Pilot Ready — July 11

- [ ] `analyze.py --repo curl --mode sidecar` produces valid SPDX
- [ ] `CC=`/`CXX=`/`AR=`/`LD=` injection works
- [ ] `SYS_PTRACE` not required for C/C++ sidecar builds
- [ ] Sidecar SPDX matches standalone within ≤5% package count
- [ ] Wrapper chaining with ccache verified
- [ ] All languages work in both modes (zero standalone regressions)

---

## Week-by-Week Summary

| Week | Dates | Track A | Track B | Track C | Track D |
|------|-------|---------|---------|---------|--------|
| **1** | May 5–9 | #95, #96, #97 | #106, #107 | #113, #114 | — |
| **2** | May 12–16 | #97, #98, #99 | #108, #109 | #115, #116 | — |
| | **May 17 – Jun 10** | **VACATION** | **VACATION** | **VACATION** | **VACATION** |
| **3** | Jun 11–13 | #100, #101, #102, #103 | #110, #111 | #117, #118 | — |
| **4** | Jun 16–20 | #104, #105 | #112 | #119, #120 | — |
| **5** | Jun 23–27 | — | — | — | #121, #122, #123 |
| **6** | Jun 30 – Jul 3 | — | — | — | #124, #125, #126 |
| **7** | Jul 7–11 | — | — | — | #126, #127, #128 |

---

## Quick Links

| Resource | Link |
|----------|------|
| **All Phase 1 issues** | [`label:phase-1`](https://github.com/tedg-dev/omnibor-analysis/labels/phase-1) |
| **All Phase 2 issues** | [`label:phase-2`](https://github.com/tedg-dev/omnibor-analysis/labels/phase-2) |
| **Track A epic** | [#129](https://github.com/tedg-dev/omnibor-analysis/issues/129) |
| **Track B epic** | [#130](https://github.com/tedg-dev/omnibor-analysis/issues/130) |
| **Track C epic** | [#131](https://github.com/tedg-dev/omnibor-analysis/issues/131) |
| **Track D epic** | [#132](https://github.com/tedg-dev/omnibor-analysis/issues/132) |
| **Milestone 1** | [Phase 1: Java Pilot Ready](https://github.com/tedg-dev/omnibor-analysis/milestone/1) |
| **Milestone 2** | [Phase 2: C/C++ Pilot Ready](https://github.com/tedg-dev/omnibor-analysis/milestone/2) |
| **Detailed schedule** | [q4fy26-implementation-schedule.md](q4fy26-implementation-schedule.md) |

---

*Generated: 2026-05-01 from sidecar design documents*
