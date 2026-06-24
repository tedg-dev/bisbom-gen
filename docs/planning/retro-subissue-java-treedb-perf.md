# Retro Sub-Issue — Faster SBOM generation for Java builds (already delivered)

| | |
|---|---|
| **Parent issue** | TBD — to be assigned by the user |
| **Type** | Retrospective (work already completed) |
| **Scope** | **Java builds only** (Maven and Gradle). |
| **Status** | DONE — merged & EC2-validated golden-clean (June 22, 2026) |
| **Delivering PRs** | #189 (primary), #187, #191 |
| **Author** | Ted G. |
| **Drafted** | 2026-06-23 (Cascade) |
| **Effort (actual)** | ~3 AI-days across analysis, implementation, EC2 validation |

---

## SI-R1 — Speed up SBOM generation for Java builds

**User Story**

As a build and release engineer,
I want SBOM generation for Java projects to run quickly,
so that adding software bill-of-materials reporting to our Java builds does
not noticeably slow down our pipelines.

**Background (Conversation)**

Timing on a real build host showed that, for Java projects, the SBOM step
was overwhelmingly dominated by a single slow stage that processed each
compiled component one at a time — accounting for roughly 78–99% of that
step's time on large projects. This made SBOM generation impractically slow
for big Java codebases and was the clear bottleneck to address.

**What was delivered**

The slow per-component stage — which repeatedly launched small external
helper programs for every compiled file — was replaced with fast built-in
processing. On a large project this removed on the order of tens of
thousands of external program launches. The improvement is applied to the
shared build tooling without forking it, and is locked to a known-good
version so behavior stays stable over time.

**Headline result:** SBOM generation for Java projects is now substantially
faster — the previously dominant stage dropped from roughly four minutes to
a matter of seconds on the projects measured — with no change to the
resulting SBOM. Full measurements are in
`docs/deep-dive/bomsh-java-performance-optimization.md`.

**Acceptance Criteria (Confirmation — all met)**

- Given a Java project, when its SBOM is generated, then the stage that was
  previously the dominant cost is now a minor part of the total time.
- Given the faster method, when its SBOM output is compared to the
  previously trusted output, then the two are identical — no loss of
  accuracy or completeness.
- Given the change, when it is validated on a range of representative Java
  projects on a real build host, then all produce identical, correct
  results.
- Given a future change in the underlying build tooling, when that tooling
  changes unexpectedly, then the build fails loudly rather than silently
  shipping unverified results.

**Known follow-ups (not part of this work)**

- A further speed-up that processes components entirely in memory is
  possible and has been deferred to a later change.
- One very large multi-module Java project remains slower in absolute
  terms simply because of its size; the improvement still applies.

**Engineering reference**

Delivered in PRs #189 (primary), #187, and #191. Full technical detail,
method, and measurements live in
`docs/deep-dive/bomsh-java-performance-optimization.md`.

---

## Note on the headline number

Avoid quoting a single blended "percent faster" figure: some raw build-time
comparisons were skewed by cached dependencies left over from earlier runs.
The most defensible statement is the one above — the previously dominant
stage went from roughly four minutes to seconds — because it reflects the
improvement directly.
