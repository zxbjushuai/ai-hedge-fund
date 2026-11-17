# Proposal: Protect Active Simulation Logs During Retention

## Why

Retention currently protects recent files and the newest file per managed
directory, but it does not inspect simulation run state. A stale approved plan
could therefore delete `logs/simulations/sim-{id}.log` while that run is still
pending, starting, running, or cancelling. That removes the only per-run
telemetry needed to diagnose an in-flight failure.

## What Changes

- Read active simulation IDs from `sim_run` using a read-only SQLite connection.
- Treat `sim-{id}.log` as protected when the run status is `pending`, `running`,
  or `cancelling`.
- Re-read active run state when applying a saved plan, so a run that starts
  after plan approval cannot have its log deleted by that stale plan.
- Fail closed when an existing database cannot be read for state.
- Report protected active-run files in the retention plan and update the
  retention runbook.

## Non-goals

- Deleting or mutating simulation rows.
- Automatically cleaning logs during a simulation or daily run.
- Changing the manual approval requirement for `--apply`.
- Managing agent, service, database, or prompt-cache files.
