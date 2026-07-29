---
description: Rules for EC2 operations to avoid common mistakes
---

# EC2 Operations Rules

## NEVER hardcode instance IDs from memory

Instance IDs change when instances are terminated and recreated. **Always** discover
the current instance ID dynamically:

```bash
aws ec2 describe-instances --profile ted-admin \
  --filters "Name=tag:Name,Values=*bisbom*" \
  --query "Reservations[].Instances[].{ID:InstanceId,State:State.Name}" \
  --output table --no-cli-pager
```

Or read it from `.windsurf/rules/infrastructure/active-profile.md`.

## Dockerfile COPY paths use project root context

The Docker build context is the **project root** (set by `docker-compose.yml`
`context: ..`). All `COPY` instructions in the Dockerfile use paths relative to
the project root:

- `COPY requirements.txt ...` — OK (file is at project root)
- `COPY docker/bomtrace_go.conf ...` — OK (file is in docker/ subdir)
- `COPY bomtrace_go.conf ...` — WRONG (file doesn't exist at project root)

## rsync rules

- **Never** use `--delete` when syncing to EC2 (it can wipe files that only exist remotely)
- **Always** exclude `__pycache__` and `.pytest_cache`
- **Always** sync `requirements.txt` from project root (it's not in docker/)
- Sync order: app/, docker/, tests/, requirements.txt

## AWS session management

- `duo-sso` sessions expire every 1 hour
- If any `aws` command fails with `RequestExpired`, `ExpiredToken`, or
  `NoCredentials`, Cascade **MUST immediately execute** duo-sso itself:
  `run_command: duo-sso --profile ted-admin`
  **NEVER print instructions for the user to run it manually. EVER.**
- After duo-sso completes, fix the credentials profile name:
  `sed -i '' 's/^\[default\]/[ted-admin]/' ~/.aws/credentials`
- Then retry the failed AWS command

## EC2 instance power management

- **DO NOT** stop the EC2 instance between tasks during the user's workday
- Only stop the instance when:
  - The user explicitly says they are done for the day, or
  - The user has been unresponsive for 30+ minutes after Cascade asked a question
- Starting/stopping EC2 takes ~30 seconds each way — avoid unnecessary stop/start cycles
- When in doubt, **leave it running**

## Use the /ec2-start workflow

For starting EC2, syncing code, and rebuilding Docker, always use `/ec2-start`.
Do not improvise these steps from memory.
