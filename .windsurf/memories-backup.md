# Cascade Memories & Configuration Backup

| | |
|---|---|
| **Purpose** | Snapshot of Cascade memories + an index of all IDE-config assets, so nothing is lost across an IDE update, owner change, or migration to another agent |
| **Created** | 2026-06-18 |
| **Created by** | Cascade AI (at user request) |
| **Scope note** | Rules and workflows are already git-tracked (see manifest below). The genuinely IDE-bound data is the **memory database** (entries created via `create_memory`), captured in §3 |

---

## 1. What Is Already Safe in Git

All `.windsurf/` configuration is committed to this repository and is
**not** gitignored. It survives any IDE version, vendor, or even a switch
to a different coding agent — it is plain markdown you control. Verified
inventory: **66 tracked files** (2 global-rules + 52 rules + 12 workflows).

The only thing *not* covered by git is the memory database, captured in §3.

---

## 2. Manifest of Git-Tracked Config

### 2.1 Global Rules (`.windsurf/global-rules/`)

| File | Role |
|------|------|
| `global_rules.md` | Authoritative cross-workspace behavioral contract (terminal safety, markdown formatting) |
| `README.md` | Notes on the global-rules folder |

### 2.2 Top-Level Rules (`.windsurf/rules/`)

| File | Role |
|------|------|
| `CRITICAL.md` | Master checklist — consulted before every action |
| `dead-code.md` | Dead-code policy |
| `getting-started.md` | Onboarding pointer |
| `github-sync.md` | GitHub sync guidance |

### 2.3 Cascade Behavior (`.windsurf/rules/cascade/`)

| File | Role |
|------|------|
| `auto-run-policy.md` | When commands may auto-run |
| `behavior.md` | Reasoning/interaction + industry-best-practice mandate |
| `golden-file-policy.md` | Golden files immutable without explicit approval |
| `terminal-safety.md` | Command-length, anti-hang, output limits |

### 2.4 Infrastructure (`.windsurf/rules/infrastructure/`)

| File | Role |
|------|------|
| `README.md` | Infra rules overview |
| `active-profile.md` | Active EC2/cloud profile pointer |
| `cloud-shutdown.md` | Shutdown discipline |
| `docker-rules.md` | Docker build/run rules |
| `ec2-operations.md` | EC2 operational rules |
| `github-rulesets.md` | Branch-protection ruleset config |
| `go-sdk-version.md` | Go SDK pinning |
| `toolchain-versions.md` | Toolchain version pins |
| `virtual-environment.md` | `.venv` usage rules |
| `templates/aws-ec2.md` | AWS EC2 profile template |
| `templates/digitalocean.md` | DigitalOcean template |
| `templates/local-linux.md` | Local Linux template |

### 2.5 Project (`.windsurf/rules/project/`)

| File | Role |
|------|------|
| `code-standards.md` | Cross-language code standards |
| `golden-file-changelog.md` | Golden-file changelog rules |
| `golden-spdx-regression.md` | SPDX regression gate |
| `bisbom-rules.md` | Bisbom-specific rules |
| `output-binaries.md` | `output_binaries` config rules |
| `pre-commit.md` | Pre-commit verification gate |
| `project-context.md` | Project context |
| `release-builds.md` | Release-build policy |
| `runtime-timing.md` | Runtime timing capture |
| `spdx-relationship-types.md` | SPDX relationship type imports |
| `stable-tags.md` | Pinned release tags for analyzed repos |
| `supported-languages.md` | Supported language matrix |
| `upstream-pinning.md` | Upstream tool pinning (bomsh) |

### 2.6 Quality (`.windsurf/rules/quality/`)

| File | Role |
|------|------|
| `README.md` | Quality rules overview |
| `best-practices.md` | General best practices |
| `ci-workflow-standards.md` | CI/CD workflow standards |
| `design-principles.md` | Design principles + anti-patterns |
| `markdown-formatting.md` | Markdown formatting rules |
| `security.md` | Security standards (OWASP/CWE) |
| `testing-standards.md` | Testing standards + coverage thresholds |
| `lang/c-cpp.md` | C/C++ specifics |
| `lang/go.md` | Go specifics |
| `lang/java.md` | Java specifics |
| `lang/python.md` | Python specifics |
| `lang/rust.md` | Rust specifics |

### 2.7 Workflow Rules (`.windsurf/rules/workflow/`)

| File | Role |
|------|------|
| `build-documentation.md` | Build-doc requirements |
| `drawio-png-export.md` | Draw.io + PNG export rule |
| `pr-workflow.md` | PR workflow |
| `regression-gate.md` | Regression gate |
| `stash-discipline.md` | Git stash discipline |
| `sync-results.md` | Sync results after remote runs |
| `versioning.md` | Versioning rules |

