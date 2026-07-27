---
description: Run on every startup to verify the omnibor-analysis environment is ready
---

# Setup Environment

Run this workflow when opening the omnibor-analysis workspace.

## 0. MANDATORY: Review all project rules

**This step is non-negotiable. Do it before ANY other work.**

Read every file in `.windsurf/rules/` (including subdirectories) to refresh all project rules:

```bash
find .windsurf/rules/ -name "*.md" | sort | while read f; do echo "=== $f ==="; cat "$f"; echo; done
```

After reading, confirm to the user which rules you've loaded and acknowledge
the key constraints (pre-commit gates, single-step git, CHANGELOG updates,
PR-first workflow, no direct commits to main).

**Do not proceed to any task until this step is complete.**

## 1. Verify Python virtual environment

All local development uses `.venv/`. Verify it exists and has dependencies:

// turbo
```bash
.venv/bin/python3 --version && .venv/bin/pip check 2>&1 | tail -3
```

If missing, create it:
```bash
python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -r requirements.txt
```

## 2. Verify key project files

// turbo
```bash
ls -la app/config.yaml app/analyze.py app/compare.py app/spdx_from_adg.py app/spdx_visualize.py docker/Dockerfile docker/docker-compose.yml
```

## 3. Run quick test check

// turbo
```bash
.venv/bin/python3 -m pytest tests/ -x -q 2>&1 | tail -5
```

## 4. Check infrastructure profile

Check if the user has set up their build host profile:

// turbo
```bash
if [ -f .windsurf/rules/infrastructure/active-profile.md ]; then
  echo "=== Active Infrastructure Profile ==="
  head -20 .windsurf/rules/infrastructure/active-profile.md
else
  echo "No infrastructure profile found."
  echo "Set one up by copying a template:"
  echo "  cp .windsurf/rules/infrastructure/templates/digitalocean.md .windsurf/rules/infrastructure/active-profile.md"
  echo "  cp .windsurf/rules/infrastructure/templates/aws-ec2.md .windsurf/rules/infrastructure/active-profile.md"
  echo "  cp .windsurf/rules/infrastructure/templates/local-linux.md .windsurf/rules/infrastructure/active-profile.md"
  echo "Then edit active-profile.md with your actual values."
fi
```

## 5. Check Docker availability

Check if Docker is available (locally or remotely):

```bash
docker --version 2>/dev/null || echo "Docker not available locally — you may need a remote Linux x86_64 host"
```

If Docker is available locally:
```bash
docker-compose -f docker/docker-compose.yml run --rm bisbom-env bomtrace3 --version 2>/dev/null || echo "Container image not built yet — run /docker-build workflow"
```

## 6. Check for existing output artifacts

```bash
find output/ -name "*.spdx.json" -o -name "*.spdx.html" 2>/dev/null | head -20 || echo "No output artifacts yet"
```

## 7. Check for existing docs/reports

// turbo
```bash
find docs/ -name "*.md" -not -name ".gitkeep" 2>/dev/null | sort | tail -10 || echo "No reports yet"
```

## 8. Report status to user

Summarize:
- Python venv status
- Test suite status (count + coverage)
- Infrastructure profile (provider, host, connection)
- Docker availability
- Available repos (from config.yaml)
- Existing output artifacts
- Available workflows: `/add-repo`, `/run-analysis`, `/run-comparison`, `/docker-build`
