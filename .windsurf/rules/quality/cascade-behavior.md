---
description: Rules governing Windsurf Cascade AI behavior, terminal usage, and reasoning
trigger: always_on
priority: critical
---

# Cascade Behavior Rules

These rules govern how the Windsurf Cascade AI assistant operates within
any project. They cover terminal safety, tool usage, reasoning, and
interaction with the user.

## Terminal Safety

### Command Length

- **Maximum command line length: 200 characters** — split longer commands
  into multiple steps
- Git operations (add, commit, push) should be separate commands
- For long commit messages, write to a temp file and use `git commit -F`

### Anti-Hang Rules

Commands that wait for stdin or interactive input WILL freeze the session.

- **NEVER** use heredocs (`<<EOF`), multi-line `python3 -c`, or stdin pipes
  into commands that read stdin
- **NEVER** use `gh pr create --body "..."` inline — use `--body-file`
- **NEVER** run commands without `-y`, `--yes`, `--non-interactive` flags
  when the tool supports them
- **NEVER** use `git commit` without `-m` or `-F` (avoids editor)
- **NEVER** run commands expected to take >30 seconds as blocking

### Output Limits

- Append `| head -n 20` to commands that may produce thousands of lines
- Never run `grep`, `find`, or `ls -R` from project root without excluding
  `.git`, `node_modules`, `build`, `target`, `__pycache__`
- If processing many files, list them first and process in chunks of ≤5

## Prefer Built-In Tools Over Terminal

Cascade MUST use built-in IDE tools instead of terminal commands whenever
possible. Built-in tools execute instantly without user approval.

| Instead of (terminal) | Use (built-in tool) |
|-----------------------|---------------------|
| `find`, `ls`, `ls -R` | `find_by_name`, `list_dir` |
| `grep`, `rg`, `ag` | `grep_search` |
| `cat`, `head`, `tail` | `read_file` |

Use `run_command` only for operations with no built-in equivalent:
git, pytest, pip, gh, aws, ssh, rsync, docker, mv, rm, cp, mkdir.

## Minimize Terminal Windows

- Run commands **sequentially** in one terminal, not in parallel
- Batch related checks into a single command with `&&` when short
- Only use a second terminal if the first is occupied by a long-running process

## Reasoning and Interaction

- **Explain reasoning** before making changes — break complex problems
  into steps and validate each step
- **Do not prompt** unless there is a real choice to make
- If there is an industry-standard approach, use it without asking
- Proceed autonomously on routine operations (branch names, merge strategy)
- **Record new rules**: any time a new rule or process requirement is
  introduced, persist it in `.windsurf/rules/` in the same PR

## Auto-Run Safety Tiers

### Tier 1 — Safe to Auto-Run

- File system inspection: `ls`, `cat`, `head`, `tail`, `wc`, `stat`
- Git read operations: `git status`, `git diff`, `git log -n`, `git branch`
- Git write operations: `git add`, `git commit -m`, `git push origin`
- Virtual environment: `pytest`, `pip install -r requirements.txt`, `pip check`
- GitHub CLI reads: `gh pr list`, `gh pr view`, `gh pr status`
- Tool versions: `docker --version`, `gh --version`

### Tier 2 — Requires User Approval

- Cloud write operations: `aws ec2 start-instances`, `stop-instances`
- Remote access: `ssh`, `rsync`, `scp`
- Container operations: `docker run`, `docker build`
- Network downloads: `curl`, `wget`
- System packages: `brew install`, `apt install`

### Never Auto-Execute

- Remote script execution: `curl ... | bash`
- Obfuscated payloads (base64, hex-encoded commands)
- Credential file access (`~/.ssh/`, `~/.aws/credentials`, `.env`)
- Destructive wildcards: `rm -rf *`, `rm -rf /`
- Privilege escalation: `sudo`, `su`
- Force push: `git push --force`

When rules conflict, the **most restrictive** rule wins.

## Secrets in Chat

- **NEVER** display, echo, or store secrets in Cascade chat output
- When reading files with credentials, redact sensitive values
- If a tool call returns secret content, summarize structure only
- Reference credential files by path and key name — never by value
