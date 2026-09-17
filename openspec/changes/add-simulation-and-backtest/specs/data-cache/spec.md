## ADDED Requirements

### Requirement: Fetch historical data from yfinance
The system SHALL fetch daily OHLCV prices, quarterly financial metrics, and EPS announcement events from Yahoo Finance, caching them in `price_cache`, `metrics_cache`, and `earnings_cache`.

#### Scenario: Fetch multiple ticker symbols
- **WHEN** the request contains `AAPL` and `MSFT`
- **THEN** the system treats them as two independent securities (Apple Inc. and Microsoft Corporation), fetches and stores one historical series per ticker, and reports success or failure independently for each

Ticker inputs define the investment universe; they are not different data types. The same price, financial-metric, and earnings datasets are fetched for every requested ticker. A multi-ticker simulation lets the strategy compare and allocate capital across companies, while a single-ticker simulation evaluates only that security.

#### Scenario: Fetch prices for a single ticker
- **WHEN** user POSTs `{"tickers":["AAPL"], "start_date":"2025-01-01", "end_date":"2025-06-30"}` to `/dashboard/cache/fetch`
- **THEN** the system downloads OHLCV bars for each trading day in the range and upserts them into `price_cache` (deduplicating on ticker+date)

#### Scenario: Fetch financial metrics with quarterly granularity
- **WHEN** the same fetch request runs
- **THEN** the system extracts quarterly financial statements from yfinance, computes derived metrics (ROE, margins, revenue growth), and upserts them into `metrics_cache` as JSON-serialized `FinancialMetrics` objects

#### Scenario: Financial metrics become visible conservatively
- **WHEN** a quarterly metric is cached without an authoritative historical filing date
- **THEN** its visibility date is report period plus 45 days, labelled `estimated_45d`, and current valuation fields are excluded

#### Scenario: Fetch earnings events for PEAD
- **WHEN** Yahoo provides an earnings announcement with actual and estimated EPS
- **THEN** the event and computed surprise are upserted into `earnings_cache` by ticker and announcement date

#### Scenario: Invalid ticker returns partial error
- **WHEN** a ticker yields no data from yfinance (invalid symbol or API error)
- **THEN** the response includes `{"error": "prices: <details>"}` for that ticker while other tickers in the same request succeed independently

### Requirement: List and manage cached data
The system SHALL provide endpoints to list all cached tickers with data ranges and to delete cached data for a specific ticker.

#### Scenario: List cache
- **WHEN** user GETs `/dashboard/cache/list`
- **THEN** the system returns a JSON object keyed by ticker with price, metric, and earnings summaries plus a filing-date quality note

#### Scenario: Delete cache for one ticker
- **WHEN** user DELETEs `/dashboard/cache/AAPL`
- **THEN** all price, metric, and earnings cache rows for AAPL are removed and deletion counts are returned
