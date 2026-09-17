# Current Handoff

## Status

- Parent change: `repair-simulation-signals-and-scale-universe`
- Current branch: `zxb_dev`
- Parent Phase 1, Signal Correctness: complete
- Workstream 1, Universe and Benchmark: complete in `da62597`
- Workstreams 2-3, LLM Platform and Cycle Audit: complete in `dd467f1`
- Parent Phase 2 / Workstream 4, Event-Driven LLM: committed and reviewed, with follow-up defects documented
- Parent Phase 3 / Workstream 5, US Security Catalog and Batch Cache UX:
  implemented in the current uncommitted worktree
- Active change: `add-security-catalog-and-batch-cache`

## Workstream 5 Planning Update: 2026-09-16

- The delivery order is security catalog and market-adapter polymorphism first,
  followed by batch cache orchestration.
- The implemented catalog/cache scope is US-only. Provider-native symbols map to
  a canonical US security identity.
- The first implementation dispatches by market (`US`, `HK`, `CN`) rather than
  exposing a general provider-routing platform. US uses Nasdaq Trader for its
  current catalog and yfinance for raw prices, financials, and earnings.
- `HK` and `CN` exist only as typed unsupported adapters with TODOs. They make no
  requests and are not exposed by the UI.
- Batch progress, cancellation, concurrency limits, backoff, failed-item retry,
  bulk upserts, and verified coverage are the second delivery step built on the
  provider contract.
- Multi-market simulation calendars, currencies, FX conversion, and portfolio
  valuation are deferred. Simulation retains its current single-benchmark rules.

### Provider contract spike

- Live probes used `AAPL`, `0700.HK`, and `600519.SS`. Yahoo returned OHLCV for
  all three markets with market-local index timezones, but provider output is not
  semantically interchangeable without normalization.
- The current Yahoo adapter omits `auto_adjust`; the installed yfinance defaults
  it to true. Historical OHLC therefore differs from raw exchange prices around
  corporate actions. A provider contract must declare adjustment mode and must
  not fill one series with bars having different adjustment semantics.
- Raw Yahoo quarterly frames existed for all three samples. The current adapter
  produced five complete AAPL metric rows but zero Tencent and Kweichow Moutai
  rows because nullable fields reach arithmetic such as annualization. Absence
  from the normalized cache can therefore mean adapter failure rather than no
  upstream data.
- Yahoo returned EPS actual/estimate/surprise rows for all three samples, but
  non-US timestamps were represented in a US timezone and the adapter discarded
  time-of-day. Announcement-date normalization needs provider and exchange
  timezone provenance.
- Live Nasdaq directory files expose symbol, name, exchange/category, ETF/test
  flags, and lot size. The live HKEX workbook exposes stock code, name, category,
  sub-category, board lot, ISIN, trading currency, and eligibility flags.
- A Tushare token is configured in the Windows user environment, but live probes
  initially lacked access. After the account reached 120 points, A-share `daily`
  succeeded repeatedly; points act as a permission threshold rather than being
  consumed per query. `stock_basic`, `fina_indicator`, and Hong Kong interfaces
  still require higher points or separate payment. No secret is stored in this
  repository. Futu OpenD is not configured.
- For `600519.SH`, 11 matched September 2026 sessions had raw Tushare and raw
  Yahoo OHLC differences below 0.00006. Multiplying Tushare volume (lots) by 100
  exactly matched Yahoo volume (shares) on every session.

### Cross-market yfinance sample

- Universe construction used current market capitalization descending, retained
  the top 1,000 securities in each market, and sampled ten evenly spaced ranks.
- A-share prices succeeded for 10/10 samples. Eight returned the full requested
  year (242 sessions); two recent listings correctly returned only post-listing
  coverage. All bars used CNY and Asia/Shanghai and had no null OHLCV, duplicate
  dates, non-positive OHLC, or negative volume.
- Hong Kong prices succeeded for 9/10 samples with 245 sessions, HKD, and
  Asia/Hong_Kong. `0638.HK` appeared in Yahoo's screener and metadata but Yahoo
  returned no prices, proving catalog presence does not guarantee price coverage.
- Raw Yahoo financial frames were materially less complete than prices. The
  current project adapter produced at least four normalized periods for 5/10
  A-share samples and 0/10 Hong Kong samples. Yahoo EPS surprise existed for
  4/10 A-share and 3/10 Hong Kong samples.
- Conclusion: the samples remain useful research for future adapters, but the
  first implemented contract is intentionally US-only. The non-US results do not
  justify exposing those markets as supported functionality.

