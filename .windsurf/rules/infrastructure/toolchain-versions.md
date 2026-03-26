---
description: Multi-version toolchain management for build environments
---

# Toolchain Version Management

The Docker image provides multiple versions of build tools for each language.
Repos can specify which version to use in their `build_steps` in `config.yaml`.

## C/C++

| Tool | Default | Alternative | How to Override |
|------|---------|-------------|-----------------|
| gcc/g++ | apt (11.x) | — | `CC=gcc-12 CXX=g++-12` in build_steps |
| clang/clang++ | apt (14.x) | — | `CC=clang CXX=clang++` in build_steps |
| make | apt | — | — |
| cmake | apt | — | — |

Example override:
```yaml
build_steps:
  - CC=clang CXX=clang++ ./configure
  - make -j$(nproc)
```

## Go

| Tool | Default | Path | How to Override |
|------|---------|------|-----------------|
| go | 1.26.0 | /usr/local/go/bin/go | Install specific version in build_steps |

Example override for older Go:
```yaml
build_steps:
  - GO_VERSION=1.21.0 && wget -q "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" -O /tmp/go.tar.gz && tar -C /tmp -xzf /tmp/go.tar.gz
  - /tmp/go/bin/go build -a -o myapp .
```

## Rust

| Tool | Default | How to Override |
|------|---------|-----------------|
| rustc/cargo | stable | `rustup install 1.75.0 && rustup default 1.75.0` |

Example override:
```yaml
build_steps:
  - rustup install 1.70.0 && rustup default 1.70.0
  - cargo build --release
```

## Java

| Tool | Default | Alternative | Command |
|------|---------|-------------|---------|
| Maven | 3.9.9 | 3.6.3 | `mvn` (default), `mvn3.9`, `mvn3.6` |
| JDK | 17 | — | — |

Example using older Maven:
```yaml
build_steps:
  - mvn3.6 package -DskipTests
```

## Adding New Versions

When adding a new toolchain version:

1. Install both old and new versions in Dockerfile
2. Create symlinks for explicit version selection (e.g., `mvn3.6`, `mvn3.9`)
3. Set the newer version as the default
4. Document in this file
5. Update relevant repos' `build_steps` if needed
