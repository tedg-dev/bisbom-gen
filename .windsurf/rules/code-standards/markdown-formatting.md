---
description: Markdown formatting rule for lists and code blocks after colons
---

# Markdown Formatting Rule

When generating markdown documents, **always add a blank line after any line ending with ":**"** before lists, code blocks, or other formatted content.

## Why This Matters

Without a blank line after ":**", the subsequent list or code block will not render correctly in most markdown parsers.

## Examples

### Incorrect (no newline):

```markdown
**What it captures:**
- Item 1
- Item 2
```

### Correct (with newline):

```markdown
**What it captures:**

- Item 1
- Item 2
```

## Rule Application

This rule applies to:

- Lines ending with ":**" followed by bullet lists
- Lines ending with ":**" followed by numbered lists
- Lines ending with ":**" followed by code blocks
- Lines ending with ":**" followed by any other formatted content

Always ensure there is a blank line between the colon and the subsequent content.
