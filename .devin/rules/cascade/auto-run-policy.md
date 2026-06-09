---
description: Auto-run terminal command policy (adapted from Cisco CodeGuard two-tier model)
---

# Auto-Run Terminal Command Policy

Adapted from Cisco's CodeGuard two-tier execution model for agentic IDEs.
This project's builds run on a remote EC2 instance (sandboxed), so local
commands are developer workflow only. Cascade MUST use this policy to
determine whether `SafeToAutoRun` is `true` or `false` for every
`run_command` call.

## Tier 1 — Auto-Run Safe (SafeToAutoRun: true)

Cascade SHOULD set `SafeToAutoRun: true` for all commands in this tier.

### File System Inspection

- `ls`, `pwd`, `cat`, `head`, `tail`, `wc`, `file`, `stat`
- `find` (with scope restrictions from cli-safety.md)
- `grep` (with scope restrictions from cli-safety.md)

### File Modification (Scoped to Project)

- `rm` — file/directory deletion (within project tree only, no `-rf *` wildcards)
- `mv`, `cp` — move/copy (within project tree)
- `mkdir`, `mkdir -p` — directory creation
- `touch` — file creation
- `chmod` — permission changes (within project tree)

### Git (All Local Operations)

- `git status`, `git diff`, `git log -n <N>`, `git show`
- `git branch`, `git branch -a`, `git branch -d`, `git branch -D`
- `git remote -v`, `git rev-parse`, `git stash list`
- `git add`, `git commit -m`, `git commit -F`
- `git push origin`
- `git pull origin`
- `git merge --no-ff`
- `git checkout`, `git switch`
- `git tag`

### Python Venv

- `.venv/bin/python3 --version`
- `.venv/bin/python3 -m pytest` — unit tests (pure mocks, no side effects)
- `.venv/bin/python3 -m app.*` — project application code
- `.venv/bin/python3 <script>` — project scripts
- `.venv/bin/pip install -r requirements.txt`
- `.venv/bin/pip install <package>`
- `.venv/bin/pip check`, `.venv/bin/pip list`, `.venv/bin/pip show`

### GitHub CLI

- `gh pr list`, `gh pr view`, `gh pr status`, `gh repo view`
- `gh pr create --body-file` (never inline `--body`)
- `gh pr merge`
- `gh pr close`
- `gh issue create`

### Tool Versions / Lookup

- `docker --version`, `gh --version`, `aws --version`
- `which`, `type`, `command -v`
- `echo`, `printf`, `env`, `printenv`

### Cloud Inspection (Read-Only)

- `aws ec2 describe-instances` (with `--profile` and `--no-cli-pager`)
- `aws sts get-caller-identity` (with `--profile`)

## Tier 2 — Requires User Approval (SafeToAutoRun: false)

Commands with significant external impact. Cascade MUST set
`SafeToAutoRun: false` for these.

### Cloud Write Operations

- `aws ec2 start-instances` — starts billable compute
- `aws ec2 stop-instances` — powers off build host
- `aws ec2 terminate-instances` — destroys instance permanently

### Remote Access / Network

- `ssh` — remote shell access
- `rsync` — file sync to/from remote host
- `scp` — remote file copy
- `curl`, `wget` — network downloads

### Container Operations

- `docker run`, `docker build`, `docker exec`
- `docker-compose up`, `docker-compose build`, `docker-compose run`

### System Package Installation

- `brew install` — system-level package manager
- `npm install` — Node.js packages (not used in this project)
- `apt install` — system packages (Linux only)

## Never Auto-Execute

These commands MUST NEVER have `SafeToAutoRun: true` under any circumstances.

- **Remote script execution**: `curl ... | bash`, `wget ... | sh`
- **Obfuscated payloads**: Base64-encoded commands, hex-encoded strings
- **Credential file access**: Commands targeting `~/.ssh/`, `~/.aws/credentials`,
  `.env` files, `keys.json`, tokens
- **Destructive wildcards**: `rm -rf *`, `rm -rf /`, `find ... -delete` without path scope
- **Privilege escalation**: `sudo`, `su`, `doas`
- **System control**: `shutdown`, `reboot`, `systemctl`
- **Force push**: `git push --force`, `git push -f`

## Interaction With Existing Rules

This policy works alongside:

- **cascade/cli-safety.md** — performance guards (timeouts, output limits, no inline Python)
- **cascade/command-execution.md** — anti-hang patterns (no heredocs, no stdin pipes)
- **infrastructure/ec2-operations.md** — EC2-specific safeguards
- **project/credentials.md** — secret handling

When rules conflict, the **most restrictive** rule wins.

## Windsurf IDE Allowlist Configuration

To enable auto-run in the Windsurf IDE, add these regex patterns to:
**Settings → Cascade → Terminal → Command Allowlist**

```
^ls(\s|$)
^pwd$
^cat\s
^head\s
^tail\s
^wc\s
^file\s
^stat\s
^find\s
^grep\s
^echo\s
^printf\s
^which\s
^env$
^printenv
^rm\s
^mv\s
^cp\s
^mkdir
^touch\s
^chmod\s
^git\s
^\.venv/bin/
^gh\s
^docker\s+--version
^(gh|aws)\s+--version
^aws\s+(ec2\s+describe-|sts\s+get-caller-identity)
```
