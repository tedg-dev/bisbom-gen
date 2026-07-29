---
description: Architecture, design patterns, and anti-patterns for all code
trigger: always_on
priority: critical
---

# Design Principles

Before making ANY business logic, design, or implementation choice, Cascade
MUST verify the approach follows industry-standard best practices. This rule
takes precedence over speed, convenience, or Cascade's own preferences.

## Core Principles

### 1. Standards Compliance

- Use established specifications — never invent ad-hoc formats when standards
  exist (SPDX, Bisbom, OpenAPI, JSON Schema, semver, PURL, CPE, etc.)
- When a standard covers your use case, adopt it fully — do not cherry-pick
  fields or invent extensions without documenting why

### 2. Separation of Concerns

- **Single Responsibility**: every module, class, and function should have
  exactly one reason to change
- **Layered architecture**: presentation → business logic → data access.
  No layer should skip levels
- **Config-driven behavior**: feature flags, thresholds, and environment
  differences belong in configuration, not in code branches

### 3. Recognized Design Patterns

Use well-known patterns when they fit. Do not invent novel abstractions:

| Pattern | When to use |
|---------|-------------|
| **Facade** | Orchestrating multi-step pipelines (e.g., build → analyze → report) |
| **Strategy** | Selecting behavior at runtime by config (e.g., language-specific builders) |
| **Factory** | Constructing objects whose concrete type depends on input |
| **Observer** | Decoupling event producers from consumers |
| **Dependency Injection** | Making components testable by injecting collaborators |

### 4. Simplicity Over Cleverness

- Prefer the simplest correct solution
- Avoid premature optimization — measure first, optimize second
- Code should be readable by a mid-level engineer without comments explaining
  *what* it does (comments explain *why*)

### 5. DRY — Don't Repeat Yourself

- If logic appears in more than one place, extract it into a shared function
  or module
- Common utilities (config loading, timestamp formatting, path helpers) must
  live in a single canonical location
- Language-specific pipeline steps that share structure should use a common
  base or template, not copy-paste with minor variations

## Anti-Patterns to Avoid

| Anti-pattern | Correct alternative |
|--------------|---------------------|
| God object / god module (>400 lines) | Decompose into focused modules |
| Hardcoded values | Configuration file or environment variables |
| Tight coupling between components | Dependency injection, interfaces |
| Stringly-typed interfaces | Enums, dataclasses, typed dicts |
| Custom formats when standards exist | Use the standard (SPDX, PURL, etc.) |
| Reinventing library functionality | Use well-known libraries |
| Premature optimization | Profile first, optimize the bottleneck |
| Feature flags in code branches | Config-driven strategy pattern |
| Repo-specific logic (`if name == "curl"`) | Generic, config-driven behavior |

## File Size Guidelines

- **Target**: ≤400 lines per module (excluding blank lines and comments)
- **Hard flag**: any module >400 lines must be flagged for refactoring
- **Refactoring patterns**: extract classes, split templates from logic,
  separate constants, decompose by concern
- **When to refactor**: complete current task first, then refactor on a
  dedicated branch — never mid-feature

## Before Every Decision

1. Is there an industry standard for this? → **Use it**
2. Is there a well-known library that does this? → **Use it** (don't reinvent)
3. Would a senior engineer at a top company approve this? → If not, reconsider
4. Is this the simplest correct solution? → Prefer simplicity

## When Standards Conflict

If two standards or best practices conflict, prefer:

1. The one with broader industry adoption
2. The one specified by project-specific rules
3. The simpler approach
