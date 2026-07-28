# #11004 — A2 Implementation Plan: Java Phase 2 Output Set + Hand-Off Manifest

|  |  |
|---|---|
| **Issue** | `#11004` (A2), sub-issue of `#11002` (Java Phase 2 Main) |
| **Predecessor** | `#11003` (A1) — Phase 2 generates SBOMs from Phase 1 metadata (PR `tedg-dev/bisbom-gen#194`, merged) |
| **Scope doc** | `docs/planning/java/java-phase2-11004-handoff-scope.md` |
| **Status** | Ownership RESOLVED by USER 2026-07-09; boundary-contract doc elevated to top priority |
| **Drafted** | 2026-07-08 (Cascade), captured from session |
| **Revised** | 2026-07-09 — USER review: `#11004` confirmed ours (implementation sub-issue of `#11002`); deliver-to-Corona (A7/SI-5) is the other team's; boundary contract prioritized first; added `bisbom-java-testapp` currency audit |

---

## Grounding in current code

Phase 2 Java SBOM generation lives in `_generate_java_binary_spdx`, which
writes `{jar}_analyzed.spdx.json` and `{jar}_build.spdx.json` into
`spdx_dir = output_dir/spdx/{lang}/{repo}/{run_ts}`
(`app/pipeline/lang_runners.py:439-443`, `:592-614`). The Phase 1 manifest
pattern to mirror on the output side is `app/pipeline/manifest.py:45-117`
(`write_manifest`, `read_manifest`, `_compute_gitoids`, `MANIFEST_VERSION`,
`MANIFEST_FILENAME`). A2 mirrors that versioned-manifest pattern on the
**output** side.

---

## Milestone 0 — Ownership (RESOLVED 2026-07-09)

Resolved by the USER during review:

- `#11002` (and the other Mains `#11005`, `#11008`) are **architecture /
  design goal** issues owned by the USER — **not** implementation issues.
  Implementation happens **only** in sub-issues.
- `#11004` is the **A2 implementation sub-issue** of `#11002`, therefore it
  **is ours**. It covers producing the Phase 2 **output artifact set +
  hand-off manifest + producer-side boundary contract**.
- **Out of charter (other team):** delivering to Corona (crosswalk **A7 /
  SI-5**, "Deliver Java build evidence to Corona") plus the Corona intake
  model, transport, and auth. We stop at emitting the documented artifact
  set — we do not implement delivery.

No longer a blocker. **Revised sequencing:** M3 (boundary contract) first,
then M1 -> M2 -> M4 -> M4b -> M5.

---

## Milestone 1 — Hand-off manifest module (generic, config-driven)

- **New module** `app/pipeline/handoff.py` — deliberately
  **language-agnostic** (so C/C++ Main B reuses it), mirroring
  `manifest.py` style: `write_handoff_manifest(...)`,
  `read_handoff_manifest(...)`, `HandoffError`, versioned constant
  `HANDOFF_VERSION = "1.0"`, filename `sbom_handoff_manifest.json`.
- **DRY refactor**: extract the SHA-256 / GitOID digest helper (today
  `_compute_gitoids` in `manifest.py`) into a shared `app/pipeline/digests.py`
  used by both manifests — no duplication.
- **Schema** (minimal, standards-aligned JSON index, per scope doc):

| Field | Meaning |
|---|---|
| `version`, `generated_ts`, `mode` | manifest metadata |
| `repo_name`, `language`, `commit_sha`, `vcs_uri`, `build_id` | provenance (`build_id` config-driven) |
| `sboms[]` | one entry per JAR |
| `sboms[].artifact` | relative path to the JAR |
| `sboms[].artifact_sha256`, `.artifact_gitoid` | artifact digests |
| `sboms[].sbom_build`, `.sbom_analyzed` | relative SBOM paths |
| `sboms[].sbom_build_gitoid`, `.sbom_analyzed_gitoid` | SBOM digests |

All paths are **relative** to the manifest, so the emitted set is
self-consistent and relocatable.

