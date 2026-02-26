---
description: Add a new target repository for OmniBOR analysis
---

# Add a New Target Repository

Use `app/add_repo.py` to auto-discover repo metadata from GitHub and generate
the `config.yaml` entry. Requires `gh` CLI authenticated on the host.

## 1. Preview the generated config (dry-run, default)

The user provides just a repo name. Cascade runs:

```bash
.venv/bin/python3 app/add_repo.py <NAME>
```

Accepts: repo name (`curl`), owner/repo (`curl/curl`), or full GitHub URL.

The script will:
- Search GitHub for the canonical repository
- Detect the build system (autoconf, cmake, meson, make)
- Analyze configure.ac / CMakeLists.txt for dependency flags
- Identify output binaries from Makefile.am
- Cross-check required apt packages against the Dockerfile
- Display the generated config.yaml entry

## 2. Review the output with the user

Show the user the generated entry and ask them to confirm or adjust:
- Build steps (configure flags, build system)
- Output binaries
- Any missing Dockerfile packages

## 3. Write the config and create directories

Once the user approves:

```bash
.venv/bin/python3 app/add_repo.py <NAME> --write
```

This writes the entry to `app/config.yaml` and creates output directories.

## 4. Add missing Dockerfile packages (if any)

If the script reports missing apt packages, add them to `docker/Dockerfile`
in the main `apt-get install` block, then rebuild:

```bash
docker-compose -f docker/docker-compose.yml build
```

## 5. Run analysis

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo <NAME>
```

## Manual override

If the auto-detection is wrong, edit `app/config.yaml` directly. The key rules:
- Last `build_steps` entry must be the `make` command (gets wrapped with bomtrace3)
- `output_binaries` should list the main executables and shared libs

## Tips

- Test the build manually inside the container first before running analyze.py
- Use `docker-compose run --rm omnibor-env bash` to enter the container and experiment
- The script prefers C/C++ repos and exact name matches when searching GitHub
