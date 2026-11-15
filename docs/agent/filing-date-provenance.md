# Filing-date provenance

Fundamental metrics entered the cache with a conservative
`report_period + 45 days` filing date. That estimate prevents obvious
lookahead, but it is not the date a filing became public and cannot support
precise event interpretation.

## Current behavior

- `USMarketDataAdapter` asks `SecFilingClient` for recent `10-Q`, `10-K`, and
  `20-F` metadata after Yahoo returns quarterly metrics.
- SEC report dates are matched to the normalized Yahoo quarter end within seven
  calendar days. A match stores the SEC filing date, acceptance timestamp, and
  `filing_date_source=sec_submissions`.
- Rows without a safe match keep `filing_date_source=estimated_45d`. A SEC
  lookup failure is logged and does not fail the metrics fetch.
- Yahoo earnings history is used for PEAD only when Yahoo provides an actual
  earnings announcement date. A successful empty response records `no_data`
  and PEAD abstains; transport or provider failures remain `failed`, retain
  their error category, and are eligible for retry.
- Current-snapshot Yahoo metrics are accepted only when the requested end date
  is today. Historical requests abstain instead of assigning current data to an
  old report period.

## SEC User-Agent

SEC requires a descriptive User-Agent. Set `AIHF_SEC_USER_AGENT` to an
operator-controlled contact string when running outside the default development
configuration. The default is `aihf-research/1.0 admin@example.invalid`.

## Refreshing existing rows

Fresh cache coverage is skipped by normal fetches. To upgrade already cached
metrics to SEC dates, run a forced metrics refresh for the affected tickers:

```bash
.venv/bin/python scripts/aihf_ops.py fetch --tickers AAPL --types metrics --force
```

Unmatched rows remain explicitly marked as estimates. There is no automatic
backfill or database migration.
