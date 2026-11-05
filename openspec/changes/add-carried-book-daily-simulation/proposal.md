# Proposal: Carried-Book Daily Simulation

## Why

Simulation runs currently start with a fresh cash balance even when a caller
wants to continue the previous day's paper-trading book. That makes a sequence
of daily runs independent backtests rather than a continuous account, and it
prevents the Web API and `aihf_ops.py` from expressing genuine daily paper
trading.

## What Changes

- Allow a simulation request to name a completed parent run whose final book it
  inherits.
- Persist the parent-run link, inherited cash and signed positions, and the
  complete post-cycle position history with each simulation NAV snapshot.
- Start the child on the parent's final valuation date so that date is the
  child's signal day and the next cached trading day is its execution day.
- Normalize child return and benchmark metrics from the inherited NAV.
- Add an `aihf_ops.py continue` path that selects a completed run and submits a
  child run.

## Compatibility

Standalone simulations remain unchanged and default to fresh cash. Existing
rows remain readable; new database columns are nullable or have defaults.

## Non-goals

- Live-broker execution or real-money trading.
- Automatic scheduling of daily simulations.
- Resuming an interrupted run from its last committed cycle.
- Allowing a carried run to change its benchmark or ticker universe.
