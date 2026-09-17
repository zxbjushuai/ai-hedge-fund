## 1. Phase 1 — Signal Correctness

- [x] 1.1 Add explicit Yahoo EPS surprise percentage parsing and actionable-event helpers
- [x] 1.2 Declare the HTML parser required by Yahoo Earnings Dates
- [x] 1.3 Keep incomplete Yahoo EPS events neutral without cross-provider joins or fabricated surprise
- [x] 1.4 Reconstruct historical LLM valuation at the filing-date close rather than every simulation close
- [x] 1.5 Estimate prompt usage from distinct filing snapshots and unique personas
- [x] 1.6 Expose Yahoo earnings parsing and missing-surprise warnings without stopping other models
- [x] 1.7 Add unit and integration coverage for Yahoo EPS availability, neutral PEAD fallback, point-in-time valuation, prompt stability, and preflight estimates
- [x] 1.8 Run targeted and full non-live v2 tests

## 2. Phase 2 — Event-Driven LLM

- [x] 2.1 Add persisted effective persona signal state keyed by ticker and model
- [x] 2.2 Bootstrap all eligible universe tickers at simulation start
- [x] 2.3 Detect new-filing, earnings-surprise, valuation-bucket, universe-entry, and maximum-age events
- [x] 2.4 Refresh only event tickers and reuse still-valid state for non-event tickers
- [x] 2.5 Preserve valid prior state on refresh failure and abstain only when no valid state exists
- [x] 2.6 Materialize a complete point-in-time daily signal set before existing portfolio construction
- [x] 2.7 Add event-driven preflight estimates, audit metadata, and chronological no-lookahead tests

## 3. Phase 3 — Security Catalog and Batch Cache UX

- [ ] 3.1 Add a local security catalog with source, exchange, type, sector, liquidity, active status, and refresh metadata
- [ ] 3.2 Synchronize a Yahoo-screened catalog behind a provider interface that can later accept SEC/Nasdaq sources
- [ ] 3.3 Add searchable/filterable/paginated security APIs and saved universes
- [ ] 3.4 Replace ticker text entry with searchable multi-select, select-page/select-filtered, and cached-coverage indicators
- [ ] 3.5 Add bounded in-memory historical cache jobs with progress, cancellation, backoff, and failed-ticker retry
- [ ] 3.6 Batch price downloads, limit fundamentals/earnings concurrency, and bulk-upsert cache rows
- [ ] 3.7 Skip already-complete coverage and clearly report partial data quality
- [ ] 3.8 Add API, worker, frontend, rate-limit, and partial-failure tests