---

## Milestone 2 — Phase 2 integration

- Emit the manifest at the **end of Phase 2 Java generation**:
  `_generate_java_binary_spdx` already knows every `analyzed_path` /
  `build_path` and the per-JAR relative paths — collect them and call
  `write_handoff_manifest` (or do it in `run_java_phase2` after generation).
- **Config-driven output location** via a new `handoff` config section
  (output dir + `build_id` / release id); no hardcoded paths.
- **Produced solely from Phase 1 metadata** — assert no source-tree reads
  (consistent with `#11003`).

---

## Milestone 3 — Boundary-contract doc — TOP PRIORITY, DO FIRST

- New `docs/sidecar/java/phase2-handoff-contract.md`: artifact-set layout +
  manifest schema for the delivery team; explicitly marks transport / auth /
  Corona specifics **out of scope**.
- **Deliver this FIRST as a standalone high-priority docs PR.** Peer team
  members are actively building the Corona side of Phase 2 and need the
  producer-side contract (artifact set + manifest schema) now.
- **Design-first:** agree the schema with the peer team before/while
  implementing M1-M2 so the code conforms to the published contract. The
  contract may ship ahead of the code.

---

## Milestone 4 — Tests (`tests/test_handoff.py`)

- Manifest correctness (every emitted SBOM is listed).
- Digest correctness (`sha256` + `gitoid` match the bytes).
- Missing-input handling (loud failure on the enterprise no-source path).
- Config-driven path resolution.
- Self-consistency (every referenced file exists at its stated path).
- No-source-tree assertion.
- Coverage gates: **>=95% per file, >=97% overall**.

---

## Milestone 4b — `bisbom-java-testapp` currency audit

The USER owns `tedg-dev/bisbom-java-testapp` and requires it to ALWAYS
exercise the latest architecture (refactors, bug fixes, features).

Verified state (2026-07-09):

- `config.yaml` pins `branch: main` (intentionally tracks latest; the sole
  repo not on a stable tag — acceptable for a controlled system-test app).
- Most recent run: `output/spdx/java/bisbom-java-testapp/2026-06-29_2312/`
  (post-`#11003`); golden baseline exists (`_analyzed` + `_build`).
- **Coverage gap:** the app is **Maven-only** (`mvn package`); it does not
  exercise the Gradle capture path (`#11006` / A4).

Actions:

- Re-run Phase 1 + Phase 2 (sidecar) on the latest `main` to confirm it
  still passes against golden after all merged work; report diffs (no
  auto-update; USER sign-off).
- Use it as the **A2 end-to-end system test** once the hand-off manifest
  exists (Milestone 5).
- Cannot verify the GitHub repo's own source coverage from here — confirm
  with the USER whether it should also cover Gradle and additional
  dependency scopes.

---

## Milestone 5 — Verify and PR

- **E2E**: from `phase1_manifest.json` only, run Phase 2 on a multi-module
  sample -> assert the complete hand-off set + manifest, then **compare
  SBOMs to the golden baseline** and report diffs (no auto-update; USER
  sign-off required).
- **Gates**: `import`, `flake8`, `pytest`, coverage.
- **Branch** `feat/java-phase2-handoff`; PR body references
  `Part of CiscoSecurityServices/gambit#11004`. Estimate ~1-2 days.

---

## Design principles honored

- Generic / config-driven — no repo- or language-specific branches.
- Reuses the existing versioned-manifest pattern (`manifest.py`).
- DRY digest utility shared between Phase 1 and Phase 2 manifests.
- Standards-aligned JSON index; relative, self-consistent paths.
- Golden gate stays human-approved (Cascade never updates goldens).

---

## Related open item (from the same session)

`#11003` (A1) is merged (PR `#194`) and sits **In Review** on the board;
there is **no code review owed** by the USER. The pending human action is
the **golden-diff sign-off** — `#11003`'s acceptance criterion enumerates
`_build` SBOM differences from the golden baseline for human review, and
per the golden-file policy only the USER approves them.
