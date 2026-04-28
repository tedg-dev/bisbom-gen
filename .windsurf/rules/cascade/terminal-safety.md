---
description: All terminal command safety rules — anti-hang, length limits, tool preferences, terminal management
trigger: always_on
priority: critical
---

# Terminal Safety

All critical rules are also in `CRITICAL.md`. This file provides the
full detail and rationale behind each rule.

## Command Length

- **Maximum command line length: 200 characters** — split longer commands
  into multiple steps
- Git operations (add, commit, push) should be separate commands
- For long commit messages, write to a temp file and use `git commit -F`

## Anti-Hang Rules

Commands that wait for stdin or interactive input WILL freeze the session.

- **NEVER** use heredocs (`<<EOF`), multi-line `python3 -c`, or stdin
  pipes into commands that read stdin
- **NEVER** use `gh pr create --body "..."` inline — use `--body-file`
- **NEVER** run commands without `-y`, `--yes`, `--non-interactive` flags
  when the tool supports them
- **NEVER** use `git commit` without `-m` or `-F` (avoids editor)
- **NEVER** run commands expected to take >30 seconds as blocking
- **NEVER** run `python3 -c "..."` or `.venv/bin/python3 -c "..."` on
  the command line. Write a script file and execute it instead.
- **NEVER** run `cd` as a command. Use the `Cwd` parameter.

## Output Limits

- Append `| head -n 20` to commands that may produce thousands of lines
- Never run `grep`, `find`, or `ls -R` from project root without
  excluding `.git`, `node_modules`, `build`, `target`, `__pycache__`
- If processing many files, list them first and process in chunks of ≤5

## Prefer Built-In Tools Over Terminal

Built-in tools execute instantly without user approval.

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
- Only use a second terminal if the first is occupied by a long-running
  process

## No Parallel Race Conditions

- DO NOT execute parallel operations that could cause race conditions
- Examples that must be sequential:
  - Multiple edits to the same file
  - Git operations (add, commit, push)
  - Operations where one depends on the result of another
- Parallel execution is acceptable for independent read-only operations
