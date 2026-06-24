# Sub-Issue Drafts — Build-Based SBOM Capture & Delivery

| | |
|---|---|
| **Parent issue** | TBD — to be assigned by the user |
| **Author** | Ted G. |
| **Drafted** | 2026-06-23 (Cascade) |
| **Status** | Draft — ready to attach under the chosen parent issue |
| **Scope** | **Multi-language — NOT C/C++ only.** SI-1 and SI-2 are C/C++-specific; SI-3 and SI-5 apply across languages; SI-4 spans Java, C/C++, Rust, and Go. See the **Applies to** tag on each sub-issue. |

---

## Conventions

- **Template:** standard User Story (`As a … I want … so that …`) with
  explicit **Acceptance Criteria**.
- **Granularity:** tasks are **consolidated** so each sub-issue covers
  **at least 2 days of AI work**. Small related tasks are grouped rather
  than split into separate issues.
- **Estimates** are in **AI-work days** (Cascade effort), not human
  engineering days, and are rough order-of-magnitude pre-grooming.

---

## SI-1 — Agree on how we observe C/C++ builds without changing them

**Applies to:** C/C++ builds

**Estimate:** ~2 AI-days

**User Story**

As a platform architect,
I want a clear, agreed approach for capturing the components of a C/C++
build without changing how teams build their software,
so that product teams can adopt SBOM generation with no disruption to their
existing build pipelines.

**Acceptance Criteria**

- Given the design is complete, when a platform architect reviews it, then
  it describes a primary approach plus fallbacks and confirms that none of
  them require changes to build commands, build settings, or CI
  configuration.
- Given each proposed approach, when it is reviewed, then it states what it
  covers, its effect on build time, and its limitations.
- Given the earlier proposal that required build changes, when the two are
  compared, then the new design explains why it is preferred and closes
  that gap.

---

## SI-2 — Automatically capture C/C++ software components during a normal build

**Applies to:** C/C++ builds

**Estimate:** ~3 AI-days

**User Story**

As a product build team,
I want my C/C++ builds to be observed automatically so their software
components are captured,
so that I receive a complete and accurate bill of materials without
changing the way I build.

**Acceptance Criteria**

- Given a standard C/C++ build, when it runs with observation enabled, then
  the components it produces and consumes are captured with no change to
  the build command.
- Given a build the primary method cannot observe, when it runs, then the
  system degrades gracefully and never causes the build to fail.
- Given an observed build, when its bill of materials is produced, then it
  matches the result of the existing trusted method.
- Given a typical build, when observation is enabled, then build time
  increases by no more than a few percent.

---

## SI-3 — Extend automatic capture to self-contained (statically linked) builds

**Applies to:** Any language that produces self-contained binaries (mainly C/C++ and Go)

**Estimate:** ~3 AI-days

**User Story**

As a product build team that ships self-contained binaries,
I want those builds captured as well,
so that statically linked software is covered by SBOMs just like everything
else.

**Acceptance Criteria**

- Given a build that produces self-contained binaries, when it runs, then
  its components are captured even though the primary method cannot observe
  it.
- Given such a build, when its bill of materials is produced, then it
  matches the trusted baseline.
- Given this capability runs at the system level, when it is deployed, then
  its operating requirements and permissions are documented for
  operations.

---

## SI-4 — Generate SBOMs from captured build data without needing the original workspace

**Applies to:** All languages — Java, C/C++, Rust, Go

**Estimate:** ~4 AI-days

**User Story**

As a release engineer,
I want SBOMs to be generated from captured build evidence alone,
so that we can produce SBOMs in modern CI/CD pipelines where the build and
reporting steps run on different machines and the original workspace is
discarded.

**Acceptance Criteria**

- Given a completed build, when the original source workspace is removed,
  then a complete SBOM can still be generated from the captured evidence
  alone.
- Given the same project, when its SBOM is generated this way, then it is
  identical to the SBOM produced with the workspace still present.
- Given a pipeline that builds on one machine and reports on another, when
  it runs, then SBOM generation needs nothing from the build machine
  except the captured evidence.
- Given any supported language, when its SBOM is generated, then the result
  is verified against the trusted baseline.

---

## SI-5 — Deliver build evidence to the central SBOM system (Corona)

**Applies to:** All languages

**Estimate:** ~2 AI-days

**User Story**

As a release manager,
I want captured build evidence delivered automatically to our central SBOM
system,
so that every product release has a discoverable, correctly filed SBOM
without manual steps.

**Acceptance Criteria**

- Given a build that has completed, when its evidence is ready, then it is
  delivered to the central SBOM system automatically.
- Given delivered evidence, when it arrives, then it is filed under the
  correct product, release, and image.
- Given the delivery path, when security reviews it, then the
  authentication and authorization model is documented and approved.
- Given existing company patterns for this kind of intake, when the design
  is produced, then it reuses them rather than inventing a new mechanism
  (see the
  [integration wiki](https://github.com/CiscoSecurityServices/gambit/wiki/Omnibor-Build-Based-SBOM-Integration)).

---

## Consolidation Note

Consolidated from an initial 10 fine-grained items into 5 sub-issues, each
covering at least two days of work:

| Sub-issue | Covers |
|-----------|--------|
| SI-1 | Agreeing the approach for observing C/C++ builds |
| SI-2 | Building the primary C/C++ capture, with fallback |
| SI-3 | Extending capture to self-contained builds |
| SI-4 | Generating SBOMs from captured data, and proving it works |
| SI-5 | Delivering evidence to the central SBOM system |

If the total must stay under two weeks, SI-3 (extending capture to
self-contained builds) is the largest and most deferrable item.
