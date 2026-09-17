## ADDED Requirements

### Requirement: Persist operational logs by local date
The system SHALL retain daemon, API, scheduler, and simulation logs under `logs/YYYY-MM-DD/` and SHALL switch the backend log destination after local midnight.

#### Scenario: Start the full application
- **WHEN** the user starts the daemon directly or through a full-app launcher
- **THEN** `backend.log` records configuration, API access, simulation preflight, lifecycle, trades, completion, and failures without recording API keys

#### Scenario: Stop the full application
- **WHEN** the launcher shuts down the backend and frontend processes
- **THEN** the daily backend, backend-console, and frontend logs remain available for later inspection

### Requirement: Run day-by-day simulation over cached data
The system SHALL execute `run_cycle()` on cached trading days for which the selected universe has complete bars, using point-in-time cached inputs.

#### Scenario: Start a simulation
- **WHEN** user POSTs `{"tickers":["AAPL"], "start_date":"2025-01-01", "end_date":"2025-06-30", "initial_capital":100000}` to `/dashboard/sim/run`
- **THEN** data and LLM configuration are preflighted, a `SimRun` record is created, and a background thread begins iterating through cached trading days

#### Scenario: Always report estimated LLM usage
- **WHEN** user POSTs a valid simulation request to `/dashboard/sim/preflight`
- **THEN** the response includes the cold-cache upper-bound `estimated_llm_calls`, calculated as `(trading_days - 1) * ticker_count * enabled_LLM_persona_count`, plus provider, model, trading-day count, enabled models, and warnings, even when the estimate is small or zero

#### Scenario: Reconstruct historical valuation
- **WHEN** cached shares, book value per share, EPS, and a point-in-time close are visible as of a simulation date
- **THEN** the data client reconstructs market cap, P/B, and trailing P/E without using current valuation fields

#### Scenario: Earnings surprise data is unavailable
- **WHEN** the selected universe has no cached non-null EPS surprise values through the simulation end date
- **THEN** PEAD is disabled with a warning while other configured strategies continue

#### Scenario: Deterministic momentum baseline
- **WHEN** at least 21 point-in-time closes are available for the default 20-day momentum model
- **THEN** it emits a bounded conviction from the trailing return without making an LLM call

#### Scenario: Historical execution has no same-close lookahead
- **WHEN** a signal is formed from data visible at a trading-day close
- **THEN** its orders fill at the next cached trading day's open and NAV is marked at that day's close

#### Scenario: Simulation isolates trades from live fund
- **WHEN** a simulation runs
- **THEN** its in-memory `SimBroker` records fills into `sim_trade_log` in the main database, never to the live `trade_log` table

#### Scenario: Poll simulation progress
- **WHEN** user GETs `/dashboard/sim/status/{id}` while simulation is running
- **THEN** the response includes `current_day`, `total_days`, and `status: "running"`

#### Scenario: Simulation completes
- **WHEN** all complete cached trading days have been processed
- **THEN** the `SimRun` status becomes `"completed"` and `final_nav` is computed from the last close NAV snapshot

#### Scenario: Simulation fails loudly
- **WHEN** configuration, data, LLM, or a daily cycle raises an unrecoverable error
- **THEN** the run becomes `"failed"` with `error_message` and is never reported as a successful zero-trade run

### Requirement: Retrieve simulation results
The system SHALL return full simulation results including NAV curve, trade log, and performance metrics.

#### Scenario: Get complete results
- **WHEN** user GETs `/dashboard/sim/result/{id}` for a completed simulation
- **THEN** the response includes `nav_curve` (array of {date, nav, cash, equity}), `trades` (array of all orders), `total_return_pct`, `max_drawdown_pct`, `sharpe_ratio`, and summary fields

#### Scenario: Get results for running simulation
- **WHEN** user GETs `/dashboard/sim/result/{id}` for a still-running simulation
- **THEN** partial results (NAV curve up to current day, trades so far) are returned

### Requirement: List past simulation runs
The system SHALL list all simulation runs with summary metadata.

#### Scenario: List all runs
- **WHEN** user GETs `/dashboard/sim/runs`
- **THEN** the response includes an array of runs each with `id`, `name`, `tickers`, `start_date`, `end_date`, `initial_capital`, `status`, `current_day`, `total_days`, `final_nav`, `created_at`