## Review Update: 2026-09-15

- sim 8 completed with 24 successful persona refreshes and 384 reuses; event
  preflight recomputation matched. No refresh failures were observed, and max-age
  was not exercised (maximum reused age: 58 days).
- Requested end date September 14 was silently truncated to cached SPY end date
  September 8. Track requested/actual coverage in Workstream 5.
- Preserve the upstream seven-day signal-mark lookback and exact T+1 prices.
- Code TODOs record estimated filing timestamps, startup eligibility design, and
  a bootstrap failure that may change identity to universe_entry on cycle 2 and
  bypass retry policy. This last item remains an unfixed correctness defect.
- Before expanding scope, address that retry regression; the next major feature
  remains Workstream 5. Full details are in
  `../add-event-driven-persona-signals/handoff.md`.
- Workstream 4 is committed by the changeset containing this handoff; no push
  was performed as part of the implementation handoff.

> Update 2026-09-14: the original repository-baseline and gap analysis below
> is retained as historical context. The active child handoffs are authoritative
> for implemented Workstreams 1-4.

## Repository Baseline

- Fork baseline: upstream v2.0.0 commit `284a650`.
- Historical simulation and SQLite persistence were added in commit `d5fc561`.
- EPS/PEAD and quarterly prompt-cache correctness were completed in commit `0ade3e0`.
- Upstream v2.2.0 was reviewed as a design source. No upstream merge was performed.
- The current architecture intentionally retains `v2/`, `app/backend/`, and `app/frontend/`.
- Upstream v2.2.0 does not use a relational database; it saves mandates, caches, and run/backtest receipts as files under `~/.hedge-fund/`. This fork should continue using SQLite for searchable Web simulation state and audit records.

## Implemented and Stable

### Historical data and simulation

- `PriceCache`, `MetricsCache`, and `EarningsCache` persist historical inputs in SQLite.
- `SimRun`, `SimNavSnapshot`, and `SimTradeLog` persist current simulation summaries and results.
- `SimRunner` executes asynchronously in the backend process and exposes status/result APIs.
- Simulations form signals from the preceding trading day, execute using the next trading day's open, and value using that day's close.

### EPS and PEAD

- Yahoo earnings history is the only current EPS-surprise source.
- Numeric Yahoo surprise is preferred; complete actual and estimated EPS may be used to derive it.
- Incomplete EPS surprise does not fabricate a BEAT/MISS signal.
- PEAD remains neutral for the affected ticker/event while other models continue.

### Fundamental persona prompts

- Historical valuation is anchored to the filing-date close.
- The rendered quarterly fundamental snapshot remains stable between visible filings.
- Prompt-call preflight estimates count bootstrap/filing snapshots and unique personas rather than every trading day.

## Relevant Current Files

- `v2/data/earnings.py` — actionable EPS-surprise helpers.
- `v2/data/yfinance_client.py` — Yahoo price, metrics, and earnings retrieval.
- `v2/data/mock_client.py` — point-in-time reads from the SQLite historical cache.
- `v2/features/snapshot.py` — filing-visible fundamentals and filing-date valuation.
- `v2/signals/pead.py` — PEAD event selection and numeric surprise direction.
- `v2/signals/llm_agent.py` — persona calls, parsing, abstention, and prompt cache.
- `v2/llm/client.py` — current Anthropic, DeepSeek, ModelScope, and OpenRouter clients.
- `v2/fund/spec.py` — current Fund mandate including embedded universe.
- `v2/pipeline/run_cycle.py` — signal, portfolio, risk, execution, and record pipeline.
- `v2/pipeline/models.py` — serialized `CycleRecord` and strategy records.
- `v2/persistence/models.py` — market cache, ledger, and simulation ORM models.
- `v2/simulation/runner.py` — cache validation, trading-day selection, background simulation, NAV/trade persistence, and result metrics.
- `v2/simulation/test_historical_semantics.py` — no-lookahead and simulation semantic regression tests.
- `app/backend/routes/dashboard.py` — cache and simulation FastAPI endpoints.
- `app/frontend/src/components/backtest/` — cache, simulation, and result UI.

## Known Gaps

### Universe and market grid

- `FundSpec` still embeds `universe`.
- Simulation config currently mutates `spec.universe` before constructing the Fund.
- `_trading_days` requires a price row for every selected ticker, so one missing ticker can remove a market day from the entire simulation.
- There is no explicit benchmark field or benchmark NAV/excess-return curve.

### LLM configuration

