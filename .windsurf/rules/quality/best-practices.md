---
description: Industry standard best practices — mandatory for all code changes
---

# Industry Standard Best Practices — MANDATORY

Before making ANY code implementation, bug fix, refactoring, or design
decision, Cascade MUST verify the approach follows industry-standard
best practices. This rule takes precedence over speed, convenience, or
backward compatibility.

## Specific Mandates

1. **NEVER hide errors with silent fallbacks** — a failed lookup,
   missing data, or unexpected state must be reported loudly
   (ERROR log + skip/fail), never silently widened or defaulted to
   "use everything"
2. **NEVER widen scope on failure** — if a specific lookup fails,
   the result should be empty or an error, NEVER "fall back to all data"
3. **Fail fast, fail loud** — errors must be visible at the point they
   occur, not masked by downstream filtering or accidental correctness
4. **Data integrity over completeness** — it is better to produce no
   output than incorrect output that looks correct
5. **No silent data corruption** — any code path that could produce
   wrong-but-plausible output is a critical bug

## Before Every Implementation

1. Is the error handling explicit and visible? → If errors are swallowed
   or masked, **fix it**
2. Does failure narrow or widen the result set? → Failure must NEVER
   widen results
3. Would a security/reliability engineer approve this? → If not,
   **redesign**
4. Is the happy path distinguishable from the error path in output? →
   Must be obvious

## Anti-Patterns That Are NEVER Acceptable

- Silent fallback to broader/all data when specific lookup fails
- `[WARN]` that continues with wrong data instead of `[ERROR]` that stops
- Strace/filter accidentally masking a real bug
- "It works in production" when the logic is fundamentally wrong
- Returning default/empty values that look like valid results
