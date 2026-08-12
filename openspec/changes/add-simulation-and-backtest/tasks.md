## 1. Log Persistence

- [x] 1.1 Add console and persistent application logging to the daemon
- [x] 1.2 Partition backend logs into `logs/YYYY-MM-DD/backend.log` and switch automatically at local midnight
- [x] 1.3 Preserve frontend and backend startup output in the daily directory from both full-app launchers

## 2. Enhanced YFinanceClient (Historical Financials)

- [x] 2.1 Add helper functions (`_fmt_date`, `_safe_float`, `_val_at`, `_match_column`, `_growth`, `_ratio`) to `v2/data/yfinance_client.py`
- [x] 2.2 Rewrite `get_financial_metrics()` to query quarterly statements and compute derived metrics
- [x] 2.3 Add `_fallback_metrics()` and inclusive historical price ranges

## 3. Cache Database Tables

- [x] 3.1 Add unique daily `PriceCache`
- [x] 3.2 Add unique quarterly `MetricsCache` with filing-date provenance
- [x] 3.3 Add `EarningsCache`, `SimRun`, `SimTradeLog`, and `SimNavSnapshot`
- [x] 3.4 Add path-isolated engines plus additive existing-DB migration

## 4. Cache CRUD API

- [x] 4.1 Implement validated cache fetch with per-ticker price/metrics/earnings upserts
- [x] 4.2 Implement cache list with all three data summaries and quality note
- [x] 4.3 Implement per-ticker deletion for all cache tables

## 5. MockDataClient

- [x] 5.1 Create protocol-compatible `MockDataClient`
- [x] 5.2 Implement cached inclusive price queries
- [x] 5.3 Implement point-in-time metric reconstruction including cached ticker identity
- [x] 5.4 Implement basic cached company metadata
- [x] 5.5 Implement cached earnings history for PEAD and explicit unsupported-data stubs

## 6. Simulation Engine

- [x] 6.1 Create simulation package and runner
- [x] 6.2 Implement complete-universe cached trading calendar
- [x] 6.3 Implement `SimRunner` class with `create()`, `start()`, and `_get()` static methods
- [x] 6.4 Implement one-fund, in-memory-broker run loop with prior-close signals, next-open fills, close NAV, and fail-fast status
- [x] 6.5 Implement `get_sim_status()` including progress and failure metadata
- [x] 6.6 Implement `get_sim_result()` with NAV, isolated trades, return, drawdown, and daily Sharpe
- [x] 6.7 Implement `list_sim_runs()` with summary and failure metadata

## 7. Broker Changes

- [x] 7.1 Track fill events in both simulation and persistent brokers
- [x] 7.2 Add protocol-compatible optional `cycle_date` to brokers
- [x] 7.3 Add optional `cycle_date` to persistent NAV snapshots
- [x] 7.4 Support separate signal, execution, and valuation prices in `run_cycle()`
- [x] 7.5 Persist daemon NAV using the actual cycle date

## 8. Simulation API Routes

- [x] 8.1 Implement validated `POST /dashboard/sim/run` with LLM and cost preflight
- [x] 8.2 Implement `GET /dashboard/sim/status/{sim_id}` route
- [x] 8.3 Implement `GET /dashboard/sim/result/{sim_id}` route
- [x] 8.4 Implement `GET /dashboard/sim/runs` route
- [x] 8.5 Set `FUND_SPEC_PATH` in daemon startup

## 9. React Frontend — Simulation API Service

- [x] 9.1 Create typed simulation API service with structured HTTP errors

## 10. React Frontend — Cache Panel

- [x] 10.1 Create cache panel including prices, metrics, earnings, and quality warnings

## 11. React Frontend — Simulation Panel

- [x] 11.1 Create simulation form, LLM cost confirmation, progress polling, failures, and past runs
- [x] 11.2 Create result metrics, NAV SVG, model/warning display, and trade table

## 12. React Frontend — Tab Integration

- [x] 12.1 Create Backtest container with Cache / Simulation navigation
- [x] 12.2 Add persistent singleton `backtest` tab type
- [x] 12.3 Add Backtest creation/restoration to `TabService`
- [x] 12.4 Add Backtest tab icon
- [x] 12.5 Add toolbar Backtest action
- [x] 12.6 Wire Backtest action into Layout

## 13. Verification

- [x] 13.1 Verify dashboard route registration and `/dashboard/status` responds through TestClient
- [x] 13.2 Run the frontend production build and verify Backtest tab integration compiles
- [x] 13.3 Smoke-test real Yahoo AAPL prices/metrics/earnings and verify cache fetch/list with an isolated API integration test
- [x] 13.4 Run deterministic cached-data integration test and verify next-open trades, close NAV, status, and live-ledger isolation

## 14. Simulation Usability and Low-Cost Provider

- [x] 14.1 Add an always-visible simulation preflight and require explicit confirmation for every run
- [x] 14.2 Add OpenAI-compatible ModelScope support with environment-only credentials and a lightweight default model
- [x] 14.3 Cache historical shares and reconstruct point-in-time market cap, P/B, and P/E
- [x] 14.4 Disable unavailable PEAD inputs with a warning and add a deterministic 20-day price-momentum baseline
- [x] 14.5 Show preflight estimates and warnings in the frontend before execution

## 15. OpenRouter Free Inference

- [x] 15.1 Add an OpenAI-compatible OpenRouter provider using environment-only credentials
- [x] 15.2 Configure `openrouter/free` as the default simulation model router
- [x] 15.3 Cover OpenRouter endpoint, model selection, and completion behavior with a provider test

## 16. Review Documentation and NAV Chart Readability

- [x] 16.1 Document database-path isolation and every column in the six new cache/simulation tables
- [x] 16.2 Document ticker-universe semantics and distinguish v2 personas from the legacy v1 agent list
- [x] 16.3 Add dated x-axis ticks and dollar-valued y-axis ticks to the NAV chart
- [x] 16.4 Correct the API-call upper bound for daily point-in-time valuation prompts
