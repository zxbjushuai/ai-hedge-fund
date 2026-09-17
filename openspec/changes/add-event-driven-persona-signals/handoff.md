# Current Handoff

## Status

Completed and reviewed in the development-branch commit that contains this
handoff, with the explicit follow-up defects below.

## Baseline

- Branch: `zxb_dev`.
- Baseline commit: `dd467f1`.
- Workstreams 1-3 are complete: explicit universe/benchmark, immutable LLM
  connections, typed failures, and cycle decision audit.

## Decisions

- Persona state is isolated per simulation; prompt-cache reuse remains global
  and content addressed.
- Default refresh thresholds are 20 percent valuation movement and 90 calendar
  days, configured through backward-compatible Fund YAML.
- All configured personas respond to all supported ticker events.
- Retryable refresh failures use 1/2/4/5-cycle backoff; non-retryable failures
  wait for a new event.

## Completion Notes

## Implemented

- Added backward-compatible Fund YAML refresh policy with 20 percent / 90 day
  defaults and deterministic retry delays.
- Added `PersonaSignalEngine` with bootstrap, universe-entry, filing, actionable
  Yahoo earnings, valuation, maximum-age, retry, reuse, expiry, and unavailable
  semantics.
- Added event-aware prompt context while preserving direct `LLMAgent.predict`
  and content-addressed prompt caching.
- Added `CycleRecord.persona_events`, signal provenance metadata, event-schedule
  preflight estimates, result policy snapshots, and Decision Audit rendering.
- Added run-scoped `sim_persona_state`; its updates commit atomically with cycle
  audit, NAV, and fills.
- Changed SQLite-backed simulation reads to propagate infrastructure failures
  instead of translating them into ordinary missing data.

## Database Changes

- New `sim_persona_state` table, uniquely keyed by run, ticker, persona, model
  identity, and prompt identity.
- New nullable `sim_run.persona_refresh_policy` JSON column.
- New non-null `sim_cycle_ticker_index.refresh_failed_count` summary column.
- Startup migration is additive; historical runs and cycle payloads need no
  backfill and return null/empty policy-event data.

## Validation

- Commit-readiness recheck on 2026-09-15: the full backend command below passed
  again (219 passed, 38 deselected, 288 warnings; 32.68 seconds), and
  `git diff --check` passed. Review edits only added comments/documentation;
  frontend results below are the prior implementation validation, not rerun here.
- `poetry run pytest v2/ app/backend/services/test_llm_provider_service.py -q`
  - 219 passed, 38 live tests deselected, 288 dependency warnings.
- Focused Workstream 4 suite
  - 12 event/state tests passed, including thresholds, retries, chronology,
    coalescing, fail-loud reads, and atomic persistence.
- `npm.cmd run build`
  - passed with existing font, sourcemap, Browserslist, and bundle warnings.
- ESLint on the four changed frontend files
  - passed with zero warnings.
- Repository-wide `npm run lint`
  - remains blocked by 248 pre-existing problems outside changed files.
- Python compileall and `git diff --check`
  - passed, apart from repository LF-to-CRLF notices.

## Known Limits

### Review on 2026-09-15

- Keep the upstream seven-calendar-day signal-price lookback. It is independent
  of the benchmark session grid and can support an unheld ticker with a missing
  signal-day bar. Orders still require the exact execution-day open, and held
  positions require the exact execution-day close. Do not replace either with
  the stale signal mark. Upstream introduced the lookback in `2a45575`.
- Known retry defect (TODO in `persona_state.py`): if cycle-1 bootstrap fails,
  cycle 2 may relabel the same initial attempt as `universe_entry`, changing the
  fingerprint and bypassing backoff or non-retryable suppression. The passing
  retry tests do not establish correctness of this particular transition.
  Fix and regression-test this before claiming complete retry conformance.
- Filing timestamps in the Yahoo metrics cache are `report_period + 45 days`
  (`estimated_45d`), not verified publication timestamps. `new_filing` currently
  reflects visibility under this approximation. TODOs at cache ingestion,
  runtime detection, and preflight estimation defer source-aware timing work.
  Removing the event alone would not correct the underlying visibility dates.
- Startup eligibility needs a follow-up design (TODO in `persona_state.py`):
  four visible quarterly metric rows are currently required for LLM analysts.
  Newly listed/partial-history securities abstain until eligible; independent
  quant models may still trade. Consider published pre-IPO history and explicit
  confidence/data requirements rather than silently lowering the threshold.
- The benchmark cache is the session grid, not an independent exchange calendar.
  Missing benchmark bars can hide real sessions or truncate the requested range
  without a warning. Frontend date inputs are not constrained by cache coverage.
  Address coverage visibility in Workstream 5; calendar validation needs an
  explicit follow-up scope before changing scheduler/CLI behavior.
- Yahoo earnings dates and EPS are research inputs, not guaranteed historical
  data vintages. Nonzero numeric surprise triggers an event; zero/missing surprise
  does not. Date granularity loses intraday announcement timing.

## Real Simulation Acceptance: sim 8

- Reviewed on 2026-09-15. Requested AAPL/MSFT, SPY benchmark, 2026-06-01 through
  2026-09-14. Completed 68 decision cycles and 69 NAV dates, actually ending
  2026-09-08 because all three price caches ended there; recorded warnings were empty.
- 408 persona results: 24 successful refreshes (`cached=false`) and 384 reuses.
  No recorded refresh failures or pending retries. Recomputed preflight matched:
  8 ticker/date refresh events x 3 personas = 24 calls.
- Refresh timeline: both tickers bootstrap on June 1; MSFT valuation change on
  June 22 (-20.23%); MSFT earnings July 29; AAPL earnings July 30; MSFT valuation
  change August 3 (+24.87%); both tickers' estimated filing visibility August 14.
- AAPL and MSFT each cover all 69 cached SPY dates. Reused values/source dates,
  current signal dates, price thresholds, and cached filing/earnings visibility
  passed inspection. All NAV rows satisfy cash + equity = NAV.
- Maximum observed reused opinion age was 58 calendar days. This run does not
  validate max-age expiry, refresh failures, retry backoff, or IPO entry behavior;
  those require controlled tests. It also does not verify Yahoo data against
  authoritative source publications.

- State is deliberately not reused across simulations; identical prompts can
  still reuse the existing prompt cache.
- Event estimates assume successful refreshes and do not predict runtime retries.
- The daily cache records earnings at date granularity; with T-close signal
  formation, an event dated T may affect T's signal but never an earlier cycle.
- The Web UI displays the Fund policy but does not edit it; policy changes are
  made in Fund YAML.

## Stable Contract for Workstream 5

- Runtime universe remains a per-run input and a ticker can enter persona
  eligibility after prices and four visible metric periods become available.
- Cache jobs may add point-in-time prices, filings, and Yahoo earnings without
  scheduling LLM work themselves; the simulation derives events deterministically.
- Missing ticker data stays local, while cache/database infrastructure failures
  must remain distinguishable and fail loud.

## Git State

- Branch: `zxb_dev`.
- Baseline: `dd467f1`.
- Workstream 4 is committed by the same changeset that contains this handoff.
