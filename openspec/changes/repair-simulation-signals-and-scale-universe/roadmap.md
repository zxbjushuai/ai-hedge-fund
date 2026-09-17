# Simulation Signals and Scalable Universe Roadmap

## Purpose

This document is the durable context for follow-up implementation sessions. It records the project baseline, decisions that later changes must preserve, the ordered workstreams, and the boundaries between them. New sessions should read this file before the proposal, design, tasks, and handoff for the change they are implementing.

The chat history is not a source of truth. If a later decision changes this roadmap, update this file and explain the change in the active change's `handoff.md`.

## Project Baseline

- Stage 4 completed on 2026-09-17: sim9 completed with 71 completed cycles, 72 NAV snapshots and 112 trades (read-only DB verification). User-authorized integration fast-forwarded `zxb_dev` to migration checkpoint `628f993`; `zxb_dev_bak` preserves `5fca1b4`. No remote push.
- Migration stages 1–3 use one `hedge_fund/` core and the React/Vite plus FastAPI Web UI under `research_app/`. The former `v2/` and `app/` source paths are retired; the old SQLite file locations remain unchanged.
- Integration branch: `migration/upstream-web-isolation`; stage 1 checkpoint `5b714d2`, real upstream merge `5d1c480` (parents include `fc1bf25`). Development branch now includes the migration; remote remains unchanged.
- The fork was based on upstream v2.0.0 (`284a650`). The approved migration now pins fork `5fca1b4` and upstream `fc1bf25`.
- `integrate-upstream-and-isolate-research-app` supersedes the former no-merge/no-rename restriction: isolate the Web app, then merge upstream and migrate `v2/` to `hedge_fund/` with staged acceptance.
- Preserve Web historical semantics and SQLite persistence while retaining upstream CLI/TUI separately. File removals require exact-target approval; visual redesign follows functional migration.
- SQLite and SQLAlchemy are the fork's persistence mechanism for cached market data, simulation state, NAV, trades, and future audit records.
- The Web UI remains the primary interface for configuring data acquisition and simulations.

## Completed Foundation

Phase 1 of this parent change is complete in commit `0ade3e0`:

- Yahoo earnings data preserves reported EPS, analyst-estimated EPS, and numeric surprise when available.
- Incomplete EPS surprise data makes PEAD neutral locally; it does not fabricate a directional event or stop other models.
- Historical persona valuation uses the last close on or before the filing date, keeping the quarterly fundamentals prompt stable until a new filing is visible.
- Cold-cache LLM usage estimates count filing snapshots and unique personas instead of trading days.
- Regression coverage exists for EPS fallbacks, historical valuation semantics, prompt stability, and preflight estimates.

## Invariants for All Follow-up Changes

### Historical execution

- A signal formed from information available on trading day T may not execute at a T price that was not yet available when the signal was formed.
- The current simulation contract is T signal formation, T+1 open execution, and T+1 close valuation.
- Do not copy upstream v2.2.0's same-cycle signal and reference-price fill behavior.
- All historical inputs must be point-in-time: no filing, earnings announcement, price, or universe membership may be visible before its effective timestamp.

### Fundamentals and PEAD

- Yahoo is the sole EPS-surprise source for the current simulation path.
- A PEAD event is actionable only with a numeric surprise or complete actual and contemporaneous analyst-estimate EPS inputs.
- Missing EPS inputs affect PEAD only. Other personas and quantitative models remain eligible.
- Quarterly fundamental prompts remain stable between visible filings unless the later event-driven change explicitly raises a defined refresh event.

### Fund, universe, and benchmark

- A Fund primarily defines strategies, staff, risk, capital policy, and cadence.
- The actual traded universe is an input and an audited property of each simulation/run, not hidden mutable state.
- A Fund may retain an optional default universe for compatibility, but a run-time universe takes precedence.
- A benchmark determines the market time grid and performance comparison; it is not automatically a tradeable universe member.
- Every run must record the effective universe and benchmark needed to reproduce it.

### LLM behavior

- Provider and model selection must be explicit per run. Do not switch concurrent Web requests by mutating process-global environment variables.
- Prompts and cache keys must include the effective model identity and all semantic inputs.
- `neutral`, `abstained`, and `failed` are different outcomes and must remain distinguishable in audit data.
- An LLM refresh failure must not overwrite a still-valid prior persona opinion.
- Deterministic portfolio construction, risk limits, and execution remain outside LLM control.

### Persistence and audit

