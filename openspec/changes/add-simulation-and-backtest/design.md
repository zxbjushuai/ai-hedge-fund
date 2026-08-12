## Context

The existing AI hedge fund pipeline (`v2/pipeline/run_cycle.py`) depends on live data clients (FDClient or YFinanceClient). There is no way to backtest strategies against historical data or simulate fund performance over a period. The system also lacks persistent logging for debugging daemon crashes or inspecting past cycle behavior.

This change adds a data caching layer, a mock data client, a day-by-day simulation engine, simulation API endpoints, and a React frontend panel — all integrated into the existing codebase without disrupting the live trading flow.

**Constraints:**
- All persistent data stays in a single SQLite database (`fund.db`)
- The `DataClient` protocol must be respected so `run_cycle()` works unchanged
- The existing `PromptCache` (`.v2_cache/llm/`) already prevents redundant LLM calls during simulation
- Each database path owns an isolated SQLAlchemy engine/session factory
- Simulation execution uses an in-memory broker and writes only to `sim_*` result tables

## Goals / Non-Goals

**Goals:**
- Enable fetching historical OHLCV prices and quarterly financial metrics from yfinance and caching them locally
- Provide a `MockDataClient` that reads from the cache with point-in-time filtering
- Run `run_cycle()` day-by-day through cached data, recording NAV and trades
- Expose simulation lifecycle via REST API (start, poll status, get results)
- Add a React frontend panel for cache management and simulation control
- Persist all daemon logs to a rotating file

**Non-Goals:**
- Real-time chart libraries (use inline SVG for NAV curve)
- Multi-strategy optimization or parameter sweeping
- News/insider-trade data in simulation (not available from yfinance)
- Replacing the existing live flow-based editor UI

## Decisions

### 1. Single SQLite DB with separate simulation tables
**Chosen:** All new tables (`price_cache`, `metrics_cache`, `earnings_cache`, `sim_run`, `sim_trade_log`, `sim_nav_snapshot`) live in the same `fund.db` alongside existing ledger tables.
**Rationale:** Single-file portability; no need for multi-DB management. Simulation tables are prefixed (`sim_`) to avoid conflicts.
**Alternative considered:** Separate `simulation.db` — rejected for added complexity with no benefit.

#### Database-path isolation
The v2 persistence layer does not define one permanent production database and one permanent test database. Instead, `init_db(db_path)` resolves the supplied path to an absolute path and keeps a separate SQLAlchemy engine and session factory for each resolved path. Normal daemon execution defaults to the repository-root `fund.db`; tests pass a database under pytest's temporary directory. A session created for one path is therefore never rebound to another path. Cache, simulation, and live-ledger tables share the configured v2 database file but remain logically isolated by table. The legacy application database at `app/backend/hedge_fund.db` belongs to the older flow/configuration subsystem and is not used by the v2 simulation runner.

#### New-table data dictionary

