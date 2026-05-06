---
description: Master checklist of all MUST/NEVER/ALWAYS rules — READ FIRST
trigger: always_on
priority: highest
---

# CRITICAL RULES — Master Checklist

**Cascade MUST consult this file before every action.** These rules are
extracted from all `.windsurf/rules/` files into one scannable checklist.
Violating any rule marked NEVER is a critical failure.

---

## Before Every Terminal Command

- [ ] **NEVER** run `python3 -c "..."` or `.venv/bin/python3 -c "..."`
  inline. Write a script file and execute it instead.
- [ ] **NEVER** use heredocs (`<<EOF`, `<<'EOF'`) or pipe stdin into
  commands that read stdin. Use temp files instead.
- [ ] **NEVER** use `gh pr create --body "..."` inline. Write body to
  `/tmp/pr_body.md` and use `--body-file /tmp/pr_body.md`.
- [ ] **NEVER** run `git commit` without `-m "msg"` or `-F /tmp/msg.txt`.
- [ ] **NEVER** run `cd` as a command. Use the `Cwd` parameter instead.
- [ ] **NEVER** exceed **200 characters** per command line. Split into
  multiple steps if longer.
- [ ] **NEVER** run commands expected to take >30 seconds as blocking.
  Use `Blocking: false` with `WaitMsBeforeAsync`.
- [ ] **ALWAYS** use `.venv/bin/python3`, never bare `python3` or `python`.
- [ ] **ALWAYS** append `| head -n 20` to commands that may produce
  thousands of lines of output.
- [ ] **ALWAYS** exclude `.git`, `node_modules`, `__pycache__`, `target`,
  `build` from `find`/`grep`/`ls -R` when searching from project root.
- [ ] **ALWAYS** prefer built-in tools over terminal commands:

  | Instead of | Use |
  |---|---|
  | `find`, `ls` | `find_by_name`, `list_dir` |
  | `grep`, `rg` | `grep_search` |
  | `cat`, `head` | `read_file` |

- [ ] **ALWAYS** run commands sequentially in one terminal. Only open a
  second terminal if the first is occupied by a long-running process.

---

## Before Every Commit

- [ ] **ALWAYS** run the full test suite — no skipping, no partial runs.
  `.venv/bin/python3 -m pytest tests/ -x -q`
- [ ] **ALWAYS** verify coverage: **97%+ overall**, **95%+ per file**.
- [ ] **NEVER** commit code that does not compile or import.
- [ ] **NEVER** commit code with lint errors that CI will catch.
- [ ] **ALWAYS** fix pre-existing test/lint failures — never ignore them.
- [ ] **NEVER** delete or skip a failing test to unblock a feature.
- [ ] **ALWAYS** record new rules in `.windsurf/rules/` in the same PR.

---

## Before Every Golden File Comparison

- [ ] **NEVER** update golden files without explicit user approval.
- [ ] **NEVER** suggest updating golden files — no reason is valid.
  The user reviews diffs and decides. Period.
- [ ] **NEVER** dismiss differences with "likely upstream" or "within
  tolerance" — report EVERY difference.
- [ ] **ALWAYS** report: exact counts (old → new), added/removed entries,
  version changes, structural changes.
- [ ] **ALWAYS** stop and wait for user approval if any diffs exist.
- [ ] **ALWAYS** clean bomtrace3 treedb between sequential repo runs
  (`rm -f /tmp/bomsh_hook_raw_logfile* /tmp/bomsh_createbom* /tmp/treedb_*`
  but PRESERVE `/tmp/bomsh_hook2.py`).

---

## Before Every Code Change

- [ ] **NEVER** hardcode repository names in executable code. Use
  config-driven behavior (`config.yaml`).
- [ ] **NEVER** write repo-specific logic (`if name == "curl"`). All
  behavior must be driven by config fields.
- [ ] **ALWAYS** use stable release tags in `config.yaml`, never dev
  branches (`master`, `main`, `unstable`).
- [ ] **ALWAYS** produce release builds, never debug. Check
  `project/release-builds.md` for language-specific flags.
- [ ] **ALWAYS** import SPDX relationship types from
  `app/spdx/relationships.py` — never hardcode strings.

---

## Before Every Git Operation

- [ ] **NEVER** commit directly to `main`. Always use feature branches.
  GitHub Rulesets enforce this server-side — direct push is rejected.
- [ ] **NEVER** create a PR or merge without explicit user approval.
- [ ] **NEVER** use `git push --force` or `git push -f`.
  Server-side rejected via Ruleset A (`non_fast_forward` rule).
- [ ] **ALWAYS** use conventional branch prefixes: `fix/`, `feat/`,
  `chore/`, `docs/`, `test/`.
- [ ] **NEVER** leave stashed work behind. If you `git stash`, you MUST
  `git stash pop` in the same turn — stash, operate, switch back, pop.
- [ ] **NEVER** assume the working tree belongs to Cascade. Other AI
  conversations or the user may have uncommitted changes at any time.
- [ ] **ALWAYS** prefer `git fetch` without switching branches over
  `git checkout` + stash when you only need to read remote state.
- [ ] **Reference**: See `infrastructure/github-rulesets.md` for full
  ruleset configuration. Owner merges without review; contributors need 1.

---

## Before Every AWS / Remote Operation

- [ ] **NEVER** hardcode EC2 instance IDs. Read from
  `infrastructure/active-profile.md` or discover dynamically.
- [ ] **NEVER** use `rsync --delete` when syncing to EC2.
- [ ] **NEVER** tell the user to run `duo-sso` manually. Run it yourself:
  `duo-sso --profile ted-admin`, then fix the profile name with `sed`.
- [ ] **NEVER** stop EC2 between tasks during the user's workday. Only
  stop when the user says they are done for the day.
- [ ] **ALWAYS** sync results locally after every successful remote
  analysis run (`rsync` output/ only — docs/ has no generated files).

---

## Secrets — Always

- [ ] **NEVER** display, echo, or store secrets, tokens, API keys, or
  passwords in Cascade chat output.
- [ ] **ALWAYS** redact sensitive values when reading credential files.
- [ ] **ALWAYS** reference credentials by path and key name — never by
  value.
- [ ] **NEVER** commit credential files (`.env`, `keys.json`, SSH keys).

---

## When Rules Conflict

The **most restrictive** rule wins. If uncertain, ask the user.
