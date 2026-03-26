---
description: Rules for handling secrets and credentials in Cascade chat
---

# Secrets in Chat

- **NEVER display, echo, or store secrets, tokens, API keys, or passwords in Cascade chat output**
- When reading files that contain credentials (e.g., keys.json, .env), redact sensitive values in any output
- If a tool call returns secret content, summarize the structure without revealing the values
- Reference credential files by path and key name only — never by value
