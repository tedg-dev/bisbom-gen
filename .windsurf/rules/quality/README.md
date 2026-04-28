# Quality Rules — Portable Kit

Portable, industry-standard quality rules for any Windsurf-powered
project. Copy this `quality/` folder into `.windsurf/rules/quality/`
of any new or existing project.

## Structure

| File | Scope | Purpose |
|------|-------|---------|
| `design-principles.md` | All languages | Architecture, patterns, anti-patterns |
| `testing-standards.md` | All languages | Test philosophy, isolation, coverage, regression |
| `security.md` | All languages | Secrets, input validation, dependency auditing |
| `ci-workflow-standards.md` | All languages | GitHub Actions, CI/CD pipeline design |
| `lang/*.md` | Per-language | Language-specific idioms and conventions |

Other quality rules (Cascade behavior, golden file policy, pre-commit
gates, code standards) live in `cascade/` and `project/` — they are
project-specific and reference the portable rules here.

## Language Files

| File | Language |
|------|----------|
| `lang/python.md` | Python |
| `lang/rust.md` | Rust |
| `lang/go.md` | Go |
| `lang/java.md` | Java (Maven/Gradle) |
| `lang/c-cpp.md` | C/C++ (autoconf, make, CMake) |

Keep only the language files you need. Cascade can generate new ones
by following the patterns in the existing files.

**Last updated:** 2026-04-28
