# Design: stable persona bootstrap identity

## Context

`PersonaSignalEngine` fingerprints a refresh attempt from its trigger reasons,
snapshot hash, earnings date, source signal date, and valuation anchor. A
retryable failure stores that fingerprint and a future retry cycle. On the next
cycle, reusing the same fingerprint allows the engine to wait (`not_attempted`)
until the retry is due.

The current no-signal branch chooses `bootstrap` only when the global cycle is
1 and `universe_entry` otherwise. A failed cycle-1 bootstrap therefore receives
a different reason and fingerprint on cycle 2, defeating both retryable backoff
and non-retryable event suppression.

## Decision

Add `initial_refresh_reason` to the run-scoped `_PersonaState`. Set it only when
the engine first evaluates a refresh for a persona with no effective signal and
sufficient snapshot data:

- cycle 1: `bootstrap`
- a later cycle: `universe_entry`

Every later no-signal evaluation reuses the stored reason. This keeps a failed
bootstrap's fingerprint stable while preserving `universe_entry` for a security
whose data first becomes eligible after cycle 1. The insufficient-data path
does not initialize the reason because no refresh was attempted; if the
security becomes eligible later, it correctly enters as `universe_entry`.

The field is engine-local and derived, not persisted. Resume from an
interrupted process remains AIHF-019 and will need to restore or safely
re-derive this identity when that feature is implemented.

## Alternatives Considered

- **Use `pending_event_fingerprint is not None`:** this removes the immediate
  relabel but cannot distinguish a failed bootstrap from a later universe entry
  without also preserving the original reason. A dedicated field is explicit
  and testable.
- **Always use `bootstrap` when no signal exists:** this would mislabel a
  security that becomes eligible after cycle 1.
- **Persist the reason immediately:** broader schema change without a current
  resume path; defer until AIHF-019 needs durable recovery state.

## Risks

- The change alters only in-process event identity; it does not change prompt
  content, LLM calls after a successful bootstrap, or portfolio execution.
- A genuine new event still changes the fingerprint, so recovery is not blocked
  indefinitely after a terminal failure.
