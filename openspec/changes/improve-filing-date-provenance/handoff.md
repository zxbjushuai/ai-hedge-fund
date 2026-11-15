# Handoff: Improve Filing-Date Provenance

## Implemented

- Added `SecFilingClient` for SEC ticker/CIK mapping and recent periodic-filing
  report and acceptance metadata.
- `USMarketDataAdapter` enriches quarterly metrics when a SEC report date is
  within seven days of the normalized Yahoo quarter end. Matched rows persist
  `filing_date_source=sec_submissions`; unmatched rows keep `estimated_45d`.
- Removed Yahoo's fiscal-column earnings fallback. Successful empty responses
  become `no_data`; provider failures propagate as retryable market-data errors.
- Historical Yahoo metric snapshots abstain instead of assigning current data to
  an old report period.
- Documented SEC User-Agent configuration and forced-refresh behavior.

## Verification

- Focused SEC/market-data tests: 23 passed.
- Backend full suite: 407 passed, 39 deselected.
- Frontend tests: 32 passed; lint and production build passed.
- Live AAPL enrichment resolved all six returned quarters to SEC acceptance
  dates (`sec_submissions`). A forced backend metrics refresh persisted 11
  AAPL/MSFT rows with SEC dates; 87 unmatched cached rows remain explicitly
  estimated across 21 tickers.
- Built-in Codex review against `backup-20261115-090857` found one P2 issue
  (provider failures collapsed to no-data); it was fixed and the rerun found no
  actionable regressions.

## Follow-up

The SEC client reads the recent submissions feed. Older quarters outside that
feed require paginated filing history. Existing rows need a forced metrics
refresh to acquire SEC dates; unmatched rows remain explicitly estimated.
