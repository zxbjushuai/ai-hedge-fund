# Current Handoff

## Status

completed

## Scope

Workstream 3 only: typed failure semantics, complete per-cycle audit
persistence, query APIs, and a minimal Decision Audit Web view.

## Stable Inputs

- Workstream 1 established explicit universe, benchmark market grid, and T/T+1 execution.
- Workstream 2 established immutable run-scoped provider/model connections.
- Prompt cache identity includes provider and model and remains the location for raw prompts/responses.
- Existing NAV, trade, status, and result APIs must remain compatible.

## Decisions

- Successful zero-valued signals are `produced`, not abstentions.
- Missing point-in-time inputs are `abstained`; attempted provider/parse failures are `failed`.
- Completed cycle audit, NAV, and fills form one atomic database write.
- Removed the obsolete separate `_save_trades()` path; completed cycles persist
  typed `CycleRecord.fills` only through the atomic audit transaction.
- Full cycle JSON is authoritative; a compact ticker table exists only for filtering and summaries.
- The initial NAV point is not a decision cycle.
- Historical runs without audit rows remain readable and report audit as unavailable.
- Audit payloads link to prompt cache keys and never duplicate credentials or raw remote responses.

## Implemented

- Added typed `Signal.status` values (`produced`, `abstained`, `failed`) and
  categorized, retry-aware `FailureDetail` data.
- Kept a successful zero-conviction signal as a produced neutral view.
  Insufficient point-in-time fundamentals now abstain, while LLM auth,
  rate-limit, timeout, transport, and parse errors produce failed signals.
- Kept data-client infrastructure exceptions fail-loud and categorized their
  failed cycle audit without persisting provider response bodies or secrets.
- Added `execution_date`, exact T+1 execution prices, and exact T+1 valuation
  closes to the complete `CycleRecord`; T signal marks remain separate.
- Added `sim_cycle_record` for completed and failed attempts and
  `sim_cycle_ticker_index` for run/date/ticker drill-down and signal outcome
  counts. Existing databases gain the tables through startup `create_all`.
- Persisted each completed cycle, ticker indexes, NAV, and fills in one SQLite
  transaction. A uniqueness failure test verifies that NAV/trades cannot be
  partially duplicated.
- Added list/detail APIs with simulation ownership checks, exact signal or
  execution date filters, combined date filtering, ticker filtering, and
  bounded pagination.
- Added `audit_available` to simulation results. Historical runs without cycle
  rows return false and retain their existing NAV/trade behavior.
- Added the Web Decision Audit view with cycle selection and date/ticker
  filters. It shows signal outcome/reasoning, T/T+1 prices, target/final
  weights, clamps, skips, orders, fills, positions, cash, and NAV.

## Database Changes

- New table `sim_cycle_record` has unique `(sim_run_id, cycle_number)`, indexed
  run/signal/execution fields, universe and full-cycle JSON, safe error fields,
  cash, and NAV.
- New table `sim_cycle_ticker_index` has unique cycle/ticker rows, indexed run
  and ticker fields, outcome counts, weights, and order/fill counts.
- No existing column was renamed or removed. Old runs require no backfill.

## Public API

- `GET /dashboard/sim/{sim_id}/cycles` accepts optional `date`, `signal_date`,
  `execution_date`, `ticker`, `limit`, and `offset` parameters.
- `GET /dashboard/sim/{sim_id}/cycles/{cycle_id}` returns the indexed summary
  and full serialized record after ownership validation.
- Existing result responses add `audit_available`; all existing NAV and trade
  fields remain unchanged.

## Validation

- `poetry run pytest v2/ app/backend/services/test_llm_provider_service.py -q`
  - 190 passed, 38 live tests deselected by project configuration after the
    adjacent OpenCode Go compatibility fix.
- Focused signal, construction, pipeline, historical semantics, persistence,
  and dashboard route tests passed.
- `npm.cmd run build` from `app/frontend`
  - passed; existing font, sourcemap, Browserslist, and bundle-size warnings remain.
- ESLint on the three changed frontend files
  - passed with zero warnings.
- Python compileall and `git diff --check`
  - passed; Git reports only the repository's LF-to-CRLF notices.

## Known Limits

- Nested strategy signals remain serialized JSON by design; only ticker-level
  summaries are relationally indexed.
- The Web view loads up to 100 cycle summaries at once. The API supports
  pagination for future long-run navigation controls.
- Failed LLM views are excluded from blending, but the current daily pipeline
  has no reusable prior persona state. Preserving a prior valid opinion is
  intentionally Workstream 4.

## Git State

- Branch: `zxb_dev`.
- Workstream 2 commit: `5becce1`.
- Workstream 3 and the final provider-platform follow-ups were committed as
  `dd467f1`.

## Stable Contract for Workstream 4

- Every produced, abstained, and failed persona attempt is distinguishable in
  the persisted cycle record.
- Prompt keys and snapshot hashes remain available for linking an opinion to
  the existing exact prompt cache.
- Workstream 4 may introduce persisted persona state and refreshed/reused/
  expired provenance without changing the cycle audit table shape.
- It must keep T signal / T+1 open / T+1 close and reuse a prior valid opinion
  when an event refresh fails.
