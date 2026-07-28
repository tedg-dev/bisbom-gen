# Issue Regression Gate

## Rule

**Before implementing** any GitHub issue, evaluate whether the change
could affect pipeline output (SPDX, metadata, dynamic libs, PURL
generation, build steps, or config resolution). If yes, a system-level
regression run is required **after** implementation passes all unit
tests and before the PR is declared ready.

Report the regression assessment to the user during issue research,
**before** writing any code.

## When to Require a Regression Run

A regression run is required if the change touches or could affect:

- SPDX generation or emission (`emitter.py`, `generator.py`,
  `java_generator.py`, any `*_generator.py`)
- Dependency parsing (`parser.py`, `lang_parsers.py`,
  `maven_parser.py`, `gradle_parser.py`)
- Package resolution or PURL generation (`resolver.py`,
  `package_resolver.py`, `collect_metadata.py`,
  `collect_dynamic_libs.py`)
- Build pipeline (`builder.py`, `runners.py`, `lang_runners.py`,
  `facade.py`)
- Config schema or path resolution (`config.py`, `config.yaml`)
- Interception strategy (`interception.py`, `CommandRunner`)
- Visualization extraction logic (`extract.py`)
- Relationship type mapping (`relationships.py`)
- Vendored detection (`vendored.py`)
- Docker image changes (`Dockerfile`, `docker-compose.yml`)

A regression run is **not** required for:

- Pure documentation changes
- New ABC/interface definitions with no consumers yet
- Test-only changes
- Rule file changes
- New modules that are not wired into the pipeline

## Regression Test Repos

Run at least one repo per supported language. These repos were chosen
to exercise the widest set of pipeline code paths:

| Language | Repo | Why |
|----------|------|-----|
| C/C++ | `redis` | Pure make, 8 vendored libs under deps/, 2 binaries, STATIC_LINK + DYNAMIC_LINK |
| Go | `fzf` | Clean Go build, vendored module detection, fast turnaround |
| Rust | `dura` | Largest Rust dep tree (42 direct + 35 transitive), git bindings |
| Java | `dependency-check` | Multi-module, shade plugin, deepest dep hierarchy |

## Regression Run Procedure

1. Ensure EC2 is running and code is synced
2. Run each regression repo: `analyze.py --repo <name>`
3. Compare SPDX output against the most recent golden/baseline run
4. Report any differences to the user per golden-file-policy
5. Only declare the issue complete if regression output matches

## Assessment Format

When evaluating an issue, report to the user:

```
### Regression Assessment: #<issue> [<title>]
- **Pipeline impact:** Yes/No
- **Reason:** <why it does or does not affect output>
- **Regression repos needed:** <list or "None">
```
