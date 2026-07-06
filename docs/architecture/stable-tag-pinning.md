# Stable Tag Pinning Strategy

This document explains why every target repository in `app/config.yaml`
is pinned to a specific release tag instead of tracking a development
branch, how the tag map was chosen, and what to do when updating.

---

## Table of Contents

1. [The Problem: Development Branches in SBOMs](#1-the-problem-development-branches-in-sboms)
2. [The Redis 255.255.255 Incident](#2-the-redis-255255255-incident)
3. [Why Tags Matter for SPDX](#3-why-tags-matter-for-spdx)
4. [Current Tag Map](#4-current-tag-map)
5. [How Tags Were Selected](#5-how-tags-were-selected)
6. [Updating a Tag](#6-updating-a-tag)
7. [Repos Without Tags](#7-repos-without-tags)

---

## 1. The Problem: Development Branches in SBOMs

When `config.yaml` points a repository at `master` or `main`, the
pipeline clones whatever commit happens to be at the tip of that branch
at build time. This creates three problems for SBOM generation:

- **Placeholder versions.** Many projects set their version to a
  sentinel value on the development branch (e.g., `255.255.255`,
  `0.0.0-SNAPSHOT`, `unreleased`). This sentinel propagates into the
  SPDX `versionInfo` field, making the SBOM useless for vulnerability
  matching.

- **Unreproducible builds.** Two builds on the same day can produce
  different SBOMs if a commit lands between them. Pinning to a tag
  guarantees that every build of `curl-8_19_0` produces the same
  dependency graph.

- **Meaningless comparisons.** When comparing an OmniBOR-generated SBOM
  against a proprietary binary scan, both sides must agree on what
  version of the software was analyzed. A moving branch target makes
  this impossible.

## 2. The Redis 255.255.255 Incident

This problem was discovered during analysis of the Redis repository.

### What happened

The `config.yaml` entry for Redis originally pointed at the `unstable`
branch:

```yaml
redis:
  url: https://github.com/redis/redis.git
  branch: unstable
```

The generated SPDX document reported the root package version as
**`255.255.255`** — a placeholder that Redis uses on its development
branch to indicate an unreleased build. This value appeared in:

- The `versionInfo` field of the root SPDX package
- The HTML visualization title and tooltip
- The PURL (`pkg:generic/redis@255.255.255`)

A vulnerability scanner consuming this SBOM would find zero CVE matches
because no Redis advisory references version `255.255.255`. The SBOM
was technically valid SPDX but practically worthless.

### How it was fixed

The branch was changed to a stable release tag:

```yaml
redis:
  url: https://github.com/redis/redis.git
  branch: "8.0.6"
```

The regenerated SPDX now reports `versionInfo: 8.0.6`, and the PURL
`pkg:generic/redis@8.0.6` correctly matches against the NVD and OSV
databases.

### The lesson

If this happened with Redis — a well-known project with clear release
tags — it can happen with any repository that uses a sentinel version
on its development branch. The fix is systematic: **pin every repo to a
known stable release tag**.

## 3. Why Tags Matter for SPDX

SPDX 2.3 records the version of each package in the `versionInfo`
field. The pipeline automatically extracts the root package version
from the config tag (see [Version Detection](vendored-version-detection.md#3-root-package-version-detection)),
so tag accuracy directly determines SPDX `versionInfo` accuracy.

Downstream consumers rely on this field for:

| Consumer | What they need | Broken by dev branches |
|----------|---------------|----------------------|
| **Vulnerability scanners** | Match `pkg:generic/redis@8.0.6` against CVE databases | `255.255.255` matches nothing |
| **License compliance** | Identify which license applies to a specific release | Dev branches may have license changes in progress |
| **Reproducibility audits** | Rebuild the exact same binary | Branch tip moves between builds |
| **SBOM comparison** | Compare OmniBOR SBOM vs. Syft/proprietary scan | Both must analyze the same code |
| **Regulatory submissions** | NTIA/CISA minimum elements require accurate version | Placeholder versions fail compliance |

## 4. Current Tag Map

All repositories in `config.yaml` as of April 2026:

| Repo | Language | Tag | Extracted Version | Source |
|------|----------|-----|-------------------|--------|
| curl | c-cpp | `curl-8_19_0` | — (underscores) | GitHub Release |
| ffmpeg | c-cpp | `n8.1` | `8.1` | Git tag |
| nmap | c-cpp | `master` | — (no version) | No tags exist (see [§7](#7-repos-without-tags)) |
| redis | c-cpp | `8.0.6` | `8.0.6` | GitHub Release |
| openosc | c-cpp | `v1.0.7` | `1.0.7` | GitHub Release |
| node | c-cpp | `v22.19.0` | `22.19.0` | GitHub Release |
| fzf | go | `v0.70.0` | `0.70.0` | GitHub Release |
| lazygit | go | `v0.60.0` | `0.60.0` | GitHub Release |
| croc | go | `v10.4.2` | `10.4.2` | GitHub Release |
| dive | go | `v0.13.1` | `0.13.1` | GitHub Release |
| gdu | go | `v5.34.1` | `5.34.1` | GitHub Release |
| pocketbase | go | `v0.25.9` | `0.25.9` | GitHub Release |
| oxipng | rust | `v10.1.0` | `10.1.0` | GitHub Release |
| dura | rust | `v0.2.0` | `0.2.0` | Git tag |
| jsoup | java | `jsoup-1.22.1` | `1.22.1` | GitHub Release |
| checkstyle | java | `checkstyle-13.3.0` | `13.3.0` | GitHub Release |
| crawler4j | java | `crawler4j-4.4.0` | `4.4.0` | GitHub Release |
| dependency-check | java | `v9.2.0` | `9.2.0` | GitHub Release |
| datahub | java | `v1.5.0.1` | `1.5.0.1` | GitHub Release |
| logging-log4j2 | java | `rel/2.24.3` | `2.24.3` | GitHub Release |
| spring-boot | java | `v3.4.4` | `3.4.4` | GitHub Release |
| bc-java | java | `r1rv84` | — (non-numeric) | Git tag |

## 5. How Tags Were Selected

For each repository, the selection process was:

1. **Check GitHub Releases** (`gh release view --repo <owner/repo>`).
   Use the latest non-prerelease tag.

2. **If no releases exist**, check Git tags
   (`gh api repos/<owner/repo>/tags`). Pick the latest tag that looks
   like a stable version (no `-dev`, `-rc`, `-alpha` suffixes).

3. **If no tags exist at all**, leave the branch as `master`/`main`
   and add a comment in `config.yaml` explaining why. See [§7](#7-repos-without-tags).

Tag naming conventions vary by project:

| Convention | Example | Projects |
|-----------|---------|----------|
| `vX.Y.Z` | `v0.70.0` | fzf, lazygit, croc, dive, gdu, oxipng, dura, openosc, node |
| `name-X.Y.Z` | `jsoup-1.22.1` | jsoup, checkstyle, crawler4j |
| `nX.Y` | `n8.1` | FFmpeg |
| `X.Y.Z` | `8.0.6` | Redis |
| `name-X_Y_Z` | `curl-8_19_0` | curl (underscores instead of dots) |

Git's `clone --branch` accepts both branch names and tag names, so no
special handling is needed in the pipeline.

## 6. Updating a Tag

When a new stable release is available:

1. Look up the latest release:
   ```bash
   gh release view --repo <owner/repo> --json tagName -q .tagName
   ```

2. Update `config.yaml`:
   ```yaml
   branch: <new-tag>
   ```

3. Re-run the pipeline on EC2 to regenerate SBOMs with the new version.

4. Verify the SPDX `versionInfo` field reflects the new version.

5. Commit the config change with a message like:
   ```
   chore(config): bump redis 8.0.6 → 8.2.0
   ```

**Do not batch-update all repos at once.** Each tag bump may change
the dependency graph, so update and verify one repo at a time.

## 7. Repos Without Tags

Some projects do not create GitHub releases or Git tags. As of March
2026, the only such repo in our config is **nmap**.

For these repos:

- Leave `branch: master` with a comment: `# no stable tags exist`
- Accept that the SPDX version will reflect whatever the project
  sets on its development branch (nmap uses `X.Y.Z-DEV`)
- Periodically check if the project has started creating releases

If a project creates tags infrequently (last release years ago), prefer
the latest tag over `master` even if it is old — a stable old version
produces a more useful SBOM than a moving development target.

---

*Last updated: April 29, 2026*
