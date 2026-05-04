# Resolver Regression Testing

## Overview

The `PackageResolver` abstraction maps file paths to OS package metadata.
Three implementations exist:

| Resolver | Distro family | Package manager |
|----------|---------------|-----------------|
| `DpkgResolver` | Debian, Ubuntu | `dpkg -S`, `dpkg-query -W` |
| `RpmResolver` | RHEL, CentOS, Fedora, Rocky, Alma | `rpm -qf`, `rpm -q --queryformat` |
| `ApkResolver` | Alpine | `apk info --who-owns`, `apk info -v/-a` |

## Test Coverage Matrix

### Unit tests (mocked subprocess)

Every resolver has a dedicated test file with 100% coverage of:

| Test area | `DpkgResolver` | `RpmResolver` | `ApkResolver` |
|-----------|----------------|---------------|----------------|
| `resolve()` success | ✅ | ✅ | ✅ |
| `resolve()` failure (unowned) | ✅ | ✅ | ✅ |
| `resolve()` failure (error) | ✅ | ✅ | ✅ |
| Metadata caching | ✅ | ✅ | ✅ |
| `purl_scheme()` | ✅ | ✅ | ✅ |
| `make_purl()` integration | ✅ | ✅ | ✅ |
| `distro_version_qualifier` | ✅ | ✅ | ✅ |
| Source package parsing | ✅ | ✅ (SRPM) | ✅ (origin) |

Files:
- `tests/test_dpkg_resolver.py`
- `tests/test_rpm_resolver.py`
- `tests/test_apk_resolver.py`
- `tests/test_package_resolver.py` (ABC + factory)

### Integration tests (real binaries)

`tests/test_resolver_integration.py` runs against real package manager
binaries. Tests auto-skip when the binary is not available.

| Test | dpkg | rpm | apk |
|------|------|-----|-----|
| Resolve known system binary | ✅ | ✅ | ✅ |
| Resolve nonexistent path → None | ✅ | ✅ | ✅ |
| PURL scheme matches host | ✅ | ✅ | ✅ |
| End-to-end PURL from resolved file | ✅ | ✅ | ✅ |
| Caching with real packages | ✅ | — | — |
| `auto_detect_resolver()` factory | ✅ | ✅ | ✅ |
| Startup logging | ✅ | ✅ | ✅ |

### System regression (full pipeline)

The full pipeline builds a target repo inside Docker, runs bomtrace3
interception, collects metadata via `collect_metadata.py` (which now
uses `PackageResolver`), and generates SPDX output.

Currently, the build container is **Ubuntu 22.04**, so only
`DpkgResolver` gets full pipeline coverage. See
[multi-distro-testing.md](multi-distro-testing.md) for plans to expand.

## When to Run Resolver Regression Tests

| Change | Unit tests | Multi-distro containers | Full pipeline |
|--------|-----------|------------------------|---------------|
| New resolver implementation | ✅ | ✅ (new distro) | — |
| Bug fix in existing resolver | ✅ | ✅ (affected distro) | ✅ (1+ repos) |
| `collect_metadata.py` refactoring | ✅ | — | ✅ (ALL repos) |
| `auto_detect_resolver()` changes | ✅ | ✅ (all distros) | — |
| PURL format changes | ✅ | ✅ (all distros) | ✅ (1 repo/lang) |

## Running Resolver Regression

### Quick: Unit tests only

```bash
pytest tests/test_dpkg_resolver.py tests/test_rpm_resolver.py \
  tests/test_apk_resolver.py tests/test_package_resolver.py -v
```

### Medium: Multi-distro integration

```bash
scripts/test-resolvers-multi-distro.sh
```

This spins up Ubuntu, Fedora, and Alpine containers and runs the
integration tests in each. See [multi-distro-testing.md](multi-distro-testing.md).

### Full: System regression

```bash
# On EC2, after syncing code and rebuilding Docker:
# Run all repos and compare against golden baselines
python3 scripts/compare_golden.py tests/golden/spdx output/spdx
```

## Acceptance Criteria for Resolver Changes

1. All unit tests pass with ≥95% coverage per file
2. Multi-distro integration tests pass on all three distro families
3. For changes that affect pipeline output: golden SPDX comparison
   shows zero diffs (or diffs are explicitly approved by maintainer)
