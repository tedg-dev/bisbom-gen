---
description: All builds must produce release/production binaries, not debug builds
trigger: always_on
---

# Release Build Policy

All bisbom-gen analysis builds MUST target **release/production binaries**.
SPDX SBOMs must reflect what ships to customers, not debug or development artifacts.

## Language-Specific Requirements

### C/C++ (autoconf/make)

- `./configure` without `--enable-debug` or `CFLAGS="-g -O0"`
- `make` with default optimization (typically `-O2`)
- Never pass `DEBUG=1`, `ASAN=1`, or sanitizer flags
- Verify: output binaries should NOT be in a `debug/` directory

### Rust

- Always `cargo build --release` (never plain `cargo build`)
- Output path must be `target/release/`, not `target/debug/`

### Go

- Always include `-trimpath -ldflags="-s -w"` in `go build`
- `-trimpath` strips local filesystem paths from the binary
- `-ldflags="-s -w"` strips symbol table and DWARF debug info
- `-a` is still required for bomtrace2 cache bypass
- Full pattern: `go build -a -trimpath -ldflags="-s -w" -o <binary> .`

### Java (Maven)

- Always `mvn package -DskipTests` (skip test execution)
- Standard Maven JAR packaging only includes `target/classes/` (main sources)
- Test classes (`target/test-classes/`) are NOT in the production JAR
- SPDX generation must exclude `test`-scope dependencies
- If a project's build plugins (shade, assembly) include test artifacts
  in the production JAR, annotate those packages in the SPDX `comment` field

## SPDX Comment Annotations

When a dependency is test-scope but appears in the production binary
(e.g., via shade plugin), add to the SPDX package `comment` field:

```
Test-scope dependency included in production JAR via <plugin>.
```

When test-scope dependencies are excluded (standard behavior), the
build doc should note: "N test-scope dependencies excluded from SPDX."

## Build Documentation

Every build doc (`output/build-logs/{lang}/{repo}/{ts}/build.md`) must include
a **Release Build Verification** section reporting:

- Whether the build is classified as release or debug
- Language-specific flags that confirm release mode
- Any warnings (e.g., missing optimization flags)
- For Java: count of test-scope dependencies excluded

## Console Output

The pipeline must print release-build classification to the console
before the build starts, e.g.:

```
[RELEASE] curl: release build confirmed (./configure + make, no debug flags)
[RELEASE] oxipng: release build confirmed (cargo build --release)
[WARNING] fzf: missing -trimpath -ldflags="-s -w" in go build
```

## Adding New Repos

When adding a new target repository (via `/add-repo` or manually):

1. Verify the build steps produce release binaries
2. Check for debug/development flags and remove them
3. For Java: confirm the JAR does not bundle test classes
4. Run analysis and verify the SPDX reflects production components only
