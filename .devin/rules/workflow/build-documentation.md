---
description: Rules for documenting build changes
---

# Build Documentation Rule

Whenever Cascade makes changes to build code (Dockerfile, docker-compose.yml, Makefile,
build scripts, CI/CD configs, or any build-related configuration), Cascade **must**
update the relevant documentation **immediately after** the build change is verified
to work.

# What Counts as Build Code

- `docker/Dockerfile`
- `docker/docker-compose.yml`
- Any `Makefile`, `CMakeLists.txt`, or build script
- CI/CD pipeline configs (`.github/workflows/`, etc.)
- Dependency management files (`requirements.txt`, `package.json`, etc.)
- Build-related environment variables or configuration

# Required Documentation Updates

1. **Inline comments** — Add or update comments in the build file itself explaining
   *why* the change was made, not just *what* changed
2. **README or docs** — Update the relevant README (e.g., `docker/README.md`) with:
   - Any new assumptions or constraints
   - Version pins and why they were chosen
   - Known issues and workarounds
   - Troubleshooting guidance for common failure modes
3. **CHANGELOG.md** — Add the change to the `[Unreleased]` section

# Why This Matters

Build assumptions are easy to forget and hard to rediscover. If a build breaks in a
greenfield environment months later, the documentation should contain enough context
to diagnose and fix the issue without re-investigating from scratch.
