---
description: Start EC2 build host, sync code, rebuild Docker, and verify readiness
---

# EC2 Start & Sync

Start the EC2 build host and get it ready for analysis. Run this at the start of
any session that needs remote builds.

## 0. Read active infrastructure profile

// turbo
```bash
cat .windsurf/rules/infrastructure/active-profile.md
```

Extract **Instance ID**, **SSH alias**, and **Repo path on host** from the profile.
Use these values in all subsequent steps. **NEVER hardcode instance IDs from memory.**

## 1. Check AWS session & instance status

// turbo
```bash
aws ec2 describe-instances --profile ted-admin \
  --filters "Name=tag:Name,Values=*omnibor*" \
  --query "Reservations[].Instances[].{ID:InstanceId,State:State.Name,IP:PublicIpAddress,Name:Tags[?Key=='Name'].Value|[0]}" \
  --output table --no-cli-pager
```

If this fails with `RequestExpired`, tell the user to re-auth:
```
1. Go to https://go2.cisco.com/aws → SSO + Duo MFA
2. Use SAML bookmarklet → download fresh saml.txt
3. Run: duo-sso -saml $(cat ~/Downloads/saml.txt) -profile ted-admin -set-aws-region us-west-1
4. Run: sed -i '' 's/^\[default\]/[ted-admin]/' ~/.aws/credentials
```

## 2. Start instance (if stopped)

Use the Instance ID from step 1 (NOT from memory):

```bash
aws ec2 start-instances --profile ted-admin \
  --instance-ids <INSTANCE_ID> --no-cli-pager
```

Wait for it to be running:

// turbo
```bash
aws ec2 wait instance-running --profile ted-admin \
  --instance-ids <INSTANCE_ID> --no-cli-pager && echo "Instance is running"
```

## 3. Verify SSH connectivity

Wait a few seconds for sshd to start, then test:

// turbo
```bash
sleep 5 && ssh -o ConnectTimeout=10 omnibor-build "echo SSH OK"
```

If connection is refused on port 443, user may need to disable VPN first.
If port 22 also fails, wait 30s and retry (sshd may still be starting).

## 4. Sync code to EC2

Sync all project directories and root-level files. **Do NOT use --delete on
directories that contain Docker-generated files (like __pycache__).**

```bash
rsync -avz --exclude='__pycache__' --exclude='.pytest_cache' \
  app/ omnibor-build:/home/ubuntu/omnibor-analysis/app/
rsync -avz --exclude='__pycache__' --exclude='.pytest_cache' \
  docker/ omnibor-build:/home/ubuntu/omnibor-analysis/docker/
rsync -avz --exclude='__pycache__' --exclude='.pytest_cache' \
  tests/ omnibor-build:/home/ubuntu/omnibor-analysis/tests/
rsync -avz --exclude='__pycache__' --exclude='.pytest_cache' \
  docs/ omnibor-build:/home/ubuntu/omnibor-analysis/docs/
rsync -avz --exclude='__pycache__' --exclude='.pytest_cache' \
  scripts/ omnibor-build:/home/ubuntu/omnibor-analysis/scripts/
rsync -avz --exclude='__pycache__' --exclude='.pytest_cache' \
  .windsurf/ omnibor-build:/home/ubuntu/omnibor-analysis/.windsurf/
rsync -avz requirements.txt requirements-dev.txt .coveragerc VERSION \
  omnibor-build:/home/ubuntu/omnibor-analysis/
```

## 5. Rebuild Docker image

The build context is the **project root** (set by docker-compose.yml `context: ..`).
All COPY paths in the Dockerfile are relative to the project root, NOT docker/.

```bash
ssh omnibor-build "cd /home/ubuntu/omnibor-analysis && \
  docker compose -f docker/docker-compose.yml build 2>&1"
```

This uses Docker layer cache — only changed layers rebuild (usually <1 min).
If a full rebuild is needed, add `--no-cache` (takes 10-20 min).

## 6. Verify container tools

```bash
ssh omnibor-build "cd /home/ubuntu/omnibor-analysis && \
  docker compose -f docker/docker-compose.yml run --rm omnibor-env \
  bash -c 'which bomtrace2 && which bomtrace3 && syft version && go version && \
  echo \"bomtrace_go.conf:\" && head -1 /opt/bomsh/bin/bomtrace_go.conf'"
```

Note: `bomtrace2` and `bomtrace3` do not support `--version`. Use `which` to verify they exist.

## 7. Report readiness

Confirm to the user:
- EC2 instance ID and state
- SSH connectivity
- Code sync status
- Docker image build status
- Tool versions (bomtrace2, bomtrace3, syft, go)

## Common Pitfalls

| Problem | Cause | Fix |
|---------|-------|-----|
| `RequestExpired` | duo-sso session expired (1hr) | Re-auth per step 1 |
| `InvalidInstanceID.NotFound` | Instance ID changed (terminated & recreated) | Use step 1 to discover current ID, update active-profile.md |
| `Connection reset by peer` | Cisco VPN blocks port 443 to AWS | Disable VPN, retry |
| `requirements.txt not found` during build | Forgot to sync root requirements.txt | Step 4 syncs it |
| `bomtrace_go.conf not found` during build | COPY path wrong — must be `docker/bomtrace_go.conf` (relative to project root context) | Fix Dockerfile COPY path |
| No container after instance start | Container was `--rm` or instance was recreated | Step 5 rebuilds image; step 6 runs ephemeral containers |
