# Design: US Security Catalog and Batch Cache

## Architecture

`MarketDataAdapter` is selected by market, not by a user-configurable provider.
`USMarketDataAdapter` owns Nasdaq Trader catalog parsing and Yahoo symbol/data
normalization. HK and CN adapters raise `UnsupportedMarketError` and document the
future currency/calendar/catalog work.

The current catalog is stored locally. Disappearing listings are made inactive,
never removed. Saved universes reference catalog rows while simulations continue
to persist their effective ticker snapshot.

## Price contract

New Yahoo requests explicitly use unadjusted OHLCV and include adjusted close,
dividends, and splits. Existing rows become `legacy_unknown`. A new simulation
requires raw rows throughout its requested data and an adjusted close for every
benchmark day.

At the beginning of an execution day, before orders, splits adjust prior
holdings and dividends change cash. Fractional shares created by a split are
settled at that day's raw open so the existing integer-share model is retained.
Corporate-action audit rows are committed atomically with the completed cycle.

## Jobs and coverage

Cache jobs are process-local. Price retrieval is batched; missing batch members
receive bounded individual retries. Fundamentals and earnings use a separate
two-worker limit. Retryable failures honor `Retry-After` where available and use
1/2/4 second backoff with jitter.

Coverage records distinguish the requested range from returned rows. A US
exchange calendar supplies expected sessions. Leading absence for a newly listed
security is recorded as actual coverage rather than a transport failure. Users
can force refresh; otherwise successful fresh ranges are skipped idempotently.

## Security and failure handling

Only categorized, sanitized errors are persisted. Network requests happen
outside SQLite transactions and successful rows are bulk-upserted in short
transactions. One ticker failure never rolls back other completed tickers.

## Limitations

The catalog is current, so old backtests retain survivorship bias. Yahoo filing
dates remain estimated where authoritative timestamps are unavailable. Cache-job
state is lost on restart, while already committed market data remains.
