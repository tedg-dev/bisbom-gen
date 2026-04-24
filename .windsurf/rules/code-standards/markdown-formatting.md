---
description: Comprehensive markdown formatting rules for all generated .md files
---

# Markdown Formatting Rules

All rules below apply to every markdown file Cascade generates or edits.
Violations break rendering in GitHub, VS Code preview, and other standard markdown viewers.

---

## Rule 1: Blank Line After Colon Lines

**Always add a blank line after any line ending with `:**`** before lists, code blocks, or other formatted content.

Without a blank line, the subsequent content will not render correctly.

**Incorrect:**

```markdown
**What it captures:**
- Item 1
- Item 2
```

**Correct:**

```markdown
**What it captures:**

- Item 1
- Item 2
```

---

## Rule 2: Code Fences MUST Have a Language Identifier

**NEVER use bare triple-backtick fences.** Every fenced code block must specify a language.

**Incorrect:**

````markdown
```
some content here
```
````

**Correct — use the appropriate language:**

- `bash` — shell commands, scripts
- `c` — C source code
- `python` — Python source code
- `yaml` — YAML config files
- `json` — JSON data
- `text` — plain text output, logs, syscall lists, or anything that is not code
- `toml`, `sql`, `html`, `css`, `js`, etc. — use the matching language

If the content is not code but also not prose (e.g., a list of syscall names, log output, file paths), use `text`.

---

## Rule 3: NO ASCII Art Diagrams in Markdown

**NEVER use box-drawing characters** (e.g., `┌`, `│`, `└`, `─`, `▼`, `├`) to create diagrams in markdown files. They render incorrectly in most viewers due to font width inconsistencies.

**Instead, use one of:**

- **Markdown tables** — for structured data, flows, property lists
- **Numbered/bulleted lists** — for sequential steps or hierarchies
- **Draw.io `.drawio` files** — for actual visual diagrams (per the Draw.io rule)

**Incorrect:**

````markdown
```
┌──────────┐     ┌──────────┐
│  Step 1  │────▶│  Step 2  │
└──────────┘     └──────────┘
```
````

**Correct — use a table:**

```markdown
| Step | Action | Output |
|------|--------|--------|
| 1 | Compile | main.o |
| 2 | Link | binary |
```

---

## Rule 4: Prefer Tables Over Code Blocks for Structured Data

When presenting structured information (comparisons, property/value pairs, sequential data with columns), **always use markdown tables** instead of formatted code blocks.

Tables are searchable, render consistently, and are easier to update.

**Incorrect:**

````markdown
```
Starting overhead:     40pp
After cache:           31pp
After seccomp:         14pp
```
````

**Correct:**

```markdown
| Step | Strategy | Running Total |
|------|----------|---------------|
| Start | — | **40pp** |
| +1 | Pre-Hash Cache | **31pp** |
| +2 | seccomp-bpf | **14pp** |
```

---

## Rule 5: Metadata Blocks Use Headerless Tables

Document metadata (audience, author, date, status) must use a **headerless 2-column table**, not blockquotes. Blockquotes merge consecutive lines into a single paragraph in most markdown renderers.

**Incorrect (renders as one line):**

```markdown
> **Audience:** Engineering teams
> **Status:** Draft
> **Last updated:** April 2026
```

**Correct:**

```markdown
| | |
|---|---|
| **Audience** | Engineering teams |
| **Status** | Draft |
| **Last updated** | April 2026 |
```

---

## Rule 6: Architectural Diagrams as Draw.io + Embedded PNG

When a document needs a **visual diagram** (data flows, architecture, component relationships, anything with boxes and arrows), create a `.drawio` file and embed the exported PNG in the markdown.

**Steps:**

1. Create `<name>.drawio` in the same directory as the markdown file
2. Export to PNG: `/Applications/draw.io.app/Contents/MacOS/draw.io --export --format png --scale 2 --border 10 --output <name>.png <name>.drawio`
3. Embed as a **clickable thumbnail** that opens the full-size image on click:

```markdown
<a href="diagram-name.png"><img src="diagram-name.png" width="600" alt="Diagram Title — click to enlarge"></a>

*Click image to enlarge. Source: [diagram-name.drawio](diagram-name.drawio)*
```

The `width="600"` displays a readable thumbnail inline. Clicking opens the full 2x-scale PNG. On GitHub, this opens in a lightbox; locally it opens the image file.

**When to use Draw.io diagrams:**

