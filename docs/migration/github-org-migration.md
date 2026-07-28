# Migration Research: `tedg-dev/*` → `CiscoSecurityServices`

| | |
|---|---|
| **Audience** | Repo owner / platform engineer performing the migration |
| **Scope** | Move `tedg-dev/bisbom-gen` and `tedg-dev/bisbom-java-testapp` into the `CiscoSecurityServices` GitHub org |
| **Status** | Research complete — no migration commands executed |
| **Last updated** | 2026-07-28 |

> **Naming update (2026-07-28):** The Stage C repo renames from issue
> `CiscoSecurityServices/gambit#11194` are **already done on GitHub**. The
> `omnibor` -> `bisbom` decision resolved to the short product form, not the
> verbose `build-interception-sbom-*` names once floated in the issue table:
>
> | Old repo | New repo (current) |
> |---|---|
> | `tedg-dev/omnibor-analysis` | `tedg-dev/bisbom-gen` |
> | `tedg-dev/omnibor-java-testapp` | `tedg-dev/bisbom-java-testapp` |
>
> GitHub redirects the old URLs, but this doc uses the current `bisbom-*`
> names. Local git remotes still point at the old URL until updated (see 5.1).

---

## 1. Decisive finding — the native "Transfer" button will NOT work

`CiscoSecurityServices` is a **GitHub Enterprise Managed Users (EMU)** enterprise.
The evidence is conclusive:

- The repo-owning account `tedg-dev` gets **HTTP 404** on `orgs/CiscoSecurityServices` — it cannot even see the org, so it is not (and under EMU cannot become) a member.
- The org identity is `tedg_cisco` — the underscore-suffixed `shortcode_enterprise` username pattern that EMU forces on every account.
- The `tedg_cisco` token carries `admin:enterprise` and `write:network_configurations` — enterprise-level scopes.

GitHub's native repository transfer (`Settings` → `Danger Zone` → `Transfer`)
requires the **initiating account** (`tedg-dev`, the repo admin) to have
create-repo permission in the target org. Under EMU:

- External personal accounts **cannot be added to the enterprise at all**.
- Managed users **cannot own or pull in content from outside the enterprise**.

A personal-account → EMU-org transfer is therefore **not a supported path**.
Do not attempt the Transfer button — it either won't list the org or will be
rejected.

> **Why `gambit` migrated cleanly earlier:** that was an *org-to-org* move
> (`tedg-cisco` org → `CiscoSecurityServices`), both inside/into the
> enterprise. The two repos here live on a **personal** account, which is a
> different, harder case.

---

## 2. Recommended tool — GitHub Enterprise Importer (GEI)

GEI is GitHub's official, supported tool for exactly this path:
**GitHub.com (personal) → GitHub Enterprise Cloud**, on a repo-by-repo basis.
The supported-source list includes `GitHub.com`; the target
(`CiscoSecurityServices`) is GitHub Enterprise Cloud.

### What GEI migrates (high fidelity)

- Git history — all branches, tags, and commits (attribution preserved)
- Pull requests
- Issues
- Releases
- Wiki
- Repository description and topics
- Most repository settings

### What GEI does NOT migrate — handle manually

| Not migrated | Consequence for these repos |
|---|---|
| **Actions secrets & variables** | `publish-sidecar.yml` uses only the built-in `GITHUB_TOKEN`, so nothing to re-add — but verify org Actions policy allows the workflow and `packages: write`. |
| **GHCR packages** | `ghcr.io/tedg-dev/omnibor-sidecar` stays under `tedg-dev`. The workflow uses `ghcr.io/${{ github.repository_owner }}/...`, so **future** builds auto-publish under `ghcr.io/ciscosecurityservices/...`. Old tags must be re-published or re-pulled and re-tagged. |
| **Rulesets & branch protection** | Ruleset A (`16035780`) and the legacy branch protection must be **recreated** in the org repo. Org/enterprise-level rulesets may also newly apply. |
| **Webhooks** | Migrated but **disabled**; re-enable if any exist. |
| **Projects (classic / v2)** | Not moved. The planning board is already project `#255` in the org, so likely not applicable. |
| **Git LFS / large files** | None of concern in these repos. |

---

## 3. Prerequisites — verify before starting

1. **GEI enabled for the enterprise** and the **migrator role** granted to `tedg_cisco` (org owner can self-grant, or an enterprise owner grants it). Command form: `gh gei grant-migrator-role`.
2. **Two classic PATs:**

   | PAT | Account | Required scopes |
   |---|---|---|
   | Source | `tedg-dev` | `repo`, `read:org`, `workflow` |
   | Target | `tedg_cisco` | `repo`, `admin:org`, `workflow` |

   The existing `tedg_cisco` token already exceeds the target requirement.
3. **Target org must not already contain** `bisbom-gen` or `bisbom-java-testapp` (both names are currently free).
4. **SAML/SSO authorization** of the target PAT for `CiscoSecurityServices`.

---

## 4. Step-by-step procedure

**1. Install GEI (one time):**

```bash
gh extension install github/gh-gei
```

**2. Set PAT environment variables** (write to a temp env file; never inline secrets):

```bash
export GH_SOURCE_PAT=<tedg-dev classic PAT>
export GH_PAT=<tedg_cisco classic PAT>
```

**3. Migrate each repo.** For a GitHub.com personal source, the personal login is the `--github-source-org`:

```bash
gh gei migrate-repo \
  --github-source-org tedg-dev --source-repo bisbom-gen \
  --github-target-org CiscoSecurityServices --target-repo bisbom-gen
```

