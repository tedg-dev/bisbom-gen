# Golden SPDX Files

Golden files are **immutable baselines** for regression testing. They
detect unintended changes in SPDX output caused by code changes. Every
successful analysis run MUST be compared against these files.

## Policy

- Golden files are generated from **standalone mode** (strace/ptrace on
  Ubuntu) — the authoritative baseline
- All variants (sidecar, RHEL, Alpine) are compared against the same
  golden files
- Golden files are **never** updated without explicit user approval
- Every update MUST include a changelog entry below

## Structure

```
tests/golden/spdx/
├── c-cpp/
│   ├── curl/          # pinned: curl-8_19_0 tag
│   ├── ffmpeg/        # pinned: n8.1 tag
│   ├── nmap/          # unpinned: master (no stable tags)
│   └── redis/         # pinned: 8.0.6 tag
├── go/
│   └── lazygit/       # pinned: v0.51.1 tag
├── java/
│   ├── bc-java/       # pinned: r1rv84 tag
│   ├── checkstyle/    # pinned: checkstyle-13.3.0 tag
│   ├── crawler4j/     # pinned: crawler4j-4.4.0 tag
│   ├── dependency-check/ # pinned: v9.2.0 tag
│   ├── jsoup/         # pinned: jsoup-1.22.1 tag
│   ├── logging-log4j2/   # pinned: rel/2.24.3 tag
│   └── spring-boot/   # pinned: v3.4.4 tag
└── rust/
    ├── dura/          # pinned: v0.3.1 tag
    └── oxipng/        # pinned: v9.1.4 tag
```

## Known Comparison Limitations

- **gitoid external refs** for compiled C/C++ binaries change every
  build (binaries are not reproducible). `compare_golden.py` normalizes
  these to avoid false-positive diffs.
- **nmap** uses `branch: master` (no stable tags). Golden files will
  drift as upstream `master` evolves.
- **APT system library versions** (libssl3, libnghttp2, etc.) change
  when the Docker base image is rebuilt with newer Ubuntu patches.

## Changelog

### 2026-05-14 — PR #TBD: Full re-run golden refresh

**Root cause:** PR #178 (`ac7c476`) changed `java_generator.py` to make
treedb authoritative (strace is secondary verification). PR #180
(`24fc432`) added shade plugin annotation + Maven `-am` flag. Docker
image rebuild pulled newer Ubuntu APT patches.

