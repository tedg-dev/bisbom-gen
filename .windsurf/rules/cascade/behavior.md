---
description: Core Cascade AI behavior — reasoning, interaction, best practices, secrets
trigger: always_on
priority: critical
---

# Cascade Behavior

## Reasoning and Interaction

- **Explain reasoning** before making changes — break complex problems
  into steps and validate each step
- **Do not prompt** unless there is a real choice to make
- If there is an industry-standard approach, use it without asking
- Proceed autonomously on routine operations (branch names, merge strategy)
- **Record new rules**: any time a new rule or process requirement is
  introduced, persist it in `.windsurf/rules/` in the same PR

## Industry Best Practices — MANDATORY

Before making ANY business logic, design, or implementation choice,
verify the approach follows industry-standard best practices.

1. **Standards compliance** — use established specifications (SPDX 2.3,
   Bisbom, PEP, semver, PURL, etc.) not ad-hoc formats
2. **Recognized patterns** — use well-known design patterns (strategy,
   facade, factory) not novel inventions
3. **Idiomatic code** — follow language conventions (PEP 8 for Python,
   Go conventions for Go, etc.)
4. **Security** — follow OWASP/CWE guidelines; never store secrets in code
5. **Testing** — unit tests with proper isolation, no test interdependence
6. **Architecture** — separation of concerns, single responsibility,
   dependency injection, config-driven behavior
7. **Error handling** — explicit error types, no bare except, meaningful
   messages, graceful degradation
8. **Documentation** — code is self-documenting; comments explain *why*

## Before Every Decision

1. Is there an industry standard for this? → **Use it**
2. Is there a well-known library that does this? → **Use it**
3. Would a senior engineer approve this? → If not, reconsider
4. Is this the simplest correct solution? → Prefer simplicity

## Anti-Patterns to Avoid

- Inventing custom formats when standards exist
- Hardcoding values that should be configurable
- Tight coupling between components
- God objects or modules with multiple responsibilities
- Stringly-typed interfaces when enums or types exist
- Reinventing existing library functionality
- Premature optimization at the expense of clarity

## Secrets in Chat

- **NEVER** display, echo, or store secrets in Cascade chat output
- When reading files with credentials, redact sensitive values
- If a tool call returns secret content, summarize structure only
- Reference credential files by path and key name — never by value
