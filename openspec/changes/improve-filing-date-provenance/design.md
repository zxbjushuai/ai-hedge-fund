# Design: Improve Filing-Date Provenance

## SEC Source

`SecFilingClient` reads `https://www.sec.gov/files/company_tickers.json` once
per process to map a ticker to a CIK, then reads the ticker's
`data.sec.gov/submissions/CIK##########.json` recent filing table. Only
`10-Q`, `10-K`, and `20-F` forms with both acceptance and report dates are
considered. The existing `AIHF_SEC_USER_AGENT` environment variable can supply
the required SEC User-Agent; the default identifies this research project.

## Matching

Yahoo normalizes fiscal quarter ends to calendar boundaries, while SEC report
dates preserve the issuer's exact fiscal calendar. A filing is matched to a
metrics row only when its report date differs by at most seven calendar days.
The closest report date wins, with an earlier filing date breaking ties. A
missing or ambiguous match leaves the conservative `report_period + 45 days`
estimate unchanged.

## Persistence

`FinancialMetrics` carries `filing_date_source` through the adapter boundary.
The cache stores the supplied source instead of unconditionally overwriting it
with `estimated_45d`. Existing rows are upgraded the next time metrics are
fetched without cache freshness skipping.

## Uncertainty

Yahoo's earnings-date endpoint is the only source used for PEAD announcement
dates. A successful empty response produces no actionable records rather than
pretending the quarter-end date is the announcement date. Transport failures
still propagate as retryable market-data errors. The cache counts only
persisted dated events and records `no_data` when none exist, so PEAD abstains.