| Repo | File | Change |
|------|------|--------|
| java/spring-boot | `buildSrc_analyzed.spdx.json` | Files: 0→314 (PR #178: treedb now authoritative, buildSrc .class files kept) |
| java/spring-boot | `buildSrc_build.spdx.json` | Files: 0→314, Relationships: 125→439 (same cause) |
| c-cpp/ffmpeg | all 12 existing files | Version: `8.19.0-DEV`→`8.1` (version detector fix from PR #42, golden never refreshed). Files: 3331→3342 (+11 source files from Docker rebuild). APT: libssl3 `0ubuntu1.21`→`0ubuntu1.23` |
| c-cpp/ffmpeg | 6 new files added | `libavdevice.so`, `libavfilter.so`, `libswresample.so` (_analyzed + _build) — always built, never baselined |
| c-cpp/curl | `libcurl.so_build.spdx.json` | APT versions: libnghttp2-14 `1ubuntu0.2`→`1ubuntu0.3`, libssl3 `0ubuntu1.21`→`0ubuntu1.23` |

**Not updated (structural issues):**
- c-cpp/redis — gitoid-only diffs (compiled binary hash changes every
  build). Fixed by normalizing gitoid refs in `compare_golden.py`.
- c-cpp/nmap — unpinned `master` branch; diffs are permanent until
  pinned to a commit SHA.

**Approved by:** user (2026-05-14)

---

### 2026-05-08 — PR #161: Java golden files for all 7 repos

**Root cause:** PR #156 (sibling filtering fix in `java_generator.py`)
changed dependency counts for multi-module Java projects. Full EC2
regression run regenerated all Java SPDX.

| Repo | File | Change |
|------|------|--------|
| java/bc-java | `bccore-jdk18on-1.84_analyzed.spdx.json` | **Created** (new repo, 2270 files) |
| java/bc-java | `bccore-jdk18on-1.84_build.spdx.json` | **Created** (37 packages) |
| java/bc-java | `bcprov-jdk18on-1.84_analyzed.spdx.json` | **Created** (6048 files) |
| java/bc-java | `bcprov-jdk18on-1.84_build.spdx.json` | **Created** (37 packages) |
| java/checkstyle | `checkstyle-13.3.0_*.spdx.json` | Minor version/ref updates |
| java/crawler4j | `crawler4j-4.4.0_*.spdx.json` | **Created** (new repo, 110 files, 25 packages) |
| java/dependency-check | `dependency-check-core-9.2.0_*.spdx.json` | **Created** (new repo, 582 files, 78 packages) |
| java/dependency-check | `dependency-check-utils-9.2.0_*.spdx.json` | **Created** (48 files, 12 packages) |
| java/jsoup | `jsoup-1.22.1_*.spdx.json` | Minor version/ref updates |
| java/logging-log4j2 | `log4j-api-2.24.3_*.spdx.json` | **Created** (new repo, 365 files, 14 packages) |
| java/logging-log4j2 | `log4j-core-2.24.3_*.spdx.json` | **Created** (1942 files, 44 packages) |
| java/spring-boot | `buildSrc_*.spdx.json` | **Created** (0 files — strace filtering excluded all) |
| java/spring-boot | `spring-boot-3.4.4_*.spdx.json` | **Created** (new repo, 1758 files, 162 packages) |
| java/spring-boot | `spring-boot-configuration-processor-3.4.4_*.spdx.json` | **Created** (86 files, 46 packages) |

**Approved by:** user (2026-05-08)

---

### 2026-05-07 — PR #159: Checkstyle sidecar golden update

**Root cause:** PR #111 added sidecar integration test for checkstyle.
Golden files updated to include `BUILD_TOOL_OF` relationships for ant
build tool, verified via sidecar mode.

| Repo | File | Change |
|------|------|--------|
| java/checkstyle | `checkstyle-13.3.0_analyzed.spdx.json` | 3 lines changed (ant BUILD_TOOL_OF refs) |
| java/checkstyle | `checkstyle-13.3.0_build.spdx.json` | 9 lines changed (ant BUILD_TOOL_OF refs) |

**Approved by:** user (2026-05-07)

---

### 2026-05-06 — PR #150: lazygit + oxipng clean baselines

**Root cause:** lazygit golden files were contaminated with cross-repo
package leakage from treedb (packages from other repos appeared in
lazygit SPDX due to missing treedb cleanup between sequential runs).
oxipng golden files were stale (generated from an old unpinned commit).
Both repos re-run with clean treedb from pinned tags.

| Repo | File | Change |
|------|------|--------|
| go/lazygit | `lazygit_analyzed.spdx.json` | Replaced (removed cross-repo contamination, pinned to v0.51.1) |
| go/lazygit | `lazygit_build.spdx.json` | Replaced (same) |
| rust/oxipng | `oxipng_analyzed.spdx.json` | Replaced (pinned to v9.1.4, was stale commit) |
| rust/oxipng | `oxipng_build.spdx.json` | Replaced (same) |

**Approved by:** user (2026-05-06)

---

### 2026-05-05 — PR #149: May 2026 EC2 regression run

**Root cause:** Full regression run on EC2 after multiple pipeline
improvements. Renamed checkstyle files from old naming convention
(`checkstyle_*.spdx.json` → `checkstyle-13.3.0_*.spdx.json` with
versioned names). Updated jsoup filenames similarly
(`jsoup_*.spdx.json` → `jsoup-1.22.1_*.spdx.json`). Refreshed redis,
lazygit, and dura with current pinned-tag output.

| Repo | File | Change |
|------|------|--------|
| c-cpp/redis | all 4 files | Refreshed from pinned 8.0.6 tag |
| go/lazygit | both files | Refreshed (later found to be contaminated, replaced in PR #150) |
| java/checkstyle | `checkstyle_*.spdx.json` | **Deleted** (old naming) |
| java/checkstyle | `checkstyle-13.3.0_*.spdx.json` | **Created** (versioned naming) |
| java/jsoup | `jsoup_*.spdx.json` → `jsoup-1.22.1_*.spdx.json` | Renamed + refreshed |
| rust/dura | both files | Refreshed from pinned v0.3.1 tag |

**Approved by:** user (2026-05-05)

---

### 2026-04-02 — PR #65: curl pinned to tag

**Root cause:** curl was previously configured with `branch: master`
(unpinned). Pinned to `curl-8_19_0` tag for reproducible golden files.
All 4 curl SPDX files regenerated from the tagged release.

| Repo | File | Change |
|------|------|--------|
| c-cpp/curl | `curl_analyzed.spdx.json` | Regenerated from curl-8_19_0 tag (was master) |
| c-cpp/curl | `curl_build.spdx.json` | Regenerated (same) |
| c-cpp/curl | `libcurl.so_analyzed.spdx.json` | Regenerated (same) |
| c-cpp/curl | `libcurl.so_build.spdx.json` | Regenerated (same) |

**Approved by:** user (2026-04-02)

---

### 2026-03-13 — PR #39: Version detector rewrite + analyzed/build SBOM split

**Root cause:** Major refactor — version detector rewritten with 10
ordered strategies. SPDX output split into `_analyzed` (source files
only) and `_build` (source files + dependency packages) variants.
Renamed all golden files from `_adg.spdx.json` to `_build.spdx.json`.
Created new `_analyzed.spdx.json` for every repo. Added lazygit (Go),
checkstyle + jsoup (Java) golden files.

| Repo | File | Change |
|------|------|--------|
| c-cpp/curl | `curl_adg.spdx.json` → `curl_build.spdx.json` | Renamed |
| c-cpp/curl | `curl_analyzed.spdx.json` | **Created** |
| c-cpp/ffmpeg | 6 `*_adg.spdx.json` → `*_build.spdx.json` | Renamed |
| c-cpp/ffmpeg | 6 `*_analyzed.spdx.json` | **Created** |
| c-cpp/nmap | 3 `*_adg.spdx.json` → `*_build.spdx.json` | Renamed |
| c-cpp/nmap | 3 `*_analyzed.spdx.json` | **Created** |
| c-cpp/redis | 2 `*_adg.spdx.json` → `*_build.spdx.json` | Renamed |
| c-cpp/redis | 2 `*_analyzed.spdx.json` | **Created** |
| go/lazygit | both files | **Created** (new repo) |
| java/checkstyle | both files | **Created** (new repo) |
| java/jsoup | both files | **Created** (new repo) |
| rust/dura | `dura_adg.spdx.json` → `dura_build.spdx.json` | Renamed |
| rust/dura | `dura_analyzed.spdx.json` | **Created** |
| rust/oxipng | `oxipng_adg.spdx.json` → `oxipng_build.spdx.json` | Renamed |
| rust/oxipng | `oxipng_analyzed.spdx.json` | **Created** |

**Approved by:** user (2026-03-13)

---

### 2026-03-11 — Initial commit: First golden baselines

**Root cause:** Initial system-level regression test infrastructure.
Created 15 golden ADG SPDX files for 6 repos with `_adg.spdx.json`
naming convention (before the analyzed/build split).

| Repo | File | Change |
|------|------|--------|
| c-cpp/curl | `curl_adg.spdx.json`, `libcurl.so_adg.spdx.json` | **Created** (initial) |
| c-cpp/ffmpeg | `ffmpeg_adg.spdx.json`, `ffprobe_adg.spdx.json`, 4 lib `*_adg.spdx.json` | **Created** (initial, 6 files) |
| c-cpp/nmap | `nmap_adg.spdx.json`, `ncat_adg.spdx.json`, `nping_adg.spdx.json` | **Created** (initial) |
| c-cpp/redis | `redis-server_adg.spdx.json`, `redis-cli_adg.spdx.json` | **Created** (initial) |
| rust/dura | `dura_adg.spdx.json` | **Created** (initial) |

472 tests passing, 99% coverage.

**Approved by:** user (2026-03-11)
