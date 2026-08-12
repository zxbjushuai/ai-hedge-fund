## ADDED Requirements

### Requirement: Backtest tab in IDE layout
The system SHALL provide a "Backtest" tab accessible from the top toolbar (BarChart3 icon), following the same VSCode-style tab pattern as Settings and Flow tabs.

#### Scenario: Open Backtest tab
- **WHEN** user clicks the BarChart3 icon in the TopBar
- **THEN** a new tab titled "Backtest" opens with a left-navigation pane and content area, or focuses an existing Backtest tab if already open

#### Scenario: Backtest tab persists across browser refreshes
- **WHEN** user has the Backtest tab open and refreshes the page
- **THEN** the tab is restored from localStorage

### Requirement: Data Cache panel
The Backtest tab SHALL include a "Data Cache" sub-page for fetching, listing, and deleting cached historical data.

#### Scenario: Fetch data
- **WHEN** user enters tickers (comma-separated), start date, end date, and clicks "Fetch Data"
- **THEN** the frontend calls `POST /dashboard/cache/fetch` and displays a result message (e.g., "AAPL: 125 prices, 20 metrics") or error details

#### Scenario: View cached data
- **WHEN** the Data Cache page loads
- **THEN** it calls `GET /dashboard/cache/list` and renders each ticker as a card showing price count/range and metrics count/range, with a delete (trash) button

#### Scenario: Delete cached data
- **WHEN** user clicks the delete button on a ticker card
- **THEN** `DELETE /dashboard/cache/{ticker}` is called and the list refreshes

### Requirement: Run Simulation panel
The Backtest tab SHALL include a "Run Simulation" sub-page for configuring and executing simulations.

#### Scenario: Configure and run
- **WHEN** user fills in tickers, start/end dates, initial capital, and clicks "Run Simulation"
- **THEN** `POST /dashboard/sim/run` is called and a progress bar appears showing `current_day / total_days` with percentage

#### Scenario: Confirm estimated LLM cost
- **WHEN** user clicks "Run Simulation" with a valid configuration
- **THEN** the frontend first calls the preflight endpoint and always displays estimated calls, provider, model, trading days, enabled models, and warnings before submitting with `confirm_cost=true`

#### Scenario: Poll progress
- **WHEN** a simulation is running
- **THEN** the frontend polls `GET /dashboard/sim/status/{id}` every 2 seconds, updating the progress bar, until status becomes `"completed"` or `"failed"`

#### Scenario: View results on completion
- **WHEN** simulation completes
- **THEN** results include four metric cards, a NAV chart with dated horizontal ticks and dollar-valued vertical ticks, trade log, enabled models, and data-quality warnings

### Requirement: Past simulations list
The Run Simulation panel SHALL display a list of previously run simulations, selectable to view their results.

#### Scenario: Load past runs
- **WHEN** the panel loads
- **THEN** `GET /dashboard/sim/runs` is called and each run is rendered as a clickable card showing tickers, date range, status badge, and final NAV

#### Scenario: View past run results
- **WHEN** user clicks a past run card
- **THEN** the result details (NAV curve, trades, metrics) are loaded and displayed below the card list
