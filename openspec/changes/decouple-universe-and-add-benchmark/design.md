## Context

`SimRunner` currently overwrites `spec.universe`, `_trading_days` requires a
bar for every selected ticker, and empty execution/valuation price maps fall
back to signal-day marks through Python truthiness. These behaviors couple a
fund mandate to one study, shrink the calendar when any ticker is missing, and
can accidentally fill at the wrong day's price.

## Decisions

### Runtime universe with compatibility fallback

`FundSpec.universe` becomes optional. `run_cycle` accepts an explicit universe,
normalizes it once, and falls back to the FundSpec value only for legacy CLI
callers. Simulation and preflight always pass the run universe explicitly.
`CycleRecord.universe` is the audited effective value.

### Per-run benchmark

The Web request owns `benchmark`, defaulting to SPY. `SimRun.tickers` remains
the effective-universe storage for compatibility and `SimRun.benchmark` stores
the benchmark. The benchmark supplies the daily grid but is not added to the
tradeable universe. A user may explicitly include the same symbol in both.

### Benchmark NAV persistence

`SimNavSnapshot.benchmark_nav` is nullable for old runs and populated for all
new snapshots. It is scaled to initial capital from the first benchmark close.
Benchmark and excess returns are derived from the stored curve. Old rows return
null benchmark fields rather than fabricated data.

### Missing-price behavior

- Fewer than two benchmark bars is a preflight error.
- An unheld security without a recent signal-day close is skipped locally.
- Missing T+1 open prevents only that security's order; an existing holding is
  left unchanged.
- A held security without a T+1 close fails the run because NAV is unknowable.
- Empty explicit price maps never fall back to signal-day marks.
- Insufficient fundamentals are warnings; persona agents abstain until enough
  point-in-time filings exist.

### Cache boundary

The cache request accepts a benchmark. If it is not tradeable, only benchmark
prices are fetched. Simulation never performs network acquisition; missing
benchmark coverage is an actionable preflight error.

## Compatibility

- Existing Fund YAML files and callers that omit the runtime universe continue
  to use their embedded default.
- Existing `tickers` request/result fields remain unchanged.
- SQLite migration is additive and old simulations expose null benchmark data.
- Historical T signal / T+1 open execution / T+1 close valuation is preserved.
