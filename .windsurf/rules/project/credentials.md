---
description: Rules for credential and sensitive data handling
---

# Credentials

- Never commit credential files (keys.json, .env, tokens) to this repository
- GitHub tokens may be needed to clone private repos — use environment variables or mounted secrets
- Binary scanner credentials (BDBA API keys, etc.) should be passed via environment variables into the Docker container, never hardcoded in config.yaml or scripts
- The .gitignore already excludes keys.json and *.env