| Table | Column | Meaning |
|---|---|---|
| `price_cache` | `id` | Internal primary key. |
| | `ticker` | Exchange ticker symbol, such as `AAPL` or `MSFT`. |
| | `date` | Trading date for the daily bar. |
| | `open`, `high`, `low`, `close` | Daily OHLC prices used for signal history, next-open execution, and close valuation. |
| | `volume` | Number of shares reported as traded for the day. |
| | `created_at` | UTC time at which the cache row was written. |
| `metrics_cache` | `id` | Internal primary key. |
| | `ticker` | Company ticker to which the filing belongs. |
| | `report_period` | Fiscal period end represented by the financial statement. |
| | `filing_date` | Date on which the metrics become visible to the simulation. |
| | `filing_date_source` | Provenance of the visibility date, such as `estimated_45d`. |
| | `data` | JSON-serialized `FinancialMetrics`, including profitability, balance-sheet, cash-flow, per-share, and shares-outstanding values. |
| | `created_at` | UTC cache-write time. |
| `earnings_cache` | `id` | Internal primary key. |
| | `ticker` | Company ticker for the earnings event. |
| | `report_period` | Fiscal period covered by the earnings result. |
| | `announcement_date` | Point-in-time date on which the event becomes available. |
| | `actual_eps`, `estimated_eps` | Reported and consensus earnings per share when Yahoo supplies them. |
| | `surprise_pct` | Percentage difference between actual and estimated EPS; nullable because Yahoo often omits it. |
| | `created_at` | UTC cache-write time. |
| `sim_run` | `id` | Simulation identifier used by status and result APIs. |
| | `name` | Optional user-facing run name. |
| | `tickers` | JSON array containing the simulated investment universe. |
| | `start_date`, `end_date` | Requested historical date range. |
| | `initial_capital`, `final_nav` | Starting cash and final net asset value. |
| | `status` | Lifecycle state: `pending`, `running`, `completed`, or `failed`. |
| | `current_day`, `total_days` | Progress counters over cached trading days. |
| | `error_message` | Failure detail, populated only for failed runs. |
| | `warnings` | JSON array of non-fatal data-quality and model-availability warnings. |
| | `models` | JSON array of models actually enabled after preflight. |
| | `created_at`, `completed_at` | UTC lifecycle timestamps. |
| `sim_trade_log` | `id` | Internal trade primary key. |
| | `sim_run_id` | Owning simulation; keeps trades isolated from other runs and the live ledger. |
| | `ticker`, `side`, `quantity` | Instrument, `BUY`/`SELL`, and filled whole-share quantity. |
| | `price`, `fee`, `total_amount` | Fill price, commission, and gross transaction amount. |
| | `cycle_date` | Historical date on which the next-open fill occurred. |
| | `created_at` | UTC persistence time. |
| `sim_nav_snapshot` | `id` | Internal snapshot primary key. |
| | `sim_run_id` | Owning simulation. |
| | `cycle_date` | Historical close represented by the snapshot. |
| | `nav` | Cash plus closing market value of positions. |
| | `cash` | Uninvested cash after that day's fills. |
| | `equity` | Closing market value of held positions. |
| | `created_at` | UTC persistence time. |

### 2. Historical financials from yfinance DataFrames
**Chosen:** Use `stock.quarterly_financials`, `stock.quarterly_balance_sheet`, `stock.quarterly_cashflow` to build `FinancialMetrics` per quarter. Fallback to `stock.info` snapshot if DataFrames are empty.
**Rationale:** These DataFrames contain historical income statement, balance sheet, and cash flow items (revenue, net income, equity, etc.) spanning multiple years. While yfinance cannot provide historical P/E ratios or market cap, the key metrics for LLM analysis (ROE, margins, D/E, revenue growth) can be computed.
**Alternative considered:** Only `stock.info` snapshot — rejected because identical data for all dates makes LLM cache hits meaningless (no signal evolution over time).

### 3. MockDataClient with DB-level point-in-time filtering
**Chosen:** `MockDataClient` filters metrics by `filing_date <= end_date`. Quarterly metrics without an authoritative filing date become visible at `report_period + 45 days` and are labelled `estimated_45d`; current valuation fields are excluded from historical rows.
**Rationale:** Ensures lookahead-free backtesting. The same data served to any `as_of` date in `run_cycle()` matches what would have been publicly available on that date.
**Alternative considered:** In-memory pandas DataFrames — rejected for consistency with the `DataClient` protocol and database persistence.

### 4. Separate broker instance per simulation
**Chosen:** `SimRunner` uses one in-memory `SimBroker` for the whole run. Fill events and close NAV are copied directly to `sim_trade_log` and `sim_nav_snapshot` in the main database; live ledger tables are never touched.
**Rationale:** Prevents simulation trades from mixing with live trades and avoids global database-session rebinding. The in-memory broker is discarded after the run.
**Timing:** signals observe data available through the preceding trading-day close, fills use the next cached trading day's open, and NAV uses that day's close. Quarterly metrics become visible at report period + 45 days (`estimated_45d`), and Yahoo EPS surprises are stored in `earnings_cache`.

### 5. React Backtest panel as a tab (matching Settings pattern)
**Chosen:** Added as a new `'backtest'` tab type, opened via a `BarChart3` icon button in the TopBar alongside Settings. Follows the existing left-nav + right-content pattern from `Settings`.
**Rationale:** Consistent UX. No new page/routing needed — fits into the existing VSCode-style tab system.
**Alternative considered:** Standalone page/route — rejected because the project uses no React Router; all navigation is tab-based.

### 6. Inline SVG for NAV chart
**Chosen:** Render NAV curve as an `<svg>` element with `polyline`. No chart library dependency.
**Rationale:** Avoids adding a new npm dependency (recharts, visx, etc.) for a single chart. Sufficient for showing trend direction and magnitude.
**Alternative considered:** recharts — simpler but adds ~200KB to bundle.

