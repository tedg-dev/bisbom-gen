# Multi-Distro Testing

## Problem

The build container runs Ubuntu 22.04, so the full pipeline only
exercises `DpkgResolver`. To verify `RpmResolver` and `ApkResolver`
work correctly against real package databases, we need to run tests
inside Fedora and Alpine containers.

## Approach

We use lightweight Docker containers that install Python, mount
the project, and run the resolver integration test suite. No
bomtrace3 or full pipeline — just the resolver layer.

## Container Matrix

| Container | Image | Tests exercised | Key binary |
|-----------|-------|-----------------|------------|
| Ubuntu 22.04 | `ubuntu:22.04` | `requires_dpkg` | `/usr/bin/dpkg` |
| Fedora 39 | `fedora:39` | `requires_rpm` | `/usr/bin/rpm` |
| Alpine 3.18 | `alpine:3.18` | `requires_apk` | `/sbin/apk` |

## Running Multi-Distro Tests

### Automated script

```bash
scripts/test-resolvers-multi-distro.sh
```

The script:
1. Builds a minimal Python environment in each container
2. Installs project dependencies from `requirements.txt`
3. Runs `pytest -m requires_<manager>` with verbose output
4. Reports pass/fail per distro
5. Exits with non-zero status if any distro fails

### Manual (single distro)

```bash
# Fedora only:
docker run --rm -v "$PWD":/workspace -w /workspace fedora:39 \
  bash -c "dnf install -y python3 python3-pip && \
  pip3 install --quiet -r requirements.txt && \
  python3 -m pytest tests/test_resolver_integration.py \
    -m requires_rpm -v"
```

## What Gets Tested

Each container runs the same integration test suite from
`tests/test_resolver_integration.py`:

1. **File → package resolution** — resolves a known system binary
   (e.g., `/usr/bin/rpm` on Fedora, `/sbin/apk` on Alpine)
2. **Nonexistent path** — confirms `resolve()` returns `None`
3. **PURL scheme** — verifies the scheme matches the distro
   (e.g., `pkg:rpm/fedora`, `pkg:apk/alpine`)
4. **End-to-end PURL** — resolves a file and builds a full PURL
5. **`auto_detect_resolver()` factory** — confirms correct resolver
   is selected based on `/etc/os-release`
6. **Startup logging** — verifies log message includes distro name

## Adding a New Distro

To add support for a new distro family:

1. Implement the resolver (e.g., `PacmanResolver` for Arch)
2. Add integration tests to `tests/test_resolver_integration.py`
   with a new `@pytest.mark.requires_pacman` marker
3. Register the marker in `tests/conftest.py`
4. Add a new container to `scripts/test-resolvers-multi-distro.sh`
5. Update the container matrix table above

## Limitations

- **No full pipeline coverage** on non-Ubuntu distros — bomtrace3
  is only validated on Debian/Ubuntu (see `docs/aws-ec2-migration-recommendation.md`)
- **Network required** — containers need network access to install
  Python packages on first run
- **x86_64 only** — all containers run `linux/amd64` to match the
  build environment

## CI Integration (Future)

These multi-distro tests can be added to GitHub Actions:

```yaml
jobs:
  resolver-integration:
    strategy:
      matrix:
        include:
          - image: ubuntu:22.04
            marker: requires_dpkg
            setup: "apt-get update && apt-get install -y python3 python3-pip"
          - image: fedora:39
            marker: requires_rpm
            setup: "dnf install -y python3 python3-pip"
          - image: alpine:3.18
            marker: requires_apk
            setup: "apk add python3 py3-pip"
    container: ${{ matrix.image }}
    steps:
      - uses: actions/checkout@v4
      - run: ${{ matrix.setup }}
      - run: pip3 install -r requirements.txt
      - run: python3 -m pytest tests/test_resolver_integration.py -m ${{ matrix.marker }} -v
```
