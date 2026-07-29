---
description: Languages supported by the current OmniBOR/bomsh version
---

# Supported Languages

This file defines which programming languages are supported by the current
OmniBOR/bomsh installation for build interception and SPDX generation.

## Current Supported Languages (Bisbom bomsh v2026.1)

| Language | Config Value | Tracer | Notes |
|----------|-------------|--------|-------|
| **C/C++** | `c-cpp` | bomtrace3 | Full ptrace-based interception |
| **Rust** | `rust` | bomtrace2 | Traces rustc via default bomtrace.conf |
| **Go** | `go` | bomtrace2 | Traces go compile/link via bomtrace_go.conf |
| **Java** | `java` | bomtrace2 | Traces javac, uses Maven dependency:tree |

## GitHub Language Mapping

GitHub API reports languages differently than our config values. This mapping
is used by the language validation check:

| GitHub Reports | Maps To | Supported |
|----------------|---------|-----------|
| C | c-cpp | ✓ |
| C++ | c-cpp | ✓ |
| Rust | rust | ✓ |
| Go | go | ✓ |
| Java | java | ✓ |
| Kotlin | java | ✓ (builds with Maven/Gradle) |
| Scala | java | ✓ (builds with Maven/Gradle) |
| Python | — | ✗ |
| JavaScript | — | ✗ |
| TypeScript | — | ✗ |
| Ruby | — | ✗ |
| PHP | — | ✗ |
| Shell | — | ✗ (often mixed with C) |
| Makefile | — | ✗ (build system, not source) |

## Pre-Clone Validation Rule

Before cloning a new repository, the pipeline MUST:

1. Query GitHub API for the repository's languages (`/repos/{owner}/{repo}/languages`)
2. Check if the **primary language** (highest byte count) is supported
3. If unsupported, **abort the run** and report which languages were detected
4. Allow override via `--force` flag if the user knows the repo is buildable

## Updating This File

When OmniBOR/bomsh adds support for a new language:

1. Update the tables above
2. Update `app/pipeline/language_validator.py` with the new mapping
3. Update the version comment (e.g., "bomsh v2026.2")
4. Create language subdirectories with `.gitkeep` under **all** output
   categories to preserve the directory skeleton on fresh clone:
   ```
   output/binaries/<lang>/.gitkeep
   output/binary-scan/<lang>/.gitkeep
   output/build-logs/<lang>/.gitkeep
   output/bisbom/<lang>/.gitkeep
   output/runtime/<lang>/.gitkeep
   output/spdx/<lang>/.gitkeep
   ```
5. Commit the `.gitkeep` files (they are allowed through `.gitignore`)
