# Design: Test the Deterministic Daily Path

## Scenario

The regression test uses a temporary SQLite database and a price-momentum fund
spec. It seeds two selectable catalog securities (`AAA` and benchmark `SPY`) and
requests three consecutive XNYS sessions through the normal route functions.

The cache-job batch adapter is replaced with a fixed OHLCV response. The real
cache-job manager persists prices and coverage, so the test covers the same
path used by the Web UI rather than seeding `price_cache` directly.

## Execution

After the cache job reaches a terminal state, the test calls the simulation
preflight with the catalog-selected ticker. It then starts a real background
simulation with `confirm_cost=True`. Because the spec contains only
`price_momentum`, no LLM client is resolved and no provider is contacted.

The test polls the status route with a bounded monotonic deadline. On completion
it verifies the result route, NAV curve, benchmark curve, trade isolation, and
cycle audit availability. A failure leaves the simulation's persisted error in
the assertion context for diagnosis.

## Determinism

- Fixed dates select only three known XNYS sessions.
- The batch adapter returns fixed bars and rejects unexpected tickers.
- The fund spec uses no LLM-backed strategy.
- The cache manager and runner are real, but all external I/O is mocked.
