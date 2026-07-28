# Sub-Issue Drafts — C/C++ Sidecar Interception & Phase Isolation

| | |
|---|---|
| **Epic (Main B)** | C/C++ build-based SBOM capture and delivery (sidecar + phase isolation) — gambit **#11008** |
| **Higher-level user stories** | B1 **#11009**, B2 **#11010**, B3 **#11011**, B4 **#11012** (delivery to Corona is out of charter — #11013 closed, not planned) |
| **Author** | Ted G. |
| **Drafted** | 2026-07-23 (Cascade) |
| **Status** | **B1.1 (#11176) is In Development** (Walk 21) — the first work item (ratify tier model). B1.2 (#11177), B1.3 (#11178), and parent #11009 are `Ready`. B2–B4 (#11010–#11012) remain `Ready`; their work items are drafted, not yet created. Main A → B gate lifted (2026-07-24 — Java functionally complete). |
| **Scope** | **C/C++ only.** Static-build fallbacks (B3) also apply to Go; cross-language delivery is Main C. Sidecar-only; standalone (ptrace) is the deprecated ~1% escape hatch. |
| **Canonical design** | `../../sidecar/c-cpp/sidecar-design.md` (reconciled 2026-07-23); reference `../../sidecar/c-cpp/interception-strategies.md`; template precedent `../../sidecar/java/reference/inline-hashing-interception-design.md` (delivered, golden-clean) |

---

## How to read this doc

The four C/C++ **user stories** (B1–B4) already exist as gambit issues
(#11009–#11012) and are the *higher-level* stories. This doc decomposes each
into concrete **work-item sub-issues** (`B1.1`, `B1.2`, …), mirroring the
Java per-theme breakdown in `../java/phase1-build-speed-subissues.md`
(Main issue = user story; sub-issue = work item). The stable B1–B4 labels
and their #11009–#11012 mapping are unchanged.

### Conventions

- **Template:** User Story (`AS A … I WANT … SO THAT …`, keywords ALL CAPS)
  with **Acceptance Criteria** in Given/When/Then form.
- **Granularity:** each work item is a shippable deliverable of roughly
  1–3 AI-days; small related tasks are grouped, not split.
- **Estimates:** AI-work days (Cascade effort), rough pre-grooming.
- **Standing gate (every work item):** golden-clean validation on a real
  build host (EC2), the `regression-gate`, and multi-distro runs
  (Ubuntu/RHEL/Alpine). No item is "done" until it passes these. Golden
  files are never updated by Cascade — diffs are reported and work STOPS.

### Two priorities that constrain every C/C++ work item

1. **No change to the C/C++ build environment** — the only customer-visible
   change is a section added to the CI/CD YAML (two environment variables).
   The `Makefile`/`CMakeLists.txt`/build scripts and the build command are
   byte-for-byte unchanged.
2. **Minimal impact on the ephemeral CI/CD build step** — only exec/argv
   capture and per-unit inline hashing run in-band (target 1–3%, parallelizes
   with `-jN`). Treedb assembly, `ldd`/`readelf`, version detection, and SPDX
   run out-of-band (Phase 2 / post-build capture window).

---

## Current implementation state (ground truth)

| Component | State |
|---|---|
| `PtraceStrategy` (`bomtrace3`) standalone | Production — 6 repos (curl, ffmpeg, nmap, redis, openosc, node) |
| `CcWrapperStrategy` (`CC=`/`CXX=`/`AR=`/`LD=`) | Skeleton in `interception.py`, **not wired**; standalone-without-ptrace, **not sidecar** |
| `LdPreloadStrategy` / eBPF / audit (sidecar) | **Not implemented** — this doc's B2/B3 |
| `run_c_cpp_pipeline()` | Runs Phase 1 + Phase 2 sequentially, standalone only (no `mode=`) |
| `build()` in `builder.py` | **Already strategy-aware** (`instrument_command` → `(cmd, env)` → `generate_adg`) |
| `resolve_omnibor_cfg()` | **Already supports** nested `standalone`/`sidecar` config |
| `handoff.py` (Phase 2 hand-off manifest) | **Already language-agnostic** — reusable by C/C++ (B4.4) |

---

## B1 (#11009) — Agree how we observe C/C++ builds without changing them

**Higher-level user story (unchanged):** AS A platform architect, I WANT a
clear, agreed approach for capturing the components of a C/C++ build without
changing how teams build, SO THAT product teams adopt SBOM generation with
no disruption to their build pipelines.

### B1.1 — Ratify the interception tier model

**Estimate:** ~0.5 AI-days · **Priority:** High · **gambit:** #11176 —
In Development (Walk 21). Design reconciled in the canonical docs (2026-07-23).

**Deliverable:** Ratify `LD_PRELOAD` shim (primary) → node-level eBPF or
Linux audit (fallbacks) → per-repo `ptrace` (standalone escape hatch, NOT a
sidecar tier). `fanotify` is eliminated (no argv). `CC=`/`CXX=` wrappers are
standalone-without-ptrace, not sidecar.

**Acceptance Criteria**

- Given the tier model, when an architect reviews it, then it names one
  primary mechanism plus fallbacks and confirms none require changes to
  build commands, build files, or CI configuration.
- Given each tier, when reviewed, then it states coverage, build-time impact,
  static-binary support, and required capabilities.
- Given the earlier proposal that required build changes (`CC=` wrappers),
  when compared, then the doc explains why `LD_PRELOAD` is preferred and
  closes that gap.

**Design refs:** `sidecar-design.md` §2; `interception-strategies.md` §8.

### B1.2 — Deployment-model & injection-vector decision

**Estimate:** ~0.5 AI-days · **Priority:** High · **gambit:** #11177 — Ready

**Deliverable:** Document that the **ephemeral CI/CD build-step** is the
target, so injection is **two CI/CD-YAML env vars** (`LD_PRELOAD` + a
config-driven raw-logfile path) — the Java-proven vector — with the K8s
mutating webhook as an optional self-managed-cluster convenience only.
Kernel observers (eBPF/audit) require node-level infrastructure and are
therefore fallbacks, not the ephemeral default.

**Acceptance Criteria**

- Given the ephemeral CI/CD model, when the injection vector is chosen, then
  it is env-only (no build-command/build-file change) and works with no
  node-level capability or daemon.
- Given a self-managed cluster, when an alternative injection is documented,
  then the webhook path is clearly marked optional, not required.
- Given the two priorities, when the decision is reviewed, then it shows
  build-step overhead stays in-band-minimal (capture + inline hash only).

**Design refs:** `sidecar-design.md` §2.3; `../../sidecar/cicd-workspace-lifecycle.md`.

### B1.3 — Config schema decision (nested mode + per-repo override)

**Estimate:** ~0.5 AI-days · **Priority:** Medium · **gambit:** #11178 — Ready

**Deliverable:** Adopt the nested `omnibor: { standalone:, sidecar: }` config
for C/C++ (already supported by `resolve_omnibor_cfg()`), with a per-repo
`interception` override (`ld_preload` | `ebpf` | `audit` | `ptrace`) and a
config-driven raw-logfile path. No repo names in executable code.

**Acceptance Criteria**

- Given the nested config, when `--mode sidecar` runs, then the sidecar
  sub-key is auto-selected; standalone remains backward-compatible.
- Given a hermetic repo, when it sets `interception: ptrace`, then only that
  repo drops to standalone without affecting others.
- Given the schema, when reviewed, then no repo-specific logic exists in code
  (behavior is config-driven).

**Design refs:** `sidecar-design.md` §5.

---

## B2 (#11010) — Automatically capture C/C++ components during a normal build

**Higher-level user story (unchanged):** AS A product build team, I WANT my
C/C++ builds observed automatically so their software components are captured,
SO THAT I receive a complete, accurate bill of materials without changing how
I build.

### B2.1 — `libomnibor_intercept.so` `LD_PRELOAD` shim

**Estimate:** ~3 AI-days · **Priority:** High · **Critical path.**

**Deliverable:** A shared library that interposes `execve`/`posix_spawn`
(compiler/linker argv capture) and `close`/`rename` (artifact finalization),
computes git-blob `SHA-1` + `SHA-256` gitoid inline, and appends the **same
raw-logfile format** `bomtrace3` produces (so `bomsh_create_bom.py` is
unchanged). Extends the delivered Java shim scaffold
(`docker/shim/omnibor_java_intercept.c`). Fails open — never breaks the build.

**Acceptance Criteria**

- Given a normal C/C++ build with the shim preloaded, when each compile/link
  unit finalizes, then its argv and input/output GitOIDs are captured with no
  change to the build command.
- Given any internal shim error, when it occurs, then the real tool proceeds
  and the SBOM is reported incomplete — the build never fails.
- Given the captured raw logfile, when `bomsh_create_bom.py` runs on it, then
  the treedb is byte-identical to the `bomtrace3` standalone treedb.
- Given a `-jN` build, when the shim is active, then in-band overhead stays
  within a few percent.

**Design refs:** `sidecar-design.md` §2.3, §6.1; Java `inline-hashing-interception-design.md`.

### B2.2 — `LdPreloadStrategy` in `interception.py`

**Estimate:** ~1 AI-day · **Priority:** High

**Deliverable:** `instrument_command()` returns the build command
**unchanged** plus env only (`LD_PRELOAD` + config-driven raw-logfile path);
`generate_adg()` runs `bomsh_create_bom.py -r <raw_logfile> -b <bom_dir>`
(reusing `PtraceStrategy`'s ADG path). Reuse `prepare_capture_log()`.

**Acceptance Criteria**

- Given sidecar mode, when `instrument_command()` runs, then the returned
  command equals the input command and only env vars are added.
- Given a completed build, when `generate_adg()` runs, then it produces the
  treedb + ADG documents from the shim's raw logfile.
- Given both a compile-only and a link step, when captured, then inputs and
  outputs map correctly in the treedb.

### B2.3 — Wire strategy selection + `mode=` threading

**Estimate:** ~0.5 AI-days · **Priority:** High

**Deliverable:** Implement `_select_c_cpp_strategy(mode, repo_cfg)` (sidecar →
`LdPreloadStrategy`; per-repo `interception` override selects the tier; else
`None` = legacy `bomtrace3`); thread `mode=` through `run_c_cpp_pipeline()` →
`builder.build(strategy=...)` (plumbing already accepts it).

**Acceptance Criteria**

- Given `--mode sidecar`, when a C/C++ repo runs, then `LdPreloadStrategy`
  is selected and used by `build()`.
- Given standalone mode, when a repo runs, then the legacy `bomtrace3` path
  is unchanged (zero regression).
- Given a per-repo `interception` override, when set, then the matching tier
  is selected without repo-name branching in code.

### B2.4 — Ship the shim in the Docker sidecar image + CI/CD snippet

**Estimate:** ~0.5 AI-days · **Priority:** Medium

**Deliverable:** Build the shim in the Docker `standalone` stage, copy into
`sidecar`, install at `/opt/omnibor/lib/libomnibor_intercept.so`; document the
two-env-var CI/CD-YAML snippet (Jenkins/GitHub Actions).

**Acceptance Criteria**

- Given the sidecar image, when built, then the shim is present and loadable.
- Given the documented CI/CD snippet, when a team adds it, then only two env
  vars change and the build command is untouched.

### B2.5 — Unit tests + EC2 golden-clean validation (dynamic repos)

**Estimate:** ~1.5 AI-days · **Priority:** High

**Deliverable:** Unit tests for the strategy + selection; EC2 golden-clean run
across the 6 dynamically-linked C/C++ repos; raw-logfile/treedb byte-parity
vs `bomtrace3`.

**Acceptance Criteria**

- Given the test suite, when it runs, then it covers strategy selection,
  env-only instrumentation, ADG generation, and failure paths; coverage meets
  project thresholds.
- Given each dynamic C/C++ repo on EC2, when run in sidecar mode, then the
  SPDX is golden-clean at package and file level (diffs reported, not
  updated).

---

## B3 (#11011) — Extend capture to statically linked builds

**Higher-level user story (unchanged):** AS A product build team that ships
self-contained binaries, I WANT those builds captured as well, SO THAT
statically linked software is covered by SBOMs like everything else.

> **Applies to:** C/C++ and Go. Node-level observers require nodes you
> control; they are the fallback for the minority of builds `LD_PRELOAD`
> cannot see (static tools, musl/Alpine, `env -i`).

### B3.1 — eBPF node observer (Fallback A)

**Estimate:** ~3 AI-days · **Priority:** Medium · **Deferrable.**

**Deliverable:** A privileged node component loading BPF on
`sched_process_exec`, `sched_process_exit`, and `sys_enter_openat`; argv via
`/proc/PID/cmdline`; `sched_process_exit` doubles as build-completion
detection. Writes the same raw-logfile format.

**Acceptance Criteria**

- Given a statically-linked build on a controlled node, when eBPF observation
  is active, then components are captured though `LD_PRELOAD` cannot interpose.
- Given the observer, when its output is compared to the trusted baseline,
  then the SBOM matches (golden-clean).
- Given deployment, when documented, then required capabilities
  (`CAP_BPF`/`CAP_PERFMON` or `CAP_SYS_ADMIN`) and kernel floors are stated.

### B3.2 — Linux audit observer (Fallback B)

**Estimate:** ~2.5 AI-days · **Priority:** Medium · **Deferrable.**

**Deliverable:** An `execve` audit rule + reader that reconstructs the build
process tree (PPID) and extracts compiler/linker invocations; universal on
self-managed Linux (RHEL 7+, no `CAP_BPF`).

**Acceptance Criteria**

- Given a controlled node with the audit rule, when a static build runs, then
  its components are captured from full-argv audit records.
- Given system-wide audit noise, when the reader runs, then it filters to the
  build's process tree only.
- Given the SBOM produced, when compared to baseline, then it is golden-clean;
  required capability (`CAP_AUDIT_READ`, plus `CAP_AUDIT_CONTROL` unless the
  rule is pre-configured) is documented.

### B3.3 — Fallback selection + graceful degradation

**Estimate:** ~1 AI-day · **Priority:** Medium

**Deliverable:** Auto-detect capabilities and select the tier; degrade
gracefully (never fail the build); document the ops/caps matrix.

**Acceptance Criteria**

- Given a build `LD_PRELOAD` cannot see, when a fallback is available, then it
  is used automatically; when none is, then the build still succeeds and the
  gap is reported.

**Design refs:** `sidecar-design.md` §2.4; `interception-strategies.md` §§2–5.

---

## B4 (#11012) — Generate SBOMs from captured data without the original workspace

**Higher-level user story (unchanged):** AS A release engineer, I WANT SBOMs
generated from captured build evidence alone, SO THAT we can produce SBOMs in
CI/CD where build and reporting run on different machines and the workspace is
discarded.

### B4.1 — C/C++ phase split + manifest

**Estimate:** ~1.5 AI-days · **Priority:** High

**Deliverable:** Split `run_c_cpp_pipeline()` into `run_c_cpp_phase1()` /
`run_c_cpp_phase2()`; write/read `phase1_manifest.json`; support
`--phase build` / `--phase spdx`. Backward compatible when run as one pass.

**Acceptance Criteria**

- Given `--phase build`, when Phase 1 runs, then it writes a manifest
  enumerating the Phase-1 artifacts Phase 2 needs.
- Given `--phase spdx --manifest …`, when Phase 2 runs, then it reads paths
  from the manifest and touches no source tree.
- Given no `--phase`, when the pipeline runs, then behavior is identical to
  today.

### B4.2 — Binary-facts-in-Phase-1 pilot (no binary egress)

**Estimate:** ~1.5 AI-days · **Priority:** High

**Deliverable:** Run `bomsh_sbom.py` + `ldd`/`readelf` inside the Phase-1
capture window (binary present), emit the small per-artifact SPDX + metadata;
Phase 2 does only the metadata-driven merge/validate. Binaries never leave the
build host (CWE-200).

**Acceptance Criteria**

- Given a Phase-1 run, when binary-derived facts are captured, then hashes,
  ELF/`ldd` metadata, and ADG resolution are all recorded without shipping the
  binary anywhere.
- Given Phase 2, when it assembles SPDX, then it reads only captured metadata
  (no binary, no source tree).

**Design refs:** `sidecar-design.md` §4.2.

### B4.3 — Version pre-computation into the manifest

**Estimate:** ~0.5 AI-days · **Priority:** High

**Deliverable:** In Phase 1, run version detection over vendored dirs and
store `precomputed_versions` in the manifest; Phase 2 reads it instead of
scanning `configure.ac`/`CMakeLists.txt`/`#define`.

**Acceptance Criteria**

- Given vendored libraries, when Phase 1 completes, then their versions are in
  the manifest.
- Given Phase 2 with no source tree, when SPDX is generated, then versions
  come from the manifest and match the source-scan result.

### B4.4 — Reuse `handoff.py` for the C/C++ Phase 2 output contract

**Estimate:** ~0.5 AI-days · **Priority:** Medium

**Deliverable:** Emit `sbom_handoff_manifest.json` for C/C++ Phase 2 runs via
the existing language-agnostic `handoff.py` (per-artifact `sha256` + `gitoid`
from Phase 1, plus `build`/`analyzed` SPDX digests).

**Acceptance Criteria**

- Given a C/C++ Phase 2 run, when it finishes, then it writes a verifiable
  hand-off manifest via `handoff.py` with no C/C++-specific fork.

### B4.5 — Cross-host Phase 2 golden validation

**Estimate:** ~1 AI-day · **Priority:** High

**Deliverable:** Prove Phase 2 with the workspace removed produces
golden-clean SPDX across the C/C++ repos.

**Acceptance Criteria**

- Given a completed Phase 1 and a removed workspace, when Phase 2 runs, then a
  complete SBOM is produced from captured evidence alone and matches the SBOM
  produced with the workspace present.
- Given each C/C++ repo, when validated on EC2, then output is golden-clean
  (diffs reported, never updated).

---

## Delivery to Corona (Main C / #11013 — C/C++ slice)

C/C++ build-evidence delivery to Corona is **out of the C/C++ Phase 1/2
charter** and tracked under Main C (**#11013**), owned by the Corona / Phase
2-incorporation team — mirroring the Java delivery split (A7). Listed here for
traceability only; it is not a B-series work item.

---

## Sequencing & dependencies

| Work item | Depends on | Deferrable? |
|---|---|---|
| B1.1–B1.3 (design) | — | No — gates the rest |
| B2.1 (shim) | B1.1–B1.2 | No — **critical path** |
| B2.2–B2.4 (wiring/ship) | B2.1 (for E2E); design done for the rest | Partly parallel to B2.1 |
| B2.5 (validation) | B2.1–B2.4 | No |
| B3.1–B3.3 (fallbacks) | B2 | **Yes** — only for `LD_PRELOAD`-blind builds |
| B4.1–B4.5 (phase isolation) | B2 (manifest inputs) | No |

**Critical-path blocker:** B2.1 (the C/C++ shim). B2.2–B2.4 and B4.1/B4.3 can
proceed in parallel against the standalone golden path. B3 (kernel observers)
is deferrable to post-pilot.

**Gate reminder:** none of this starts until Main A (Java) is 100% complete
and tested (README priority rule). These are drafts; the matching gambit
sub-issues under #11009–#11012 are created only when B work begins.
