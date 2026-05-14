# Testing Strategy

This directory documents the testing strategy for omnibor-analysis.
The goal is **exceptional test coverage** with clear, repeatable
verification for every code change.

## Testing Layers

| Layer | Scope | Where it runs | Speed |
|-------|-------|---------------|-------|
| **Unit tests** | Individual functions and classes | macOS / any host | < 5 sec |
| **Integration tests** | Real OS binaries, mocked pipeline | Linux containers | < 30 sec |
| **System regression** | Full pipeline (build → intercept → SPDX) | EC2 + Docker | 5–20 min/repo |
| **Golden file comparison** | SPDX output diff against baselines | macOS / EC2 | < 10 sec |

## Test Locations

```
tests/
├── conftest.py                    # Shared config, custom markers
├── test_*.py                      # Unit tests (run everywhere)
├── test_resolver_integration.py   # Integration tests (skip if binary missing)
├── test_spdx_regression.py        # Golden file integrity checks
└── golden/spdx/                   # Golden baseline SPDX files
    ├── c-cpp/{redis,curl,nmap,ffmpeg}/
    ├── go/{lazygit}/
    ├── rust/{dura,oxipng}/
    └── java/{checkstyle,jsoup}/

scripts/
├── compare_golden.py              # Diff new SPDX against golden baselines
└── test-resolvers-multi-distro.sh # Multi-distro resolver integration tests
```

## Pytest Markers

| Marker | Meaning |
|--------|---------|
| `integration` | Requires real OS package manager binaries |
| `requires_dpkg` | Needs dpkg/dpkg-query (Debian/Ubuntu) |
| `requires_rpm` | Needs rpm (Fedora/RHEL/Rocky) |
| `requires_apk` | Needs apk (Alpine) |

### Running by marker

```bash
# All tests (integration auto-skips on macOS):
pytest tests/ -x -q

# Only integration tests:
pytest tests/ -m integration -v

# Skip integration tests:
pytest tests/ -m "not integration"

# Only dpkg resolver tests (inside Ubuntu container):
pytest tests/ -m requires_dpkg -v
```

## Documents in This Directory

- **[resolver-regression.md](resolver-regression.md)** — Resolver-specific
  regression testing: what to test, when, and how
- **[multi-distro-testing.md](multi-distro-testing.md)** — Running tests
  against Fedora, Alpine, and Ubuntu containers
- **[upstream-changes.md](upstream-changes.md)** — Testing policy when
  upstream repositories (bomsh, bomtrace, target repos) change
- **[golden-file-testing.md](golden-file-testing.md)** — Golden file
  regression testing framework and update workflow

## Quick Reference: When to Run What

| Change type | Unit tests | Multi-distro | System regression |
|-------------|-----------|--------------|-------------------|
| New resolver or resolver fix | ✅ | ✅ | ✅ (1 repo) |
| `collect_metadata.py` changes | ✅ | — | ✅ (all repos) |
| SPDX emitter/generator changes | ✅ | — | ✅ (all repos) |
| Parser changes (lang-specific) | ✅ | — | ✅ (affected lang) |
| Config/build pipeline changes | ✅ | — | ✅ (all repos) |
| New target repo added | ✅ | — | ✅ (new repo only) |
| Test-only or docs-only | ✅ | — | — |
| Upstream bomsh/bomtrace update | ✅ | — | ✅ (ALL repos) |
