---
description: Python-specific best practices, tooling, and conventions
---

# Python Best Practices

## Project Structure

- **Python version**: Target Python 3.11+ unless the project requires older
- **Virtual environment**: Always use `.venv/` at the project root. Never
  install into the system Python
- **Package layout**: Use `app/` or `src/<package>/` as the package root.
  Tests live in `tests/` mirroring the source tree
- **requirements.txt**: Pin all direct dependencies with exact versions.
  Separate dev dependencies into `requirements-dev.txt` if needed
- **Imports**: Always absolute (`from app.module import Class`). Group by:
  stdlib → third-party → local, separated by blank lines

## Formatting & Linting

- **Formatter**: Black (line length 88) or Ruff format
- **Linter**: Flake8 + Pylint, or Ruff (all-in-one)
- **Type checking**: mypy with `--strict` for new projects; gradual adoption
  for existing projects
- **Import sorting**: isort (compatible with Black) or Ruff

## Idioms

- **f-strings** over `%` formatting or `.format()`
- **pathlib.Path** over `os.path` for all file system operations
- **dataclasses** or `TypedDict` for structured data; avoid plain dicts
  for internal APIs
- **Context managers** (`with` statement) for all resource management
- **List/dict comprehensions** over `map()`/`filter()` when readable
- **`enumerate()`** instead of manual index tracking
- **`if __name__ == "__main__"`** guard on all runnable scripts

## Error Handling

- Use specific exception types: `ValueError`, `FileNotFoundError`, `KeyError`
- Never use bare `except:` — always catch a specific type
- `except Exception` is acceptable only when re-raising or logging
- Provide meaningful error messages: `raise ValueError(f"Expected int, got {type(x)}")`

## Testing

- **Framework**: `unittest.TestCase` with `unittest.mock`, or `pytest`
- **Mocking**: `@patch("module.path.to.dependency")` — always patch where
  the dependency is *used*, not where it is *defined*
- **Temp files**: Use `tempfile.TemporaryDirectory()` for file I/O tests
- **Coverage**: `pytest-cov` with per-file reporting

## CI Configuration

- **Setup**: `actions/setup-python` with pinned version (e.g., `3.13`)
- **Cache**: `~/.cache/pip` and `.venv/` keyed on `requirements.txt` hash
- **Lint job**: `flake8 app/ tests/ && pylint app/`
- **Test job**: `.venv/bin/python3 -m pytest tests/ -x -q --cov=app`
- **Warnings as errors**: `pytest -W error` to catch deprecation warnings

## Dependency Audit

- `pip audit` or `safety check` to scan for known CVEs
- Review `pip list --outdated` periodically for security patches
