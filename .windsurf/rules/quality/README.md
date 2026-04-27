# Quality Rules for Windsurf Cascade Development

Portable, industry-standard quality rules for any Windsurf-powered project.
Copy this entire `quality/` folder into `.windsurf/rules/quality/` of any
new or existing project.

## Structure

| File | Scope | Purpose |
|------|-------|---------|
| `design-principles.md` | All languages | Architecture, design patterns, anti-patterns, separation of concerns |
| `code-standards.md` | All languages | File size, formatting, naming, DRY, error handling, documentation |
| `testing-standards.md` | All languages | Test philosophy, isolation, coverage, mocking, regression |
| `security.md` | All languages | Secrets, input validation, dependency auditing, OWASP/CWE |
| `ci-workflow-standards.md` | All languages | GitHub Actions, CI/CD pipeline design, caching, concurrency |
| `pre-commit-verification.md` | All languages | Quality gates before every commit |
| `cascade-behavior.md` | Windsurf IDE | AI-specific rules for Cascade terminal, tools, reasoning |
| `golden-file-policy.md` | All languages | Regression baseline management and approval workflow |
| `lang/*.md` | Per-language | Language-specific idioms, tooling, and conventions |

## Language Files

The `lang/` subfolder contains per-language best practices:

| File | Language | Status |
|------|----------|--------|
| `lang/python.md` | Python | Complete |
| `lang/rust.md` | Rust | Complete |
| `lang/go.md` | Go | Complete |
| `lang/java.md` | Java (Maven) | Complete |
| `lang/c-cpp.md` | C/C++ (autoconf, make, CMake) | Complete |

When starting a new project, keep only the language files you need and delete
the rest. If a language file is missing for your stack, Cascade can generate
it by following the patterns in the existing files.

## How Cascade Uses These Rules

Windsurf Cascade reads all `.md` files under `.windsurf/rules/` as
always-on context. These rules:

1. **Override** Cascade's default behavior when they are more specific
2. **Stack** — all files are active simultaneously; the most restrictive rule wins
3. **Persist** across sessions — Cascade re-reads them on every conversation start

## Versioning

These rules are versioned with the project. When updating, bump the date
below so teams can track which version they have.

**Last updated:** 2026-04-27