### 7. Always-visible API usage preflight
**Chosen:** `POST /dashboard/sim/preflight` always returns a cold-cache upper-bound estimate and the UI always shows a confirmation dialog before starting a simulation. `POST /dashboard/sim/run` requires `confirm_cost=true` regardless of the estimate.
**Rationale:** A threshold hid useful information for small runs. Showing the estimate every time makes API use predictable while the prompt cache can still reduce actual calls.

### 8. ModelScope as the low-cost simulation provider
**Chosen:** Add an OpenAI-compatible ModelScope client using `MODELSCOPE_API_KEY`, `https://api-inference.modelscope.cn/v1/`, and configurable `V2_LLM_MODEL` (default `Qwen/Qwen3-4B`). Explicit provider configuration wins; otherwise ModelScope is preferred when its key exists.
**Rationale:** It provides a lightweight test path without coupling simulation code to a proprietary SDK. Secrets remain in the process environment rather than repository files.

### 9. Point-in-time valuation plus deterministic trend baseline
**Chosen:** Cache historical shares outstanding and reconstruct market cap, P/B, and P/E using the latest close and visible filings. Add a 20-day price-momentum strategy to the example fund. Disable PEAD during preflight when the selected cache has no actionable EPS surprises.
**Rationale:** Historical agents previously received no valuation context and all abstained, while Yahoo frequently returned earnings dates with null surprise values. The trend sleeve makes a simulation capable of trading without extra API calls and is kept explicit in the fund specification.

### 10. OpenRouter free-model routing
**Chosen:** Add an OpenAI-compatible OpenRouter client using `OPENROUTER_API_KEY`, `https://openrouter.ai/api/v1`, and configurable `V2_LLM_MODEL` (default `openrouter/free`). OpenRouter becomes the configured simulation provider while ModelScope and DeepSeek remain available.
**Rationale:** The free router tracks currently available zero-cost models, avoiding a hard dependency on a free model slug that may later be removed. Provider attribution headers are included, while credentials remain environment-only.

### 11. Persistent logs partitioned by local date
**Chosen:** A shared logging handler writes to `logs/YYYY-MM-DD/backend.log` and switches directory at local midnight. Uvicorn uses the same root handlers. Full-app shell launchers retain `frontend.log` and `backend-console.log` beside it instead of using a temporary directory.
**Rationale:** One directory per day makes simulation failures and API activity easy to inspect without mixing an indefinitely growing file. Logs are append-only and are not automatically deleted; retention can be added explicitly later.

### 12. Investor personas versus systematic models
**Chosen:** The example v2 fund enables three LLM personas (`graham`, `buffett`, and `munger`) plus deterministic quant models. Graham emphasizes balance-sheet strength and margin of safety; Buffett emphasizes durable business quality, capital allocation, and reasonable valuation; Munger emphasizes failure modes, consistency, and avoiding unclear or overpriced businesses. Each persona is a distinct system prompt sent to the configured LLM and produces one signal per ticker per distinct point-in-time fundamentals snapshot. Historical valuation fields normally change with each daily close, so the cold-cache upper bound is `(trading_days - 1) * ticker_count * LLM_persona_count`. The prompt cache removes a call only when the complete prompt is unchanged or has already been evaluated. `pead` and `price_momentum` are mathematical models and make no LLM calls.
**Rationale:** The root README describes the legacy v1 system's larger set of 19 agents and manager stages. That list does not describe the currently enabled v2 simulation fund. V2 treats both personas and quant signals as interchangeable alpha models, and only models explicitly present in the fund YAML execute.

## Risks / Trade-offs

- **[Log retention]** Daily logs are intentionally preserved and no automatic deletion policy is applied. Long-running installations should archive them externally until retention requirements are defined.

- **[ModelScope account activation]** The API key must belong to an account enabled for hosted inference; provider-side 401 errors fail the run instead of being converted into neutral signals.

- **[Yahoo rate limiting]** → `_retry()` backs off 0.5s/1s/2s before giving up. User must wait for rate limit reset. Consider adding a configurable delay or proxy support later.
- **[LLM cost during simulation]** → Mitigated by existing `PromptCache`: financial data only changes quarterly, so most days are cache hits (3-4 actual LLM calls per ticker per year).
- **[Estimated filing dates]** → Yahoo does not expose reliable historical filing dates for these frames. The API/UI labels the conservative 45-day estimate; current market-cap and valuation fields are excluded instead of backfilled with today's values.
