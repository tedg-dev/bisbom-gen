---
description: Minimize terminal window usage — user views terminals during work
trigger: always_on
priority: high
---

# Minimize Terminal Windows

The user actively views terminal windows while Cascade works. Opening many
parallel terminals clutters the workspace and makes it hard to follow.

## Rules

1. **Run commands sequentially** in one terminal, not in parallel across many
2. **Prefer built-in tools** (read_file, grep_search, find_by_name, list_dir)
   over terminal commands — they produce zero terminal windows
3. **Batch related checks** into a single command with `&&` when safe and short
4. Only use a second terminal if the first is occupied by a long-running process
