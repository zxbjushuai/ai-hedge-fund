# Fix persona bootstrap retry identity

## Why

AIHF-012 records a simulation-correctness defect in the event-driven persona
engine. When the first LLM refresh fails, the persona has no effective signal.
The next cycle currently relabels the same pending attempt as `universe_entry`,
which changes the event fingerprint and can bypass deterministic retry backoff
or non-retryable failure suppression.

## What Changes

- Remember the reason that initiated each persona's initial refresh attempt.
- Reuse `bootstrap` for a failed cycle-1 bootstrap until it succeeds or a new
  event genuinely changes the fingerprint.
- Preserve `universe_entry` when a persona is first evaluated after cycle 1,
  including a security that was previously ineligible.
- Add deterministic regression tests for retryable backoff, non-retryable
  suppression, and genuine later universe entry.

## Impact

- Runtime state: one in-memory field on run-scoped persona state.
- API, database schema, frontend, and historical execution semantics are
  unchanged.
- Backlog item: AIHF-012.
