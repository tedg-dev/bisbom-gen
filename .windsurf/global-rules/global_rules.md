# Global Rules — All Workspaces

## Terminal Command Safety

Before every terminal command, verify ALL of the following:

1. **No inline Python.** NEVER run `python3 -c "..."` or `.venv/bin/python3 -c "..."`. Write a script file (e.g., `/tmp/script.py`) and execute it instead.
2. **No heredocs or stdin pipes.** NEVER use heredocs (`<<EOF`, `<<'EOF'`) or pipe stdin into commands that read stdin. Use temp files instead.
3. **No inline PR/issue bodies.** NEVER use `gh pr create --body "..."` or `gh issue create --body "..."`. Write to a temp file and use `--body-file`.
4. **No bare git commits.** NEVER run `git commit` without `-m "msg"` or `-F /tmp/msg.txt`.
5. **No cd commands.** NEVER run `cd` as a command. Use the `Cwd` parameter instead.
6. **Max 200 characters.** NEVER exceed 200 characters per command line. Split into multiple steps.
7. **No long blocking commands.** NEVER run commands expected to take >30 seconds as blocking. Use `Blocking: false` with `WaitMsBeforeAsync`.

## Markdown Formatting

All rules apply to every `.md` file Cascade generates or edits.

### 1. Backtick-Wrap Identifiers Containing Underscores

**Any identifier containing underscores MUST be wrapped in backticks** outside fenced code blocks. Bare underscores trigger italic rendering — `PTRACE_TRACEME` without backticks renders as PTRACE*TRACEME*.

Applies to: filenames, function names, constants, config keys, Linux capabilities (`CAP_SYS_ADMIN`, `CAP_BPF`), syscall names (`sys_enter_execve`).

**Self-check:** Before finishing any markdown edit, scan prose for bare underscores. If a word contains `_` and is not inside backticks or a code fence, wrap it.

### 2. Blank Line After Colon Lines

Always add a blank line after any line ending with `:**` before lists, code blocks, or other formatted content.

### 3. Code Fences MUST Have a Language Identifier

NEVER use bare triple-backtick fences. Specify a language: `bash`, `python`, `c`, `yaml`, `json`, `text`, etc.

### 4. No ASCII Art Diagrams

NEVER use box-drawing characters. Use markdown tables, numbered lists, or `.drawio` diagrams.

### 5. Tables Over Code Blocks for Structured Data

Use markdown tables for comparisons, property/value pairs, sequential data — not formatted code blocks.

### 6. Tables Stay as Markdown (Never Images)

NEVER convert markdown tables to images. Tables must remain native markdown.

### 7. Evaluate Table Readability

4+ columns with short values or extreme width imbalance → use HTML `<table>` with explicit widths. 2–3 balanced columns → markdown tables are fine.

### 8. Metadata Blocks Use Headerless Tables

Document metadata (audience, author, date, status) must use a **headerless 2-column table**, not blockquotes. Blockquotes merge consecutive lines into one paragraph.

### 9. Architectural Diagrams as Draw.io + Embedded PNG

When a document needs a visual diagram (data flows, architecture, boxes and arrows), create a `.drawio` file and embed the exported PNG. NEVER use ASCII art. Use markdown tables for tabular data, Draw.io only for spatial/flow diagrams.

### 10. Consecutive Lines Need Blank Line Separators

Consecutive lines without blank lines render as one paragraph. Add blank lines between `**Key:** value` lines. Do NOT use trailing `\` for line breaks.