- v2 provider selection is primarily environment-driven.
- Provider implementations duplicate response handling.
- The old Web UI has API-key and model infrastructure, but v2 simulation is not cleanly configured per run through it.
- Process-global provider/model environment variables are unsafe as concurrent request state.
- Reasoning/thinking response blocks are not normalized through one shared path for every provider.

### Failure semantics and audit

- Neutral, abstained, and failed outcomes are not yet expressed as a complete cross-layer contract.
- Simulation persistence stores NAV and trade rows but not the complete `CycleRecord` for each cycle.
- The Web UI cannot yet drill into a trade and reconstruct the signals, blends, risk clamps, and order that produced it.
- Data absence and infrastructure failure need consistent typed/category-based handling across Yahoo, cache, LLM, preflight, and runner boundaries.

### Event-driven execution

- Persona effective state is not persisted independently of prompt cache.
- Event tickers and non-event tickers are not explicitly distinguished.
- There is no maximum-age, universe-entry, valuation-bucket, new-filing, or earnings-event refresh scheduler.

### Scalable selection and caching

- Tickers are still manually entered.
- There is no local security catalog, saved universe, searchable multi-select, or filtered selection.
- Cache acquisition is synchronous per request and lacks a first-class batch-job model and progress UI.

## Decisions That Must Be Preserved

- Keep the React/Vite and FastAPI application.
- Keep the `v2/` package name for this roadmap.
- Do not merge upstream v2.2.0 wholesale.
- Keep SQLite as the Web simulation persistence layer.
- Keep Yahoo-only EPS surprise until a separate design change justifies another point-in-time-compatible source.
- Keep missing EPS local to PEAD.
- Keep quarterly prompt stability between defined refresh events.
- Keep T signal formation and T+1 open execution.
- Treat the benchmark as a calendar/performance input, not an implicit tradeable security.
- Store the effective universe, provider, model, and decision trail needed to reproduce a run.

## Historical Next Recommended Session (superseded by the status above)

Create and implement the OpenSpec change:

```text
openspec/changes/decouple-universe-and-add-benchmark/
```

The session should first create its own `proposal.md`, `design.md`, `tasks.md`, and `handoff.md`, using Workstream 1 in `roadmap.md` as the boundary.

Expected design questions to resolve before implementation:

1. Whether `FundSpec.universe` becomes an optional compatibility default or is removed with a loader migration.
2. Where the effective universe and benchmark are stored on `SimRun`.
3. Whether `benchmark_nav` extends `SimNavSnapshot` or uses a separate table.
4. How benchmark price caching is triggered without adding it to the tradeable universe.
5. How to distinguish not-yet-listed, ordinary missing data, temporarily untradeable, and held-but-unpriceable states in the first implementation.
6. How the benchmark-derived market grid preserves the current T/T+1 execution contract at the start and end boundaries.

Suggested new-session prompt:

```text
Create and implement the OpenSpec change
openspec/changes/decouple-universe-and-add-benchmark/.

Before editing, fully read:
- openspec/changes/repair-simulation-signals-and-scale-universe/roadmap.md
- openspec/changes/repair-simulation-signals-and-scale-universe/handoff.md
- openspec/changes/repair-simulation-signals-and-scale-universe/proposal.md
- openspec/changes/repair-simulation-signals-and-scale-universe/design.md
- openspec/changes/repair-simulation-signals-and-scale-universe/tasks.md

Only implement Workstream 1: run-time universe, benchmark, benchmark-derived
market grid, and benchmark performance. Preserve Yahoo EPS behavior, quarterly
prompt stability, and T signal / T+1 open execution. Do not implement provider
selection, event-driven LLM, audit UI, or the security catalog. Run relevant
tests, update the child tasks and handoff, and do not commit unless asked.
```

## Verification State

- The parent `tasks.md` records Phase 1 tasks 1.1 through 1.8 as completed.
- No test suite was re-run for this documentation-only handoff creation.
- A new implementation session must inspect the current worktree and run tests relevant to its own code changes.

## Handoff Update Template

Replace or extend the active child change's handoff with:

```md
## Status

completed / partial / blocked

## Implemented

- Behavior actually completed
- Corresponding task identifiers

## Changed Files

- `path` — purpose

## Decisions Made

- Decision and rationale

## Database Changes

- Tables, columns, indexes, migrations, and compatibility behavior

## Tests

- Exact command
- Result
- Tests not run and why

## Known Issues

- Remaining limitations and follow-up work

## Stable Contract for the Next Change

- Interfaces and semantics the next workstream may rely on

## Git State

- Branch
- Commit if created
- Staged, unstaged, and untracked files
```
