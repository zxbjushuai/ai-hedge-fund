# Handoff: Carried-Book Daily Simulation

## Implemented

- `SimRun.carried_from_run_id` records the completed parent run.
- `sim_nav_snapshot.positions_json` persists the signed position book at every
  NAV point, including the inherited opening snapshot.
- `load_carried_book()` validates completion, valuation-date boundary, benchmark,
  universe, and NAV/cash consistency before a child row is created.
- `SimBroker` accepts an existing signed position book without creating trades.
- A carried run starts its benchmark and return denominator from inherited NAV.
- `POST /dashboard/sim/preflight` and `/dashboard/sim/run` accept
  `carried_from_run_id`; `aihf_ops.py continue` selects and continues a run.

## Invariants

- Signal inputs still come from the child start date only; its first cycle
  executes on the next cached trading day.
- Parent corporate actions are inherited through final cash/positions and are
  not replayed.
- Standalone runs retain fresh-cash behavior.

## Verification

- Backend: 332 passed, 39 deselected.
- Frontend: 28 tests passed; ESLint clean; Vite production build succeeded.
- Temporary backend chain on port 8001: run 15 `2026-08-10..2026-08-14`
  (AAPL/MSFT/SPY) ended at NAV 99654.54; run 16 inherited
  `carried_from_run_id=15`, the same cash and positions, and ended at 98750.27
  on `2026-08-18` with -0.91% return versus -1.15% benchmark.

## Operational Note

Restarting the systemd backend was denied without interactive authentication.
The chain was verified with a temporary backend on `127.0.0.1:8001`, then that
process was stopped. The existing `aihf-backend` process will serve the new
feature after its next authorized restart.

## Follow-ups

- Resume an interrupted run from its last committed cycle (distinct from
  starting a child from a completed parent).
- Automatic daily scheduling remains intentionally out of scope.
