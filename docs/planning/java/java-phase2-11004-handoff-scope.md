# #11004 — Java Phase 2 SBOM Output & Hand-Off Contract (omnibor-analysis side)

|  |  |
|---|---|
| **Inferred JIRA/issue ID** | #11004 (mapping inferred from repo structure; issue tracker currently unavailable) |
| **Parent** | Java Phase 2: Generate SBOMs From Phase 1 Metadata Without the Source Tree |
| **Predecessor** | #11003 — generate Java SBOMs from Phase 1 metadata (PR `tedg-dev/omnibor-analysis#194`) |
| **Charter** | Us (the USER + Cascade): Phase 1 + Phase 2 omnibor-analysis work **only** |
| **Author** | Ted G. |
| **Drafted** | 2026-06-26 (Cascade) |
| **Status** | Draft scope — for review |

---

## Charter Constraint (decisive)

"Our charter" = **us (the USER + Cascade)** — the actors doing this work,
not a separate team. We own **Phase 1 (interception/capture)** and **Phase 2
(SBOM generation)** in omnibor-analysis — full stop.

A **different team** owns the **S3 bucket** side and **how the Phase 2
output integrates/works with Corona** — which most likely includes the
Phase2<->Corona hand-off/integration contract itself, not just transport
and auth.

Therefore this sub-issue ("Deliver Java SBOMs to Corona") is **most likely
the other team's**. Our deliverable ends at **producing the Phase 2 SBOM
output** in omnibor-analysis — which #11003 already does. The items below
are a **candidate** in-charter remainder **only if** the USER confirms any
of it is ours; otherwise our Java Phase 1/Phase 2 work is complete at
#11003.

---

## What I Believe #11004 Is (re-scoped)

The original sub-issue (2) was "Deliver Java SBOMs to Corona." With delivery
owned elsewhere, the in-charter remainder is the **Phase 2 output and
hand-off contract**:

1. **Define the Java Phase 2 output artifact set** — exactly which files
   Phase 2 emits per build, their naming, and directory layout (the
   `_build` and `_analyzed` SPDX per JAR already produced today).
2. **Emit a machine-readable hand-off manifest** — a small index file the
   delivery team consumes, listing each produced SBOM, the artifact it
   describes (JAR), its digest (SHA-256 / GitOID), the source commit SHA,
   and a build identifier.
3. **Make the output location config-driven** — written to a configurable
   path (no hardcoded values), produced **solely from Phase 1 metadata**
   (consistent with #11003 — no source tree).
4. **Document the boundary contract** — a short spec so the delivery team
   knows the format and location; we do not implement transport or auth.
5. **Prove it end-to-end** — given only the Phase 1 manifest, Phase 2
   produces the complete hand-off set; verified against the local golden
   baseline.

---

## Explicitly Out of Scope (other team owns)

- The Corona intake mechanism (S3 bucket vs API), its data model, and the
  product/release/image pathing inside Corona.
- The CI/CD-to-Corona **authentication / authorization** model.
- Any network transport, upload client, or retry/delivery semantics.
- Non-Java languages (tracked under the shared SI-5).

---

## User Story

As a release engineer whose Java builds run Phase 1 and Phase 2 on separate
machines,

I want Phase 2 to write a complete, well-specified SBOM artifact set plus a
hand-off manifest to a known location,

so that the delivery team can ingest it into the central SBOM system without
needing the source tree or any omnibor-analysis internals.

---

## Acceptance Criteria

- Given a Phase 2 run from Phase 1 metadata only, when it completes, then it
  writes the defined SBOM artifact set (`_build` + `_analyzed` per JAR) to a
  config-driven output location.
- Given that output, when Phase 2 finishes, then it also writes a
  machine-readable hand-off manifest listing each SBOM, the JAR it
  describes, the artifact digest, the source commit SHA, and a build id.
- Given the hand-off manifest, when the delivery team reads it, then every
  referenced file exists at the stated relative path (self-consistent set).
- Given no source tree is present, when the set is produced, then nothing is
  read from the build workspace (consistent with #11003).
- Given the boundary, when documented, then transport/auth/Corona specifics
  are explicitly marked as out of scope (owned by the delivery team).
- Given the change is complete, when verified locally, then it meets project
  gates (import, `flake8`, `pytest`, coverage thresholds) and the SBOMs
  match the local golden baseline.

---

## Proposed Deliverables

- A Phase 2 output-writer/manifest module (generic, config-driven) — no
  language- or repo-specific logic.
- Config keys for the output location and build/release identifiers.
- A short boundary-contract doc (`docs/deep-dive/`) describing the artifact
  set + manifest schema for the delivery team.
- Unit tests: manifest correctness, digests, missing-input handling,
  config-driven path resolution.

---

## Open Questions / Assumptions

- **ID binding unverified** — that this sub-issue is literally #11004 is
  inferred from the repo's two-sub-issue structure; confirm when the issue
  tracker is reachable.
- **Manifest schema** — should the hand-off manifest follow a format the
  delivery team already expects? That detail lives in the (currently
  unavailable) integration wiki. Until confirmed, propose a minimal,
  standards-aligned JSON index and let the delivery team adjust.
- **Possible alternative** — if "deliver to Corona" transfers **entirely**
  to the other team, our Java Phase 1/Phase 2 charter may already be
  complete with #11003 (pending PR review), and #11004 would not be ours.
  Confirm ownership before implementation.

---

## Relationship to #11003

#11003 made Phase 2 **generate** Java SBOMs from Phase 1 metadata without
the source tree. #11004 makes Phase 2 **package and hand off** those SBOMs
at a documented boundary — the last omnibor-analysis step before the
delivery team takes over.
