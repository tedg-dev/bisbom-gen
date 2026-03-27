---
description: CRITICAL - Command line length limits (READ FIRST)
priority: highest
---

# Command Line Length Rule

**PRIORITY: HIGHEST — Read this before running ANY terminal command.**

## Hard Limit

**Maximum command line length: 200 characters**

Any command longer than 200 characters MUST be split into multiple steps.

## Why This Matters

- Long commands are hard to read and approve
- They often get canceled by the user
- They can cause terminal buffer issues
- Multi-line commands with `&&` chains are error-prone

## Correct Patterns

### Git Operations — ALWAYS Separate Steps

```bash
# Step 1: Stage files
git add -A

# Step 2: Commit (short message)
git commit -m "feat: short description"

# Step 3: Push
git push origin branch-name
```

### NEVER Do This

```bash
# BAD - Too long, will be canceled
git add file1 file2 file3 ... && git commit -m "long message with details" && git push origin branch
```

## Before Every Command

1. Count the characters (mentally estimate)
2. If > 200 chars, split into steps
3. Use separate tool calls for each step

## Commit Messages

For longer commit messages, use a temp file:

```bash
# Write message to file
echo "feat: title" > /tmp/commit_msg.txt
echo "" >> /tmp/commit_msg.txt
echo "- Detail 1" >> /tmp/commit_msg.txt

# Commit with file
git commit -F /tmp/commit_msg.txt
```
