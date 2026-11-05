# Design: Carried-Book Daily Simulation

## Parent-run contract

`SimRun.carried_from_run_id` links a child run to the completed run whose final
book it inherits. The child must start on the parent's last recorded NAV date,
use the same benchmark, and use the same normalized ticker set. These checks
prevent accidental forks and ensure every inherited position can be priced.

The carry source is read from the parent's last completed cycle record: its
`cash` and signed `positions` are the post-corporate-action, post-execution
book at the parent's close. The parent's final NAV must agree with that record.

## Runner behavior

A carried `SimBroker` is seeded with inherited cash and positions. The child's
initial NAV snapshot is written on the parent's final valuation date with the
inherited NAV, cash, equity, and positions. The child's `initial_capital` is
therefore the inherited NAV, so return, benchmark normalization, and drawdown
are measured from the continuous account rather than from a fresh deposit.

The existing cycle loop is unchanged. The first child cycle observes the parent
valuation date's close and executes on the next trading day's open. Corporate
actions on that execution day apply to the inherited book, with no replay of
the parent's already-settled actions.

## Persistence

`sim_nav_snapshot.positions_json` stores the signed position book at each NAV
point. It duplicates the cycle audit only at the small boundary needed for a
continuous NAV/position series; existing `sim_cycle_record.payload` remains the
full decision audit.

Both schema additions are additive migrations with safe defaults.

## Operations

`scripts/aihf_ops.py continue` selects an explicit run or the latest completed
run, starts from its valuation date, and uses the same universe. The caller may
choose the end date; default is today. No push or scheduler behavior changes.