### 2.8 Slash-Command Workflows (`.windsurf/workflows/`)

| File | Slash command |
|------|---------------|
| `add-repo.md` | `/add-repo` |
| `browse-ec2-files.md` | `/browse-ec2-files` |
| `cisco-lab-proxy.md` | `/cisco-lab-proxy` |
| `docker-build.md` | `/docker-build` |
| `ec2-provision.md` | `/ec2-provision` |
| `ec2-start.md` | `/ec2-start` |
| `first-time-setup.md` | `/first-time-setup` |
| `github-init.md` | `/github-init` |
| `merge-pr.md` | `/merge-pr` |
| `run-analysis.md` | `/run-analysis` |
| `run-comparison.md` | `/run-comparison` |
| `setup-environment.md` | `/setup-environment` |

---

## 3. Memory Database Entries (the IDE-bound data)

These are entries created via `create_memory`. They live in Cascade's
memory store, **not** in git, so they are the real loss risk. Captured
here verbatim.

### 3.1 Next Session — Complete Java Golden Re-Eval + Testapp

| | |
|---|---|
| **ID** | `4d0020e5-dff6-402a-b6f0-272477110261` |
| **Tags** | `next_session`, `java`, `golden_files`, `bomsh_java`, `phase_isolation`, `ec2` |

Content:

> Context: PR #189 (`feat/bomsh-java-fast-hashing`) is MERGED to main. It
> adds pure-Python fast-path for bomsh Java treedb
> (`docker/patches/bomsh_java_fast_io.py`, `apply_fast_io.py`,
> `fast_classreader`, `apply_fast_javap`), pins bomsh via
> `ARG BOMSH_COMMIT`, adds Maven `archive.apache.org` fallback, and wires
> patches into both Docker stages. EC2 image already rebuilt with these
> patches.
>
> Validated so far (sidecar mode, EC2): dependency-check (treedb
> 244s -> 19.5s, ~12x; recovered the cli JAR `dependency-check-9.2.0`
> SBOM that old javap path dropped) and spring-boot (structurally
> identical, javac 21.0.10 -> 21.0.11 env bump only). Their golden files
> were updated (user-approved) and compare clean.
>
> TODO when user returns (long weekend):
>
> 1. Re-run ALL remaining Java repos in sidecar mode on EC2 to complete
>    the evaluation: bc-java, checkstyle, crawler4j, jsoup,
>    logging-log4j2. (dependency-check + spring-boot already done.) Run
>    one at a time, sync `output/` locally, compare to
>    `tests/golden/spdx/java/<repo>` with `scripts/compare_golden.py`.
>    These 5 goldens still carry javac 21.0.10 and the OLD
>    (non-deterministic) file ordering.
> 2. After all are run + compared: it is VERY LIKELY all Java golden
>    files will be replaced due to the improvements (deterministic sorted
>    ordering via `find_suffix_files`, recovered JARs, javac 21.0.11).
>    Per golden-file policy, report ALL diffs and get explicit user
>    approval before updating any golden. Then produce a TABLE evaluation
>    of ALL Java runs showing as much speed-increase detail as possible
>    (per-repo treedb step before/after, dep_tree time, total
>    before/after, % improvement). Pull old timings from prior
>    `output/runtime/java/<repo>` runs and new `adg_substeps.json`.
> 3. Run against `https://github.com/tedg-dev/bisbom-java-testapp` (add
>    to `app/config.yaml` via `/add-repo` first).
>    3b. IMPORTANT: `bisbom-java-testapp` has problems because COMPLETE
>    ISOLATION between Phase 1 and Phase 2 was not implemented correctly.
>    See `docs/deep-dive/phase-isolation-build-time-analysis.md` and
>    related phase-isolation docs before/while running it.
>
> EC2: instance `i-02ef4bf118d6bae90`, profile `ted-admin`, alias
> `bisbom-build`, repo path `/home/ubuntu/bisbom-gen`. Stopped for
> the long weekend; restart via `/ec2-start`. `duo-sso --profile
> ted-admin` to re-auth (~1hr expiry).

---

## 4. Honest Limitation + Manual Full Export

This backup captures every memory currently surfaced in Cascade's working
context. Cascade has **no tool to enumerate the entire memory database**,
so older entries from prior conversations may exist that are not shown
here. To guarantee a complete export before any IDE update:

1. Open the IDE's Memories panel (Windsurf: Cascade settings → Memories,
   or the Memories management view).
2. Review the full list and copy any entries not already captured in §3
   into this file.
3. Commit the update.

Keeping this file current before any IDE migration ensures all rules,
workflows, and memories are preserved in git regardless of what happens
to the IDE.
