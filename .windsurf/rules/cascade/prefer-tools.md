---
description: Prefer built-in tools over terminal commands to avoid approval prompts
trigger: always_on
priority: high
---

# Prefer Built-In Tools Over Terminal Commands

Cascade MUST use built-in IDE tools instead of terminal commands whenever possible.
Terminal commands require user approval and interrupt workflow. Built-in tools
execute instantly without approval.

## Tool Substitutions

| Instead of (terminal)          | Use (built-in tool)       |
|-------------------------------|---------------------------|
| `find`, `ls`, `ls -R`        | `find_by_name`, `list_dir` |
| `grep`, `rg`, `ag`           | `grep_search`             |
| `cat`, `head`, `tail`        | `read_file`               |

## When Terminal Commands Are Still Needed

Use `run_command` only for operations that have no built-in tool equivalent:

- `git` operations (status, add, commit, push, merge, branch, etc.)
- `.venv/bin/python3` execution (pytest, app modules, pip)
- `gh` CLI operations
- `aws` CLI operations
- `ssh`, `rsync`, `docker` operations
- File modifications that require shell logic (`mv`, `rm`, `cp`, `mkdir`)

## Examples

**BAD** — triggers approval prompt:
```
run_command: find docs/ -type f -name "*.md" | sort
run_command: grep -r "zoomToFit" app/
run_command: cat app/viz/js_interaction.py
```

**GOOD** — instant, no approval:
```
find_by_name: SearchDirectory=docs/, Pattern=*.md
grep_search: SearchPath=app/, Query=zoomToFit
read_file: file_path=app/viz/js_interaction.py
```