- Architecture overviews with multiple components and data flow arrows
- Sequence/interaction diagrams
- Anything that would otherwise tempt you to use ASCII art

**When NOT to use Draw.io diagrams (use markdown tables instead):**

- Tabular data (comparisons, metrics, property/value lists)
- Sequential steps without branching
- Anything readers may need to search, copy, or diff

---

## Rule 7: Tables Stay as Markdown (Never Images)

**NEVER convert markdown tables to images.** Tables must remain as native markdown because:

- They are **searchable** (Ctrl+F works)
- They are **diff-friendly** (git shows line-level changes)
- They are **editable** without re-exporting
- They **render natively** on GitHub, VS Code, and all markdown viewers
- They **adapt** to dark/light themes automatically

Draw.io images lose all of these properties. Use Draw.io only for diagrams with flows, arrows, and spatial relationships — not for data tables.

---

## Rule 8: Backtick-Wrap Identifiers Containing Underscores (HIGH PRIORITY)

**Any technical identifier containing underscores MUST be wrapped in backticks** when it appears in prose outside a fenced code block. Bare underscores in markdown are interpreted as italic markers — `_text_` renders as _text_, silently corrupting filenames, variable names, and constants.

This rule applies to:

- **Filenames:** `bomsh_hook_raw_logfile`, `openosc_package_info.c`, `redis-server_build.spdx.json`
- **Function/variable names:** `hash_tree`, `_run_c_cpp_pipeline()`
- **Constants/enums:** `STATIC_LINK`, `DEPENDS_ON`, `GENERATED_FROM`
- **Config keys:** `build_steps`, `output_binaries`, `apt_deps`

**Incorrect — underscores create false italics:**

```markdown
The bomsh_hook_raw_logfile contains STATIC_LINK relationships.
```

Renders as: "The bomsh*hook*raw\_logfile contains STATIC*LINK relationships."

**Correct — backticks prevent italic interpretation:**

```markdown
The `bomsh_hook_raw_logfile` contains `STATIC_LINK` relationships.
```

**Why not backslash-escape?** Backslash escaping (`\_`) works but is fragile and ugly in raw markdown. Backticks are preferred because they also apply monospace formatting, which is semantically correct for technical identifiers.

**Never escape underscores inside code blocks or backticks.** Fenced code blocks (` ``` `) and inline backticks (`` ` ``) are literal contexts — markdown does not interpret underscores inside them. Escaping with `\_` inside code produces a visible backslash in the rendered output.

**Self-check:** Before finishing any markdown edit, scan all prose lines (outside code fences and backticks) for bare underscores. If a word contains `_` and is not inside backticks or a code fence, wrap it in backticks.

---

## Rule 9: Consecutive Lines Need Blank Line Separators

**Consecutive lines that are not separated by a blank line render as a single paragraph** in standard markdown. This is especially problematic for metadata-style blocks like:

**Incorrect (renders as one long line):**

```markdown
**Impact:** -11pp (40% → 29%)
**Complexity:** Low
**Target budget category:** SHA-256 file hashing
```

**Correct — add a blank line between each line:**

```markdown
**Impact:** -11pp (40% → 29%)

**Complexity:** Low

**Target budget category:** SHA-256 file hashing
```

**Do NOT use trailing `\` for line breaks.** While `\` is valid CommonMark, it renders as a literal backslash in many viewers (Webex, some GitHub contexts, VS Code preview). Blank lines are the only universally reliable separator.

**When this applies:**

- Strategy/feature metadata blocks (Impact, Complexity, Target)
- Any group of short bold lines meant to display vertically
- Consecutive `**Key:** value` lines outside a table

**Alternative:** Use a headerless table (Rule 5) if there are more than 3 lines.

---

## Summary of Violations

| Violation | Fix |
|-----------|-----|
| Bare ` ``` ` code fence | Add language: ` ```bash `, ` ```c `, ` ```text `, etc. |
| ASCII art box diagrams | Create `.drawio` + export PNG + embed in markdown |
| Structured data in code blocks | Convert to markdown tables |
| No blank line after `:**` | Add blank line before list/code/content |
| Diagram needed in markdown | Create `.drawio`, export PNG, embed with `![](name.png)` |
| Table converted to image | Revert to markdown table — tables must stay as text |
| Bare underscores in prose identifiers | Wrap in backticks: `bomsh_hook_raw_logfile` |
| Consecutive bold lines merge into one | Add blank line between each line (never use `\`) |
