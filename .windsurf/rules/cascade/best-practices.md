---
description: All design and implementation choices MUST follow industry-standard best practices
trigger: always_on
priority: critical
---

# Industry Standard Best Practices — MANDATORY

## Rule

Before making ANY business logic, design, or implementation choice, Cascade MUST
verify the approach follows **industry-standard best practices**. This rule takes
precedence over speed, convenience, or Cascade's own preferences.

## What This Means

1. **Standards compliance** — use established specifications (SPDX 2.3, OmniBOR,
   PEP standards, semver, PURL, etc.) not ad-hoc formats
2. **Recognized patterns** — use well-known design patterns (strategy, facade,
   factory, observer) not novel inventions
3. **Idiomatic code** — follow language conventions (PEP 8 for Python, Go
   conventions for Go, etc.)
4. **Security** — follow OWASP, CWE, and NIST guidelines; never store secrets
   in code; validate all inputs
5. **Testing** — unit tests with proper isolation, mocking external dependencies,
   no test interdependence
6. **Architecture** — separation of concerns, single responsibility, dependency
   injection, config-driven behavior
7. **Data formats** — JSON Schema validation, well-defined APIs, documented
   contracts
8. **Error handling** — explicit error types, no bare except, meaningful error
   messages, graceful degradation
9. **Documentation** — code should be self-documenting; comments explain *why*,
   not *what*

## Before Every Decision

Ask yourself:

1. Is there an industry standard for this? → Use it
2. Is there a well-known library that does this? → Use it (don't reinvent)
3. Would a senior engineer at a top company approve this approach? → If not, reconsider
4. Is this the simplest correct solution? → Prefer simplicity over cleverness

## Anti-Patterns to Avoid

- Inventing custom formats when standards exist (e.g., custom SBOM format vs SPDX)
- Hardcoding values that should be configurable
- Tight coupling between components
- God objects or modules with multiple responsibilities
- Stringly-typed interfaces when enums or types exist
- Reinventing existing library functionality
- Premature optimization at the expense of clarity

## When Standards Conflict

If two standards or best practices conflict, prefer:

1. The one with broader industry adoption
2. The one specified by project rules (SPDX 2.3, OmniBOR, etc.)
3. The simpler approach
