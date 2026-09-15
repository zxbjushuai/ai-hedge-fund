# Design: Event-Driven Persona Signals

## State boundary

Each simulation owns state keyed by `(sim_run_id, ticker, persona,
model_identity, prompt_identity)`. This prevents a later run from leaking an
opinion into an earlier historical timeline. The existing content-addressed
prompt cache remains reusable across runs.

The current effective signal, source date, prompt/snapshot keys, price anchor,
processed filing/earnings facts, and retry state are persisted without API
keys, prompts, response bodies, or authentication headers.

## Refresh policy

`FundSpec.persona_refresh` defaults to a 20 percent valuation move, 90 calendar
days maximum age, and retry delays of 1, 2, 4, then 5 trading cycles. All
configured personas react to the same ticker events. Coincident reasons are
coalesced into one refresh.

The engine evaluates only information visible on the signal date. A successful
neutral response is valid state. A failed refresh reuses an unexpired state;
without one, the effective signal abstains while the failed attempt remains
auditable. Retryable failures use deterministic backoff. Non-retryable failures
wait for a different event fingerprint.

## Pipeline and transaction

`SimRunner` owns one `PersonaSignalEngine` and passes it to `run_cycle`.
`run_cycle` retains direct `model.predict` behavior when no engine is supplied.
The engine memoizes each `(ticker, persona identity)` within a cycle so duplicate
strategy staffing makes at most one decision.

`CycleRecord.persona_events` is the serialized transition source. Completed
cycle audit, ticker indexes, persona-state upserts, NAV, and fills commit in one
transaction. The signal metadata contains the effective provenance for the Web
audit view.

## Estimates

Preflight replays the cached signal-day timeline assuming successful cold-cache
refreshes. It returns unique ticker/date refresh events, unique persona count,
total estimated calls, and possibly overlapping reason counts. Runtime retries
are excluded because their occurrence is unknowable before execution.
