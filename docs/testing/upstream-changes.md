# Testing Policy for Upstream Changes

## Scope

This policy covers testing requirements when upstream repositories
or tools change. "Upstream" includes:

1. **Build interception tools** — bomsh, bomtrace3, bomtrace2
2. **Target repositories** — repos we analyze (redis, curl, fzf, etc.)
3. **OS packages** — system libraries in the build container
4. **Docker base image** — Ubuntu version, installed packages
5. **Python dependencies** — libraries used by the analysis pipeline

## Risk Classification

| Upstream change | Risk level | Required testing |
|-----------------|------------|------------------|
| bomsh/bomtrace version bump | **Critical** | ALL repos, full pipeline |
| Docker base image update | **Critical** | ALL repos, full pipeline |
| Target repo version bump | **High** | Affected repo, full pipeline |
| Python dependency update | **Medium** | Full unit + integration suite |
| OS package update (apt) | **Medium** | ALL repos (metadata may change) |
| New target repo added | **Low** | New repo only |
| Test-only changes | **None** | Unit tests only |

## bomsh / bomtrace Changes

These tools perform build interception — they are the foundation of
all bisbom-gen analysis. Any change can affect every output artifact.

### Before updating bomsh/bomtrace:

1. Record the current version/commit SHA
2. Run ALL regression repos and save output as "before" baseline
3. Update the tool
4. Run ALL regression repos again
5. Compare every output file against "before" baseline
6. Report ALL differences per golden file policy
7. Only proceed if differences are understood and approved

### What to compare:

- `bomsh_omnibor_treedb` — file count, hash values
- `component_metadata.json` — package counts, versions
- All `*.spdx.json` — packages, relationships, PURLs, versions
- `*.html` — visual verification (manual spot check)

### Specific scenarios:

| bomsh change | What could break | Test focus |
|--------------|------------------|------------|
| Hook script logic | Missed file interceptions | Treedb completeness |
| OmniBOR hash algorithm | All hash values | ADG, external refs |
| Python library changes | Metadata parsing | SPDX generation |
| ptrace behavior | Build interception | Treedb file counts |
| New language support | Existing languages | Regression on all langs |

## Target Repository Changes

When bumping a target repo to a new version (e.g., redis 7.2.4 → 7.4.0):

### Expected changes:
- Package version in SPDX root package
- Source file counts (new/removed files)
- Dependency versions (vendored libs may update)
- Dynamic library versions (system deps may change)

### Testing procedure:
1. Run analysis on the new version
2. Compare against golden baseline for the old version
3. Review ALL differences — categorize as:
   - **Expected** — version bumps, new dependencies
   - **Unexpected** — missing packages, broken relationships
4. If all differences are expected: update golden files
5. If unexpected differences: investigate before proceeding

### Do NOT blindly update golden files

Even when bumping a target repo version, some differences may
indicate a pipeline bug exposed by the new code. Always review.

## Docker Base Image Changes

Updating the Docker base image (e.g., Ubuntu 22.04 → 24.04) affects:

- All system package versions (`dpkg-query` results change)
- GCC version and behavior
- Dynamic library versions and paths
- Potentially: bomtrace3 compatibility

### Testing procedure:
1. Build new Docker image
2. Run ALL regression repos
3. Compare against golden baselines
4. Expect: version changes in system packages
5. Verify: no missing packages, no broken relationships
6. If validated: update ALL golden files in one batch

## Python Dependency Changes

### pip dependency updates:
1. Run full unit test suite
2. Run multi-distro integration tests
3. If any test framework changes: verify test collection counts

### Adding new dependencies:
1. Verify the package is actively maintained
2. Check for known CVEs (`pip audit`)
3. Pin the exact version in `requirements.txt`
4. Run full test suite

## OS Package Changes (apt updates in container)

When the Docker container gets apt updates:

- System library versions may change
- `collect_metadata.py` output may differ
- SPDX system dependency packages may have new versions

### Testing:
1. Run ALL regression repos
2. Focus on `component_metadata.json` diffs
3. Version bumps in system packages are expected
4. Missing or extra packages require investigation

## Regression Repo Selection

### Current regression repos (36 golden files):

| Language | Repo | Binaries | Golden files |
|----------|------|----------|--------------|
| C/C++ | `redis` | 2 | 4 |
| C/C++ | `curl` | 2 | 4 |
| C/C++ | `nmap` | 3 | 6 |
| C/C++ | `ffmpeg` | 5 | 10 |
| Go | `lazygit` | 1 | 2 |
| Rust | `dura` | 1 | 2 |
| Rust | `oxipng` | 1 | 2 |
| Java | `checkstyle` | 1 | 2 |
| Java | `jsoup` | 1 | 2 |

### When to run which repos:

| Change scope | Repos to test |
|--------------|---------------|
| Language-agnostic (resolver, metadata, emitter) | ALL repos |
| C/C++ specific (make parsing, vendored detection) | redis, curl, nmap, ffmpeg |
| Go specific (go module parsing) | lazygit |
| Rust specific (cargo parsing) | dura, oxipng |
| Java specific (maven/gradle parsing) | checkstyle, jsoup |
| bomsh/bomtrace update | ALL repos |
| Docker image update | ALL repos |

## Reporting Requirements

For every upstream change that triggers regression testing:

1. **Before/after summary** — what changed in the upstream
2. **Diff report** — every difference in every output file
3. **Classification** — expected vs unexpected for each diff
4. **Approval** — explicit maintainer sign-off before updating goldens
5. **Git record** — golden file updates in a dedicated commit with
   clear message referencing the upstream change

## Anti-Patterns

- ❌ Updating golden files without reviewing diffs
- ❌ Assuming version bumps are "harmless"
- ❌ Running only one repo when the change is language-agnostic
- ❌ Skipping regression tests "because unit tests pass"
- ❌ Dismissing differences as "likely upstream"
- ❌ Running regression on a dirty working tree
