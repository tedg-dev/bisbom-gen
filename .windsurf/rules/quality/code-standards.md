---
description: Universal code quality standards for all languages
trigger: always_on
priority: critical
---

# Code Standards

These rules apply to every file in every language. Language-specific
rules in `lang/*.md` supplement but never override these.

## Naming

- **Variables/functions**: descriptive, lower_snake_case (Python/Rust/C) or
  camelCase (Java/Go) per language convention
- **Classes/types**: PascalCase in all languages
- **Constants**: UPPER_SNAKE_CASE
- **Files/modules**: lower_snake_case; no spaces, no uppercase
- **Boolean variables**: prefix with `is_`, `has_`, `can_`, `should_`

## Formatting

- Consistent indentation — use the project's configured formatter
- Max line length: follow the project standard (typically 80–100 characters)
- One blank line between functions; two blank lines between top-level classes
- No trailing whitespace; files end with a single newline
- Imports always at the top of the file, grouped by: stdlib → third-party → local

## Error Handling

- **Explicit error types**: use language-specific error hierarchies, never
  generic catch-all exceptions without re-raising or logging
- **Meaningful messages**: error messages must describe what failed and why,
  not just "error occurred"
- **Graceful degradation**: when a non-critical operation fails, log the
  failure and continue — do not crash the entire pipeline
- **No silent failures**: every `catch`/`except`/`recover` must either log,
  re-raise, or return an error — never swallow silently

## Documentation

- Code should be self-documenting — comments explain *why*, not *what*
- Every public class and function must have a docstring/doc comment
- Module-level docstrings describe the module's purpose and key classes
- Inline comments are for non-obvious business logic only

## Generic Code — No Hardcoded Values

- All application code MUST be generic and config-driven
- Never hardcode entity names, file paths, or environment-specific values
  in executable code
- Comments and docstrings may use specific names as illustrative examples
- Test fixtures may reference specific values when testing specific scenarios
- Config files (YAML, TOML, JSON) are expected to contain specific values

## Dependency Hygiene

- Before adding any dependency, verify it is actively maintained
- Only enable features/modules you actually use
- Pin dependency versions — use exact versions for applications,
  compatible ranges for libraries
- After changing any dependency, verify the entire project compiles and
  tests pass

## File Organization

- One concern per file — do not mix unrelated classes or functions
- Group related files into packages/modules with clear names
- Shared utilities live in a single canonical location (e.g., `utils/`,
  `common/`, `config/`)
- Language-specific pipeline steps that share structure should use a common
  base, not copy-paste

## Code Review Checklist (for Cascade self-review)

Before declaring any code change complete, verify:

- [ ] All new code follows existing project style
- [ ] No unused imports, variables, or dead code
- [ ] Error handling is explicit — no bare except / empty catch
- [ ] Docstrings on all new public APIs
- [ ] No hardcoded values that should be configurable
- [ ] File sizes remain under 400 lines
- [ ] DRY — no duplicated logic
