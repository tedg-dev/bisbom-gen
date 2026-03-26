---
description: Rules for project versioning and release management
---

# Semantic Versioning

- This project follows [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html): `MAJOR.MINOR.PATCH`
  - **MAJOR** — breaking or incompatible changes
  - **MINOR** — new functionality, backward-compatible
  - **PATCH** — bug fixes, backward-compatible
- The single source of truth for the current version is the `VERSION` file at the repo root

# VERSION File

- Contains only the version string (e.g., `0.1.0`), no prefix, no trailing content
- Must be updated as part of a version bump PR

# CHANGELOG.md

- Follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format
- Every version bump PR must move items from `[Unreleased]` into a new version section
- Use categories: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`

# Version Bump Process

- Version bumps are their own dedicated PR using the `version-bump/X.Y.Z` branch prefix
- A version bump PR must update both `VERSION` and `CHANGELOG.md`
- After the version bump PR is merged, tag the commit: `git tag vX.Y.Z && git push origin vX.Y.Z`
- Not every PR requires a version bump — bump when a meaningful milestone is reached

# Git Tags

- Every release version gets a git tag in the format `vX.Y.Z`
- Tags are created on the merge commit in `main` after a version bump PR is merged
