---
description: Build or rebuild the Docker container for OmniBOR analysis
---

# Docker Build

Build the Linux container with gcc, clang, bomtrace3, syft, and all build dependencies.

## 1. Build the image

// turbo
```bash
docker-compose -f docker/docker-compose.yml build
```

This takes 10-20 minutes on first build (compiles bomtrace2 and bomtrace3 from source).
Subsequent builds use Docker layer cache and are fast.

## 2. Verify bomtrace3 is available

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env bomtrace3 --version
```

## 3. Verify syft is available

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env syft version
```

## 4. Enter the container interactively

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env bash
```

## Notes

- The image is based on Ubuntu 22.04
- `SYS_PTRACE` capability is added automatically via docker-compose.yml
- Volumes are mounted so all repos/, output/, app/, and docs/ persist on the host
- If you add a new target repo with new build dependencies, update the Dockerfile and rebuild
