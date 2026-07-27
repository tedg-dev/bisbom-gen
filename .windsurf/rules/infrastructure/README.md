---
description: Infrastructure profile system for OmniBOR build hosts
---

# Infrastructure Profiles

Each contributor runs bisbom-gen analysis on their own Linux x86_64 build host.
This directory contains **provider templates** (tracked in git) and each user's
**active profile** (local-only, gitignored).

## How It Works

```
infrastructure/
├── README.md                  ← You are here (tracked)
├── active-profile.md          ← YOUR setup: IP, SSH, paths (gitignored)
├── templates/
│   ├── digitalocean.md        ← Template for DigitalOcean droplets (tracked)
│   ├── aws-ec2.md             ← Template for AWS EC2 instances (tracked)
│   └── local-linux.md         ← Template for local/WSL2/bare metal (tracked)
```

- **Templates** are checked into git as references. They contain placeholder values.
- **`active-profile.md`** is gitignored. It contains YOUR real IPs, SSH aliases,
  instance IDs, and provider-specific commands. Cascade reads this file to know
  how to run builds and manage your infrastructure.

## First-Time Setup

1. Pick the template closest to your setup
2. Copy it to `active-profile.md`
3. Fill in your real values (IP, SSH key path, instance ID, etc.)

Example:

```bash
cp .windsurf/rules/infrastructure/templates/digitalocean.md \
   .windsurf/rules/infrastructure/active-profile.md
# Then edit active-profile.md with your actual values
```

## What Cascade Does With This

When Cascade needs to:

- **Run a build** → reads `active-profile.md` for SSH alias and repo path
- **Sync results** → reads `active-profile.md` for rsync commands
- **Stop/start the host** → reads `active-profile.md` for provider CLI commands
- **Remind you to shut down** → reads `active-profile.md` for cost info

If `active-profile.md` doesn't exist, Cascade will ask you to set one up.

## Switching Providers

To migrate from DigitalOcean to AWS (or vice versa):

1. Copy the new template: `cp templates/aws-ec2.md active-profile.md`
2. Fill in your values
3. That's it — Cascade will use the new profile immediately

Your old profile is just a local file — delete it or rename it for reference.

## Security

- `active-profile.md` is **gitignored** — your IPs, instance IDs, and SSH
  config never leave your machine
- Templates contain only placeholder values and are safe to commit
- Never put API keys, tokens, or passwords in any of these files —
  use environment variables or `~/.ssh/config` instead
