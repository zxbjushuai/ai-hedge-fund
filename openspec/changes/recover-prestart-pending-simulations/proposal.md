# Proposal: Recover Pre-Start Pending Simulations

## Why

`SimRunner.create()` commits a `sim_run` row with `status='pending'` before the
background worker thread starts. A backend crash or hard kill in that window
leaves the row pending even though no worker can ever own it. Startup recovery
currently rewrites `running` and `cancelling` rows only, so the orphaned pending
row stays pending forever: the dashboard reports an active simulation, retention
protects its log indefinitely, and the run can never reach a terminal state.

## What Changes

- Include `pending` rows in the startup orphan-recovery pass.
- Mark a recovered pre-start pending row `failed`, record a UTC completion
  timestamp, and set a pending-specific restart error message.
- Preserve `current_day`, NAV snapshots, trades, and cycle audits for diagnosis;
  do not invent a final NAV when no cycle ran.
- Keep the existing startup recovery summary, so recovered pending rows are
  counted with the other recovered simulations.
- Add direct runner-level and FastAPI lifespan regression tests for the
  create-before-start crash window.

## Compatibility

The change is additive: no schema migration is required, terminal rows remain
untouched, and the recovery report keeps its existing shape. Pending rows in a
live process exist only between row creation and worker start, and startup
recovery runs before the API serves requests, so a startup scan cannot race a
new run. Resuming an interrupted run from its last committed cycle remains
AIHF-019 and is not attempted here.

## Non-goals

- Resuming or automatically retrying a recovered simulation.
- Changing the simulation creation transaction or worker startup handshake.
- Web UI changes for recovery counts; that remains AIHF-021.
- Deleting simulation telemetry or database rows.
