# Handoff

Implementation completed on 2026-09-24. No commit/push or live model calls performed.

sim10 completed 2026-09-23 21:48 Asia/Shanghai: 425 cycles, 426 NAV rows,
final NAV 84940.45525479385, benchmark NAV 131765.92465831802. Return -15.06%,
benchmark +31.77%, excess -46.83 percentage points. 64 refresh failures (63 generic
transport, 1 parse); old diagnostics cannot prove their underlying HTTP causes.
NAV balance and audit/NAV agreement checked. This is not a full strategy attribution.

## Delivery

- Per-run JSONL with UTC timestamps and severity, ticker/analyst/dates, HTTP status,
  per-attempt and overall latency, SDK retry ordinal, usage when supplied, parse outcome,
  signal summary, fallback/retry state and cycle commit boundaries. No new raw-body logs.
- Review chooses concurrency 1–8 (default 4); legacy API default remains 1. Same-day
  rolling work is bounded to 2C unfinished tasks, with an aggregate process limit of 8.
- Running tab displays concurrent tasks/stages, queue, call statistics and recent events;
  Review/Running focus and scrolling, persisted selected run ID, polling retry without
  resubmission. Restart does not resume simulations or reconstruct active calls.
- Partial results use last committed NAV; zero remains zero, unvalued metrics remain null.
  Both returns use the same curve end date; excess is shown in percentage points.
- SQLite change: one nullable `sim_run.execution_config` TEXT column. Existing migration
  adds it automatically; old runs retain null. Existing IDs and results are preserved.

## Acceptance

- `poetry run pytest hedge_fund/ research_app/backend/ -q -m 'not live'`:
  **325 passed, 39 deselected**, 71 existing dependency deprecation warnings.
- Final targeted observation suite: **28 passed**. Includes full runner comparison of
  NAV, fills, corporate actions and cycle audit at concurrency 1/4/8; mixed immediate and
  asynchronous events preserve order; process cap, strict validation, log creation/write
  failure, safe error codes, HTTP 200 truncation, timeout without status and SDK retry logs.
- Frontend: **23 tests passed**, TypeScript/Vite build passed, full ESLint zero warnings.
  Build reports an existing outdated Browserslist database advisory.
- Chrome DevTools acceptance used isolated contexts and mocked simulation POST/status
  responses. Review received focus, double confirmation submitted once with concurrency 4,
  Running received focus and displayed two concurrent ticker/analyst tasks. Desktop
  1440px and mobile 390px checks performed without adding chart dependencies.

## Operations and limitations

Restart the backend to load the new implementation, then refresh the frontend. New runs
write `<fund database directory>/logs/simulations/sim-{id}.log`; default is repository
`logs/simulations/`. Old sim10 has no retroactively fabricated request log.

HTTP attempts are exact for the three managed protocols. Uninstrumented legacy/custom
clients still report logical requests but may not expose HTTP/usage metadata. A null
status means no observed HTTP response, not an assumed success. Unknown remote error
codes/bodies are omitted for safety. Provider request IDs are logged as correlation hashes.
The concurrency cap is per backend process, not distributed across multiple workers.
No cancellation, automatic resume, log-retention deletion, future-date prefetch, or new
LLM retry policy was introduced. Existing bootstrap/filing-date TODOs remain unchanged.
Deterministic fake results match across concurrency settings; real providers may return
nondeterministic answers or impose tighter rate limits. Live acceptance remains user-run.
