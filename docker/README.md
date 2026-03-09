# Docker Environment

Linux container for OmniBOR build interception.

## What's Inside

- Ubuntu 22.04 base (linux/amd64 — required, see below)
- gcc, clang, make, cmake, autoconf, libtool
- Rust toolchain (rustup + stable, minimal profile)
- Go SDK 1.26.0
- bomtrace2 and bomtrace3 (compiled from omnibor/bomsh + strace v6.11)
- Python 3 + bomsh scripts
- Syft (used internally by bomsh_sbom.py for baseline SPDX scaffolding)
- Build dependencies for target repos (OpenSSL-dev, zlib-dev, FFmpeg libs, etc.)

## Usage

```bash
docker-compose -f docker/docker-compose.yml build
docker-compose -f docker/docker-compose.yml run --rm omnibor-env bash
```

The `repos/`, `output/`, `app/`, and `docs/` directories are mounted as volumes so artifacts persist on the host.

## Architecture Requirement: linux/amd64

This image **must** be built for `linux/amd64` (x86_64). The `platform: linux/amd64` directive in `docker-compose.yml` enforces this.

**Why:** bomtrace3's `bomsh_hook.c` includes `<sys/reg.h>`, an x86-only header that does not exist on ARM64. There is no ARM64 port of bomtrace3.

**On Apple Silicon (M1/M2/M3):** Docker Desktop uses QEMU to emulate x86_64. The build works but is significantly slower (~30+ minutes vs ~15 minutes on native x86).

## Strace Version Pin: v6.11

Both bomtrace2 and bomtrace3 are built by patching the [strace](https://github.com/strace/strace) source code with patches from [omnibor/bomsh](https://github.com/omnibor/bomsh). These patches are fragile and only apply cleanly against specific strace versions.

- **Pinned to:** `v6.11` (verified 2026-02-10)
- **How to test a new version:** `git clone --branch <TAG> ... && patch --dry-run -p1 < bomtrace3.patch`
- **Both patches must be verified** — bomtrace2.patch and bomtrace3.patch may break at different strace versions

## Configure Flags: --enable-mpers=check

We use `--enable-mpers=check` to match the bomsh project's own `.devcontainer/Dockerfile`. Do **not** use `--disable-mpers` as it can cause header resolution issues on some platforms.

## Parallel Build Race Condition (bomtrace3)

bomtrace3 **must** be built with `make -j1` (serial). The bomtrace3 patch copies custom source files (`bomsh_hook.c`, `bomsh_config.c`, etc.) into the strace `src/` directory. These files `#include "printers.h"` — a file that is **generated during the build** by strace's Makefile.

The patched `Makefile.am` does not correctly declare this dependency, so with parallel make (`-j$(nproc)`), the compiler can attempt to compile `bomsh_hook.c` before `printers.h` has been generated, causing a build failure.

bomtrace2 does **not** have this issue because its patch does not add custom `.c` files.

## Python Dependency Management

Python runtime dependencies are managed via `requirements.txt` at the project root. This file is the **single source of truth** — used by both the Docker container and local development.

| File | Purpose | Where installed |
|------|---------|-----------------|
| `requirements.txt` | Runtime deps (e.g. PyYAML) | Docker container + local `.venv` |
| `requirements-dev.txt` | Dev/test deps (pytest, coverage) | Local `.venv` only |

**Adding a new Python dependency:**

1. Add it to `requirements.txt` (with pinned version)
2. Run `pip install -r requirements.txt` locally
3. Rebuild the Docker image: `docker-compose -f docker/docker-compose.yml build`

**Do NOT** add ad-hoc `pip install` commands to the Dockerfile. The Dockerfile `COPY`s `requirements.txt` from the project root and installs from it.

**Local setup:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## C/C++ Build Dependencies (apt_deps)

Each target repo in `config.yaml` has an `apt_deps` list specifying the `-dev` packages required for its build. These packages must be installed in the Docker image.

**How it works:**

1. `config.yaml` lists `apt_deps` per repo (mapped to `--with-*` / `--enable-*` configure flags)
2. `analyze.py`'s `DependencyValidator` checks all `apt_deps` are installed before building
3. If any are missing, it prints an actionable error with the exact `apt-get install` command

**Adding a new target repo:**

1. Run `python3 app/add_repo.py <repo>` — it auto-detects dependencies and generates `apt_deps`
2. Add any missing packages to the Dockerfile's `apt-get install` block
3. Rebuild the image: `docker-compose -f docker/docker-compose.yml build`

**Why explicit lists?** C/C++ `./configure` scripts auto-detect libraries at build time. A missing `-dev` package may silently disable a feature or cause a cryptic error later. Explicit `apt_deps` make the contract clear and verifiable.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `sys/reg.h: No such file or directory` | Building on ARM64 without platform override | Ensure `platform: linux/amd64` is in docker-compose.yml |
| `printers.h: No such file or directory` | Parallel build race condition in bomtrace3 | Use `make -j1` for bomtrace3 (not `-j$(nproc)`) |
| `stringop-overflow` error in `bomsh_hook.c` | Upstream bomsh bug: `strcpy` into `PATH_MAX` buffer triggers GCC warning, `-Werror` makes it fatal | Pass `CFLAGS="-g -O2 -Wno-error=stringop-overflow"` to `make` for bomtrace3 |
| `patch: Hunk FAILED` | strace version incompatible with bomsh patches | Pin strace to a known-good tag (currently v6.11) |
| Build takes 30+ minutes | QEMU emulation on Apple Silicon | Normal — x86 emulation is slow; layers are cached after first build |
| `ModuleNotFoundError: No module named 'yaml'` | Python deps not installed in container | Rebuild image after verifying `requirements.txt` exists at project root |
