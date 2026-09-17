## Why

The AI Hedge Fund currently has no way to backtest strategies against historical data or verify performance before live trading. Analysts want to test fund configurations over multi-month periods with realistic price movements, but run_cycle() only works with live API data sources. Additionally, there is no log persistence for debugging production issues.

## What Changes

- **Date-partitioned logs**: Daemon, API, scheduler, and simulation logs (INFO+) write to `logs/YYYY-MM-DD/backend.log` alongside console output. Full-app launchers also persist frontend and raw backend startup output in the same daily directory.
- **Historical financial data**: Enhance `YFinanceClient.get_financial_metrics()` to extract quarterly metrics from yfinance DataFrames (income statement, balance sheet, cash flow) rather than returning only a current snapshot. This enables point-in-time fundamentals for backtesting.
- **Data cache layer**: SQLite tables `price_cache`, `metrics_cache`, and `earnings_cache` store historical prices, conservative point-in-time fundamentals, and EPS announcements for PEAD.
- **Mock data client**: `MockDataClient` implements the `DataClient` protocol reading from the local cache tables with point-in-time filtering (`filing_date <= as_of`), enabling the full run_cycle() pipeline to operate without live API calls.
- **Simulation engine**: `SimRunner` runs one persistent in-memory fund/broker over complete cached trading days. Signals use the prior close, orders fill at the next open, and close NAV/trades are recorded only in `sim_*` tables.
- **Simulation API**: Endpoints to start a simulation (`POST /dashboard/sim/run`), poll status (`GET /dashboard/sim/status/{id}`), retrieve results with NAV curve and performance metrics (`GET /dashboard/sim/result/{id}`), and list past runs (`GET /dashboard/sim/runs`).
- **Always-visible LLM preflight**: A dedicated preflight endpoint always reports the cold-cache upper-bound call count, provider, model, trading days, enabled models, and data warnings before a run can be confirmed.
- **Low-cost ModelScope provider**: OpenAI-compatible ModelScope inference is supported through `MODELSCOPE_API_KEY`, defaulting to `Qwen/Qwen3-4B` for simulation tests.
- **Free OpenRouter provider**: OpenRouter is supported through `OPENROUTER_API_KEY`, using the OpenAI-compatible endpoint and `openrouter/free` routing by default.
- **Actionable historical baseline**: Historical valuation ratios are reconstructed from point-in-time prices and filings, and a deterministic 20-day price-momentum sleeve provides a no-API baseline when fundamental agents abstain. PEAD is disabled with a warning when cached EPS surprise data is unavailable.
- **React frontend panel**: New Backtest tab in the existing VSCode-style IDE with two sub-pages: Data Cache (fetch/manage historical data) and Run Simulation (configure and run simulations, view results with SVG NAV chart, metrics cards, and trade log table).

## Capabilities

### New Capabilities
- `data-cache`: Crawl, store, list, and delete historical OHLCV price data and quarterly financial metrics via yfinance.
- `simulation-engine`: Backtest a fund configuration day-by-day against cached historical data, producing NAV curves, trade logs, and performance metrics (total return, max drawdown, Sharpe ratio).
- `simulation-ui`: React frontend panels for triggering data caching, running simulations, and visualizing results.

### Modified Capabilities
- *(none — all existing capabilities are unchanged)*

## Impact

- **`v2/data/yfinance_client.py`**: `get_financial_metrics()` rewritten to use quarterly statements; new helper functions added.
- **`v2/persistence/models.py`**: Six new ORM tables (`PriceCache`, `MetricsCache`, `EarningsCache`, `SimRun`, `SimTradeLog`, `SimNavSnapshot`).
- **`v2/data/mock_client.py`** (new): Protocol-compliant data client backed by cache tables.
- **`v2/simulation/runner.py`** (new): Backtest engine with `SimRunner`, status/result query functions.
- **`v2/brokers/persistent.py`**: `place_order()` and `save_nav_snapshot()` accept optional `cycle_date` parameter.
- **`v2/pipeline/run_cycle.py`**: Passes `as_of` date to broker's `place_order()`.
- **`v2/run_daemon.py`**: Adds `FileHandler` for log persistence; sets `FUND_SPEC_PATH` env var.
- **`app/backend/routes/dashboard.py`**: Cache management and simulation routes, including an explicit simulation preflight.
- **`app/frontend/src/`**: New components `backtest/`, service `simulation-api.ts`, wired into tab system (`tabs-context`, `tab-service`, `top-bar`, `tab-bar`, `Layout`).