```bash
gh gei migrate-repo \
  --github-source-org tedg-dev --source-repo bisbom-java-testapp \
  --github-target-org CiscoSecurityServices --target-repo bisbom-java-testapp
```

GEI runs asynchronously and returns a migration ID plus an auto-opening log.
Non-critical errors (for example, a single PR comment) do not abort the run.
Run a **trial-run migration** first (repeatable) before the production run.

**4. Open PRs:**

`#94`, `#201`, `#202`, `#203` migrate as part of `bisbom-gen`. Confirm
their head branches came across; re-target or rebase if any base moved.

---

## 5. Repo-specific cleanup after migration

Update these hardcoded references as normal PRs into the new org repo. Keep the
changes generic and config-driven — no per-repo hacks.

### 5.1 Git remotes (local + every EC2 build host)

```bash
git remote set-url origin https://github.com/CiscoSecurityServices/bisbom-gen.git
```

Redirects from the old URL work automatically, **but are permanently destroyed
if anything is ever recreated at `tedg-dev/omnibor-analysis`** — so update all
clones promptly. Also update the EC2 host clone (per the `/ec2-start` sync flow)
and switch local `gh`/git auth to operate as `tedg_cisco`, since `tedg-dev` will
lose access to EMU repos.

### 5.2 Source / config references

| File | Reference to update |
|---|---|
| `app/config.yaml:395` | `omnibor-java-testapp` clone URL → new org |
| `terraform/variables.tf:50` | `repo_url` default → new org |
| `terraform/terraform.tfvars.example:26` | `repo_url` example → new org |
| `.github/workflows/publish-sidecar.yml:4-5` | comment referencing `tedg-dev/omnibor-java-testapp` (cosmetic; image path already generic via `github.repository_owner`) |

### 5.3 Documentation links

53 files reference `tedg-dev/omnibor*` or `raw.githubusercontent.com/tedg-dev`,
notably:

- `docs/sidecar/java/enterprise-sbom.md` (6 refs + embedded PNG raw links)
- `docs/sidecar/java/*.drawio`
- `docs/architecture/README.md`
- `docs/sidecar/infrastructure.md`
- `docs/sidecar/phase-isolation-cicd-results.md`
- `.windsurf/` rules and workflows

A single scripted find-replace
(`tedg-dev/omnibor-analysis` → `CiscoSecurityServices/omnibor-analysis`, and the
testapp equivalent) is appropriate — it is a mechanical URL rename. **Exception:**
review `output/build-logs/**` historical logs; those are generated artifacts and
arguably should be left as-is because they record what happened at the time.

### 5.4 Cross-repo issue references

Issues already live in `CiscoSecurityServices/gambit`, and PRs were referenced as
`tedg-dev/omnibor-analysis#<n>`. After migration, PRs live at
`CiscoSecurityServices/omnibor-analysis#<n>` — update the `.windsurf`
issue-management rules and `docs/planning/github-issues-crosswalk.md` accordingly.

### 5.5 Rulesets / branch protection

Recreate the following per `.windsurf/rules/infrastructure/github-rulesets.md`:

- **Ruleset A** — PR required, `non_fast_forward`, `deletion`, `required_linear_history`.
- **Legacy branch protection** — `enforce_admins: false`, 1 required review.

Note that enterprise-level rulesets may now also apply and could conflict — check
after transfer.

### 5.6 GHCR packages

Trigger one `publish-sidecar.yml` run in the new org to populate
`ghcr.io/ciscosecurityservices/omnibor-sidecar`, then verify visibility and
permissions. Retire the old `tedg-dev` package once consumers are cut over.

---

## 6. Recommended order

1. Confirm GEI is enabled and the migrator role is granted to `tedg_cisco` (blocking prerequisite).
2. **Trial-run** migrate `omnibor-java-testapp` first (smaller; it is the analysis *target*) → validate → production migrate.
3. Trial-run then migrate `omnibor-analysis`.
4. Recreate rulesets / branch protection; re-run the sidecar publish workflow.
5. Land the reference-update PRs (remotes already switched locally); update the EC2 host and `gh` auth.
6. Update planning / crosswalk docs.

---

## 7. Verify with enterprise admins — do not assume

- **Is GEI enabled** for the `CiscoSecurityServices` enterprise, and will they grant `tedg_cisco` the migrator role? Some enterprises restrict this to enterprise owners.
- **Name retirement:** if either repo had **more than 100 clones or more than 100 Actions runs in the prior week**, GitHub permanently retires `tedg-dev/<name>` and it cannot be recreated there. This is acceptable here — the direction is away from `tedg-dev`, not back.

---

## 8. Evidence appendix

Commands run during research (all read-only):

| Check | Result |
|---|---|
| `git remote -v` | `origin` → `https://github.com/tedg-dev/omnibor-analysis.git` |
| `gh auth status` | Accounts `tedg-dev` (active), `tedg_cisco` (`admin:enterprise`), `tedg-cisco` |
| `gh api orgs/CiscoSecurityServices` as `tedg-dev` | **404 Not Found** (no visibility) |
| `gh api orgs/CiscoSecurityServices` as `tedg_cisco` | `type: Organization`, `members_can_create_repositories: true` |
| Open PRs (author `tedg-dev`) | `#94`, `#201`, `#202`, `#203` |

Authoritative GitHub docs consulted:

- Transferring a repository (personal-account and organization transfer rules, redirect and name-retirement behavior).
- About GitHub Enterprise Importer (supported migration paths; what GEI does and does not migrate).
