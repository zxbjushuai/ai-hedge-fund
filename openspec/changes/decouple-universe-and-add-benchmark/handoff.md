# Current Handoff

## Status

completed

## Scope

Workstream 1 only: runtime universe, benchmark-derived market grid, benchmark
performance, and local missing-price behavior. See `proposal.md`, `design.md`,
and `tasks.md` in this directory.

## Implemented

- Added an optional FundSpec compatibility universe plus normalized explicit
  run-time universes on `run_cycle` and `CycleRecord` (tasks 1.1-1.2).
- Made missing execution opens local to one ticker, prevented empty price-map
  fallback, and retained fail-loud held-position valuation (task 1.3).
- Replaced the all-ticker price intersection with a benchmark-only grid,
  persisted benchmark NAV, and returned benchmark/excess performance
  compatibly for new and old runs (tasks 2.1-2.4).
- Added per-run benchmark API validation, price-only benchmark acquisition,
  Web controls, comparison metrics, and a dual NAV chart (tasks 3.1-3.3).
- Added regression tests for normalization, calendar independence, price
  gaps, migrations, cache/preflight behavior, benchmark results, and legacy
  null results (task 4.1).

## Changed Files

- `v2/fund/`, `v2/pipeline/` - run-time universe contract and price semantics.
- `v2/persistence/`, `v2/simulation/` - additive schema, benchmark calendar,
  persistence, metrics, and regression coverage.
- `app/backend/routes/dashboard.py` - benchmark-aware cache and simulation APIs.
- `app/frontend/src/components/backtest/` and `services/simulation-api.ts` -
  benchmark configuration, result types, metrics, and chart.
- This OpenSpec directory - proposal, design, completed tasks, and handoff.

## Decisions Made

- The Web request owns the benchmark and defaults it to SPY.
- `SimRun.tickers` remains the effective-universe field for compatibility.
- Benchmark membership never implies tradeability; it is traded only when the
  user also includes it in `tickers`.
- Simulation does not fetch network data. Cache acquisition explicitly fetches
  benchmark prices, and preflight rejects insufficient benchmark coverage.
- Missing individual opens skip only affected orders; missing closes for held
  positions fail because NAV cannot be stated honestly.
- Fewer than four visible financial periods is a warning. Existing persona
  behavior abstains until the ticker becomes eligible.

## Database Changes

- Added nullable `sim_run.benchmark VARCHAR(10)`.
- Added nullable `sim_nav_snapshot.benchmark_nav FLOAT`.
- Migration is additive. Existing rows retain null benchmark values and APIs
  return null benchmark metrics rather than fabricating historical SPY data.

## Tests

- `poetry run pytest v2/fund/test_spec.py v2/pipeline/test_run_cycle.py v2/simulation/test_historical_semantics.py`
  - 40 passed.
- `poetry run pytest v2/`
  - 151 passed, 38 live tests deselected by project configuration.
- `npm.cmd run build` from `app/frontend`
  - passed; existing font-resolution, sourcemap, Browserslist, and bundle-size
    warnings remain.
- ESLint on the four changed frontend files
  - passed with zero warnings.
- Repository-wide `npm.cmd run lint`
  - ran but remains failing on 241 errors and 13 warnings already spread across
    unrelated Flow, output, context, hook, UI, and Tailwind files. The touched
    files were cleaned and verified separately; global lint cleanup is outside
    this change.
- `git diff --check` and Python `compileall`
  - passed; Git reports only the repository's existing LF-to-CRLF notices.

## Known Issues

- Full repository ESLint is not clean for pre-existing unrelated code.
- Cache acquisition remains synchronous; background jobs belong to Workstream 5.
- Complete cycle records are not persisted; that belongs to Workstream 3.

## Stable Contract for the Next Change

- Every simulation has an explicit normalized universe and benchmark.
- Benchmark cached closes define the market grid and never implicitly enter the
  analyzed/traded universe.
- New NAV rows carry benchmark NAV; old rows and their derived metrics are null.
- T signal / T+1 open execution / T+1 close valuation remains unchanged.
- One missing security bar does not remove a benchmark market day globally.

## Git State

- Branch: `zxb_dev`.
- Implementation and this OpenSpec change are included in the associated
  `fix#20260907 zxb:` Git commit; use Git history for the final commit hash.
- Parent roadmap/handoff files remain untracked and were not modified by this
  change.

## Stable Parent Invariants

- Keep SQLite and the React/Vite plus FastAPI Web application.
- Preserve point-in-time inputs and T signal / T+1 open execution.
- Keep Yahoo-only actionable EPS surprise and quarterly prompt stability.
- Do not merge upstream wholesale or implement later roadmap workstreams.
