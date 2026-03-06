---
description: Rules for executing commands in the terminal
---

# Command Execution Rules

- **Never run `cd` commands** — use `Cwd` parameter instead
- **Sequential git commands** — always wait for `git add` to complete before `git commit`
- **Avoid parallel git operations** — git commands that modify state should run sequentially
- **Use `python3`** — never use bare `python` (may not exist in pyenv)

# NEVER Run Commands That Can Hang

Commands that wait for stdin or interactive input will **freeze the session**. Avoid these patterns:

- **`gh pr create`** — ALWAYS use `gh pr create --fill` (never pass `--body` with `--fill`)
- **Inline multiline Python** — NEVER use `python3 -c "..."` with multiline code. Instead, write a short temp script to a file and run it, or use a single-line command
- **Any command that prompts for input** — always pass flags to skip prompts (e.g., `--yes`, `--force`, `--non-interactive`)
- **`git commit`** without `-m` — always pass `-m "message"` to avoid opening an editor
- **Pagers** — commands are run with `PAGER=cat` but still avoid `git log` without `-n`

If a command might hang, **do not run it**. Find a non-interactive alternative.

# No Parallel Execution That Causes Race Conditions

- **DO NOT execute parallel operations that could cause race conditions or merge conflicts**
- Examples of operations that must be sequential:
  - Multiple edits to the same file
  - Git operations (add, commit, push)
  - Operations where one depends on the result of another
- Parallel execution is acceptable for independent read-only operations (e.g., reading multiple files)
