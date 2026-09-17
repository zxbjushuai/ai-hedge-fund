## Why

The Web simulation currently configures a run by mutating `FundSpec.universe`
and builds its time grid from the intersection of every selected ticker's
cached prices. One missing ticker bar can therefore remove a market day for
the whole run. Results also lack a benchmark, benchmark curve, and excess
return, so the effective study cannot be reproduced or compared consistently.

## What Changes

- Make the effective universe an explicit `run_cycle` input while retaining an
  optional FundSpec default for compatibility.
- Record the effective universe on every `CycleRecord` and `SimRun`.
- Add a per-run benchmark, defaulting to SPY, and derive the simulation market
  grid solely from its cached bars.
- Persist benchmark NAV beside fund NAV and expose benchmark/excess returns.
- Treat missing individual-security bars locally while failing when an
  existing position cannot be valued.
- Add explicit benchmark price acquisition and Web configuration/results UI.

## Non-Goals

- LLM provider selection or response normalization.
- Event-driven persona state.
- Full cycle audit persistence and drill-down.
- Security catalog, saved universes, or background batch cache jobs.
- Weekly or monthly rebalance cadence.

## Impact

- `v2/fund/` and `v2/pipeline/` runtime universe contracts.
- `v2/simulation/` time-grid, price handling, and result metrics.
- Additive SQLite migrations for simulation benchmark data.
- Dashboard cache/simulation APIs and React backtest UI.
