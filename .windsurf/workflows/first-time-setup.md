---
description: Complete first-time setup for a new contributor cloning this repo
---

# First-Time Setup

Run this workflow when you've just cloned the omnibor-analysis repository into
a fresh Windsurf IDE installation and want to get everything working.

## 0. Read all project rules and workflows

**This step is mandatory before any other work.**

Read every rule and workflow file to load project conventions:

```bash
for f in .windsurf/rules/*.md; do echo "=== $f ==="; cat "$f"; echo; done
for f in .windsurf/workflows/*.md; do echo "=== $f ==="; cat "$f"; echo; done
```

After reading, confirm to the user which rules and workflows were loaded.

## 1. Create and verify the Python virtual environment

// turbo
```bash
python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -r requirements.txt
```

Verify it works:

// turbo
```bash
.venv/bin/python3 --version && .venv/bin/pip check 2>&1 | tail -3
```

## 2. Run the test suite to verify everything is healthy

// turbo
```bash
.venv/bin/python3 -m pytest tests/ -x -q --cov=app --cov-report=term-missing 2>&1 | tail -15
```

All tests should pass with 97%+ overall coverage.

## 3. Verify Docker is available

The analysis pipeline runs inside a Docker container. Check if Docker is
available locally:

```bash
docker --version && docker-compose --version
```

If Docker is not available locally, you have two options:

**Option A: Local Linux x86_64 host with Docker**

Build the image:
```bash
docker-compose -f docker/docker-compose.yml build
```

**Option B: Remote Linux x86_64 host**

Set up SSH access to a remote Linux server, clone the repo there, and build:
```bash
ssh <YOUR_HOST> "cd /path/to/omnibor-analysis && docker-compose -f docker/docker-compose.yml build"
```

## 4. Verify bomtrace3 inside the container

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env bomtrace3 --version
```

If this fails, the image needs to be rebuilt (step 3).

## 5. List available target repositories

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env python3 /workspace/app/analyze.py --list
```

## 6. Ready to analyze!

You're now ready to:
- **Add a new repo:** Tell Cascade "add [repo name] for analysis" or use `/add-repo`
- **Run analysis:** Tell Cascade "run analysis on [repo]" or use `/run-analysis`
- **Compare SBOMs:** Tell Cascade "compare SBOMs for [repo]" or use `/run-comparison`

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `python3 -m venv` fails | Install Python 3.9+ (brew install python3 on macOS) |
| `docker-compose` not found | Install Docker Desktop or `pip install docker-compose` |
| bomtrace3 fails with "Exec format error" | You're on ARM64 — need x86_64 Linux host |
| Tests fail on import | Run `.venv/bin/pip install -r requirements.txt` |
| SYS_PTRACE error | Docker must run with --cap-add=SYS_PTRACE (set in docker-compose.yml) |
