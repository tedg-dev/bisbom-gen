# Dead Code Policy

Dead code (functions, classes, constants, imports with no production
callers) MUST be removed immediately upon discovery. Never leave dead
code "for future use" or "in case it's needed later."

## Rules

- **ALWAYS** verify whether code is actually called by production code
  before assuming it's needed — use `grep_search` across `app/`
- **ALWAYS** remove dead code in the same PR where it's discovered
- **NEVER** write functions/constants that have no production caller —
  if tests are the only consumer, the code is dead
- **NEVER** leave "utility" functions that no production code imports
- **NEVER** guess whether code is used — verify with tools
- **NEVER** keep code around "just in case" — version control exists
  for recovery
- When removing a feature or refactoring, trace ALL callers and remove
  the entire dead chain
- Tests for removed code must also be removed — tests for dead code
  are themselves dead

## Verification Method

Before declaring any function/constant/class as "needed":

1. `grep_search` for all imports and usages across `app/` (production)
2. If only found in `tests/` and its own definition → **dead code**
3. If found in production code → keep it

## Why

- Dead code misleads future developers (and AI) into thinking it's used
- Dead code accumulates and becomes a maintenance burden
- Dead code can mask design problems (e.g. heuristics that were never
  correct but persisted because they had tests)
