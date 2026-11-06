# Design: Incremental Cache Updates

## Coverage planning

`plan_price_fetch()` reads fresh (`<= 24h`) complete price coverage rows for one
ticker and treats each row as covering the trading sessions from its requested
start through its actual end. Complete rows may begin later than requested for a
newly listed security, so the requested start is the safe coverage boundary.

The planner compares expected XNYS sessions with covered sessions and returns
the first missing session through the requested end. A fully covered request is
skipped. A request with no expected sessions is skipped without a remote call.
Stale coverage and forced requests use the full requested range.

XNYS calendars are created with bounded padding around the requested dates so
historical ranges before the library's default first session remain usable. A
planning exception is converted into a failed cache item instead of leaving the
background job stuck in `running`.

If a coverage row was fetched before that session's XNYS close, its final date is
treated as provisional and the next incremental request overlaps it. This
refreshes an intraday bar once the session has finalized without permanently
forcing full-history downloads.

## Fetching

Both the synchronous cache API and cache-job price path consult the planner.
Batch jobs group tickers by their individual gap start and retain the existing
50-ticker bound and individual fallback. Coverage rows continue to describe the
range actually fetched, so later planning can combine adjacent rows. The cache
inventory merges those rows per ticker for display and recalculates completeness
over the union, so a gap is reported as partial. The detail view keeps the full
fetch history.

## Corporate actions

Yahoo adjusted closes for historical dates change after dividends and splits.
When an incremental tail contains either event, the fetch is repeated over the
original requested range before persistence. This keeps every benchmark
adjusted-close series internally consistent without refreshing on ordinary
trading days.

## Failure behavior

Only `complete` coverage participates in gap detection. Failed or partial rows
remain retryable under the existing status and error contract.