- SQLite is the authoritative searchable store for Web simulations. Upstream timestamped JSON receipts may inform the serialized shape but are not the primary persistence design.
- Store compact indexed summary fields alongside a complete serialized cycle record. Normalize nested signal data later only when real cross-run queries require it.
- A simulation deletion must eventually handle its dependent audit rows consistently.
- Data-source absence, temporary transport failure, authentication failure, rate limiting, and parse failure must not collapse into the same empty-data result.

## Ordered Workstreams

### Workstream 1: Market and Simulation Time Semantics (Completed)

Suggested OpenSpec change: `decouple-universe-and-add-benchmark`

Scope:

- Pass the effective universe explicitly into `run_cycle` and record it on `CycleRecord`.
- Stop mutating `FundSpec.universe` to configure a simulation.
- Add benchmark configuration and benchmark NAV/excess-return results.
- Build the simulation time grid from benchmark market days rather than the intersection of all selected tickers.
- Define behavior for unlisted, missing, temporarily untradeable, and held-but-unpriceable securities.
- Preserve T/T+1 signal, execution, and valuation semantics.

Acceptance boundary:

- One missing ticker bar does not remove a market day for every other ticker.
- The benchmark is never analyzed or traded unless explicitly included in the universe.
- The result contains a reproducible universe, benchmark, benchmark curve, and excess return.

Non-goals:

- Provider selection, event-driven persona refresh, the security catalog, and a detailed audit UI.

### Workstream 2: LLM Provider Platform (Completed)

Suggested OpenSpec change: `unify-v2-llm-providers`

Scope:

- Replace provider-specific selection branches with a model/provider registry and `make_llm` factory.
- Preserve existing Anthropic, DeepSeek, ModelScope, and OpenRouter support while adopting upstream's extensible provider structure where useful.
- Normalize plain text, content blocks, and reasoning/thinking response blocks before JSON parsing.
- Add backend APIs that expose supported providers/models and accept an explicit provider/model for simulation preflight and execution.
- Connect v2 simulation to the existing Web API-key/settings experience without using global environment mutation as request state.
- Record the selected provider and model on each simulation.

Acceptance boundary:

- Two runs configured with different models cannot overwrite each other's selection.
- Missing credentials fail preflight with an actionable provider-specific error.
- Reasoning blocks cannot corrupt the final signal JSON.

Optional follow-up, not required for the first implementation: token streaming over SSE.

### Workstream 3: Failure Semantics and Cycle Audit (Completed)

Suggested OpenSpec change: `persist-simulation-cycle-audit`

Scope:

- Establish typed/category-based data and LLM failure semantics.
- Preserve the distinction between a successful neutral view, an abstention, and a failed attempt.
- Add a `SimCycleRecord`-style table with indexed run/date fields and the full serialized `CycleRecord` payload.
- Record signal date, execution date, effective universe, strategy signals, target/final weights, clamps, orders, fills, positions, cash, and NAV.
- Add query APIs for simulation, date, and ticker drill-down.
- Add a minimal Web view that can answer why a trade occurred.

Acceptance boundary:

- A data-provider outage cannot silently become a neutral signal.
- An audit query can reconstruct the inputs and transformations behind a trade.
- Existing NAV and trade result APIs remain compatible or receive an explicit migration path.

Non-goal: fully normalizing every nested signal into relational tables.

### Workstream 4: Event-Driven Persona Signals (Implemented; reviewed with follow-ups)

Suggested OpenSpec change: `add-event-driven-persona-signals`

This is the original Phase 2 of the parent change, implemented after the universe, provider, and audit contracts are stable.

Scope:

- Persist the latest effective persona state keyed by ticker and persona/model identity.
- Bootstrap eligible universe members at simulation start.
- Detect new-filing, actionable-earnings, valuation-bucket, universe-entry, and maximum-age events.
- Refresh event tickers only and reuse still-valid opinions for non-event tickers.
- Preserve a valid prior opinion when a refresh fails; abstain only if no valid state exists.
- Materialize a complete point-in-time signal set before the existing portfolio construction stage.
- Audit whether each opinion was refreshed, reused, expired, or unavailable.
- Estimate LLM calls from the actual event schedule.

Acceptance boundary:

- If only AAPL has an event on a date, only AAPL's affected personas make new calls.
- Non-event tickers still participate in the same portfolio construction using their valid prior state.
- Replaying the same point-in-time inputs produces the same event schedule.

Review outcome (2026-09-15): sim 8 verified 24 successful refreshes and 384
reuses across 68 cycles; recomputed preflight matched all 8 ticker/date events.
The implementation was completed after baseline `dd467f1`; see the child handoff
for validation evidence and the bootstrap-failure-to-universe-entry retry defect.

Follow-up priorities:

1. Fix initial-attempt identity so bootstrap failure cannot bypass backoff when
   the next cycle is mislabeled universe entry; add the missing regression case.
2. Define startup eligibility for partial-history/newly listed companies.
3. Replace estimated quarterly +45-day filing visibility with sourced timestamps;
   keep runtime detection and preflight estimation consistent.
4. Expose requested versus actual cache coverage in Workstream 5. Benchmark data
   gaps must not be presented as verified holidays or full-range completion.

Retained decision: keep the upstream seven-day signal-mark lookback. It does
not change exact T+1 open execution or close valuation. Any future removal must
review scheduler and CLI callers as well as simulation; no such removal is planned.

### Workstream 5: Security Catalog and Batch Cache UX

Suggested OpenSpec change: `add-security-catalog-and-batch-cache`

This is the original Phase 3 of the parent change. It depends on the run-time universe contract from Workstream 1 but does not strictly depend on event-driven personas.

Scope:

- Add a local searchable US security catalog and a market-level adapter contract.
- Implement US symbol mapping and data acquisition. Keep Hong Kong and mainland
  China as typed TODO adapters until reliable catalog, currency, and calendar
  contracts are designed.
- Provide filtered, paginated search and saved universes.
- Replace manual ticker text entry with multi-select, select-page, and select-filtered interactions.
- Add cached-coverage indicators and data-quality warnings.
- Add bounded in-memory cache jobs with progress, cancellation, backoff, and failed-ticker retry.
- Batch prices, limit fundamentals/earnings concurrency, and bulk-upsert cache rows.
- Skip already complete coverage idempotently.

Acceptance boundary:

- Users can select tens or hundreds of securities without memorizing ticker symbols.
- One failed ticker does not fail the whole batch.
- The UI exposes completed, partial, failed, and retryable outcomes.

Non-goal: process-restart recovery for cache jobs in the current single-machine simulation scope.

Implementation order (decision recorded 2026-09-16):

1. Build the US security catalog, canonical identity, Yahoo symbol mapping, and
   market-data adapter. Use raw Yahoo OHLCV plus adjusted close, dividends, and
   splits. Keep `HK` and `CN` adapters explicitly unsupported with follow-up TODOs.
2. Build bounded batch cache jobs on those interfaces, including progress,
   cancellation, concurrency limits, backoff, failed-item retry, bulk upserts,
   and requested-versus-actual coverage reporting.

Rationale: retry and batching policy must operate on a stable market adapter and
typed failures rather than being embedded in the current Yahoo-specific route.
Cross-market catalogs, portfolio calendars, currencies, FX conversion, and
multi-benchmark valuation remain outside this workstream.

## Dependency Graph

```text
Completed signal-correctness foundation
                  |
                  v
Workstream 1: universe + benchmark + market grid
          |                    |
          v                    +----------------------+
Workstream 2: provider platform                       |
          |                                           v
          v                              Workstream 5: catalog + batch cache
Workstream 3: failure semantics + audit
          |
          v
Workstream 4: event-driven persona state
```

Workstreams 2 and 5 may be developed in parallel after Workstream 1, but the default sequence above minimizes contract churn.

## New-Session Protocol

For every implementation session:

1. Read this roadmap completely.
2. Read the active change's `proposal.md`, `design.md`, `tasks.md`, and `handoff.md` completely.
3. Inspect the current Git state and relevant code; do not assume the previous session committed or left a clean worktree.
4. Implement only the active change. Record newly discovered follow-up work instead of expanding scope silently.
5. Run tests proportional to the risk, including historical/no-lookahead tests for simulation changes.
6. Update task checkboxes only for work actually completed.
7. Update the active `handoff.md` with changes, decisions, database migrations, commands/results, known issues, and the next stable contract.
8. Do not commit unless the user asks.

Suggested prompt:

```text
Implement the OpenSpec change at <change-directory>.

Before editing, fully read:
- openspec/changes/repair-simulation-signals-and-scale-universe/roadmap.md
- <change-directory>/proposal.md
- <change-directory>/design.md
- <change-directory>/tasks.md
- <change-directory>/handoff.md

Stay within this change's scope. Preserve the roadmap invariants, especially
point-in-time data, quarterly prompt stability, and T signal / T+1 open
execution. Run relevant tests, update tasks.md and handoff.md, and do not
commit unless explicitly asked.
```

## Scope Control

- A workstream should be split again if its implementation cannot be reviewed and tested coherently in one session.
- Prefer compatibility shims and explicit migrations over unrelated cleanup.
- Do not combine directory restructuring, TUI adoption, packaging, or an upstream merge with any workstream.
- Changes to an invariant require an explicit design update, regression tests, and a note in the handoff.
