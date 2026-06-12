# Windsurf Global Rules — Installation

## What This Is

`global_rules.md` contains rules that apply to **all Windsurf
workspaces** on your machine — not just this project. These rules
enforce terminal command safety and markdown formatting standards
across every Cascade session.

## Installation

Copy the file to Windsurf's global rules location:

```bash
cp .windsurf/global-rules/global_rules.md ~/.codeium/windsurf/memories/global_rules.md
```

The file takes effect immediately — no restart needed.

## Correct Location

| Location | Purpose |
|---|---|
| `~/.codeium/windsurf/memories/global_rules.md` | Global rules (all workspaces) |
| `.windsurf/rules/*.md` | Workspace rules (this project only) |

## Incorrect Locations (Do NOT Use)

These locations are **not read** by Windsurf despite the directory
names suggesting otherwise:

- `~/.windsurf/rules/`
- `~/.codeium/windsurf/rules/`
- `~/.windsurfrules`

## Updating

When modifying global rules:

1. Edit `~/.codeium/windsurf/memories/global_rules.md` (the live copy)
2. Copy it back to the repo: `cp ~/.codeium/windsurf/memories/global_rules.md .windsurf/global-rules/global_rules.md`
3. Commit the repo copy so other contributors can install it

## Constraints

- **6,000 character limit** — Windsurf ignores content beyond this
- **No frontmatter** — global rules are always on; no `trigger:` field
- **Single file** — all global rules must be in this one file

## Source

Per [Windsurf official documentation](https://docs.windsurf.com/windsurf/cascade/memories):
global rules are stored at `~/.codeium/windsurf/memories/global_rules.md`.
