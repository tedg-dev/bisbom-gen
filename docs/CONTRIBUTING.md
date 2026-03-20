# Contributing to OmniBOR Analysis

Thank you for your interest in contributing. This document outlines the workflow, conventions, and processes for this project.

## Table of Contents

- [Branch Workflow](#branch-workflow)
- [Commit Messages](#commit-messages)
- [Pull Requests](#pull-requests)
- [Code Style](#code-style)
- [Testing](#testing)
- [Adding a New Target Repository](#adding-a-new-target-repository)
- [Documentation](#documentation)

## Branch Workflow

This project follows a **PR-first workflow**. All changes go through pull requests.

- **Never** commit directly to `main`
- Always work on a feature branch and merge via PR
- Use conventional branch name prefixes:

| Prefix | Use Case |
|--------|----------|
| `feat/` | New features or capabilities |
| `fix/` | Bug fixes |
| `docs/` | Documentation-only changes |
| `chore/` | Maintenance, dependency updates, config changes |
| `test/` | Test additions or modifications |

**Examples:**
```
feat/add-openssl-target
fix/bomtrace-path-resolution
docs/update-spdx-methodology
chore/update-dockerfile-dependencies
```

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>(<scope>): <short description>

<optional body>
```

**Types:** `feat`, `fix`, `docs`, `chore`, `test`, `refactor`, `ci`

**Examples:**
```
feat(app): add OpenSSL as target repository
fix(docker): resolve bomtrace3 SYS_PTRACE permission issue
docs(readme): add FFmpeg analysis results
chore(docker): update Ubuntu base image to 22.04.4
test(spdx): add unit tests for SPDX package extraction
```

## Pull Requests

### Creating a PR

1. Create a feature branch from `main`
2. Make your changes
3. Ensure all tests pass (if applicable)
4. Push your branch and open a PR
5. Fill out the PR template completely

### PR Review Checklist

- [ ] Branch is up to date with `main`
- [ ] Changes are scoped and focused (one concern per PR)
- [ ] Documentation is updated if behavior changes
- [ ] No secrets or credentials are included
- [ ] `.gitignore` is updated if new generated file types are introduced

## Code Style

### Python

- Follow PEP 8
- Use type hints where practical
- Use `python3` explicitly (not `python`)
- Use `pathlib.Path` for file paths
- Use `yaml.safe_load()` (never `yaml.load()`)

### YAML

- 2-space indentation
- Use quotes for strings that could be misinterpreted

### Markdown

- Use ATX-style headers (`#`, `##`, `###`)
- Use fenced code blocks with language identifiers
- One sentence per line in prose (for cleaner diffs)

### Docker

- Pin base image versions (e.g., `ubuntu:22.04`, not `ubuntu:latest`)
- Combine `RUN` commands to reduce layers
- Clean up apt cache in the same layer as install

## Testing

- Run analysis scripts against at least one target repo before submitting changes to `app/`
- Verify Docker image builds successfully after Dockerfile changes
- Test inside the container, not on the macOS host

```bash
# Build and verify
docker-compose -f docker/docker-compose.yml build
docker-compose -f docker/docker-compose.yml run --rm omnibor-env bomtrace3 --version

# Run analysis
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo curl
```

## Adding a New Target Repository

### 1. Update `app/config.yaml`

Add a new entry under `repos:`:

```yaml
repos:
  newrepo:
    url: https://github.com/org/newrepo.git
    branch: main
    language: c-cpp          # c-cpp, rust, go, or java
    build_steps:
      - autoreconf -fi
      - ./configure --with-xxx
      - make -j$(nproc)
    clean_cmd: make clean
    description: "Short description of the project"
    output_binaries:
      - path/to/binary
      - path/to/libfoo.so
```

For Rust repos, use `language: rust` and `cargo build --release`:

```yaml
  mycrateproject:
    url: https://github.com/org/mycrateproject.git
    branch: main
    language: rust
    build_steps:
      - cargo build --release
    clean_cmd: cargo clean
    description: "Short description"
    output_binaries:
      - target/release/mycrateproject
```

> **Important:** For C/C++ repos, the last entry in `build_steps` must be the `make` command — this is the step that gets wrapped with `bomtrace3`. For Rust repos, it must be `cargo build`.
>
> **Note:** For Java repos, use `language: java` and `mvn package -DskipTests -q` as the build step. Java uses strace-based post-build analysis instead of bomtrace.

### 2. Add build dependencies to `docker/Dockerfile`

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfoo-dev \
    libbar-dev \
    && rm -rf /var/lib/apt/lists/*
```

### 3. Rebuild the Docker image

```bash
docker-compose -f docker/docker-compose.yml build
```

### 4. Create output and docs directories

Directories are created automatically by `analyze.py` using the `{lang}/{repo}/{ts}/` convention. No manual setup needed.

### 5. Test the build manually first

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env bash
cd /workspace/repos
git clone --depth 1 https://github.com/org/newrepo.git
cd newrepo
# Run build steps manually to verify they work
```

### 6. Run analysis

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo newrepo
```

## Documentation

- All analysis results go in `docs/{lang}/{repo}/{ts}/` (e.g., `docs/rust/oxipng/2026-03-06_2235/build.md`)
- Cross-repo summaries go in `docs/summary/`
- Runtime/performance metrics go in `docs/runtime/{lang}/{repo}/{ts}/`
- `{lang}` is `c-cpp`, `rust`, `go`, or `java`. `{ts}` is `YYYY-MM-DD_HHMM`.
- Update `README.md` when adding new target repos or changing workflows
