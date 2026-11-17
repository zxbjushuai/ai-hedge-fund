# Design: Protect Active Simulation Logs During Retention

## Run-State Source

Simulation telemetry is written to `logs/simulations/sim-{id}.log`, where `id`
is the primary key in `sim_run`. Retention reads `id` and `status` directly from
the configured `fund.db` through a SQLite URI with `mode=ro`. The query selects
only `pending`, `running`, and `cancelling`; terminal rows do not protect a log.
The ops command loads the repository `.env` without overriding exported values
and resolves `FUND_DB_PATH` with the backend's relative-path, `~` expansion, and
absolute-path semantics, so the check targets the service database.

The database file itself is never opened writable. A missing database means no
active simulation state exists. If a database exists but cannot be read, the
retention command exits with an error and does not delete anything.

## Planning

The planner accepts the current active run IDs. Files matching
`simulations/sim-{id}.log` with an active ID are added to the plan's `skipped`
entries with reason `active_simulation` and are excluded from both age and size
budget selection. The plan records the active IDs used for review.

## Apply Safety

`--apply` loads a fresh set of active run IDs immediately before unlink checks.
Even if the saved plan selected a log when its run was terminal or absent, a run
that became pending/running/cancelling after approval is left in place and
reported as `active_simulation`. The existing size and nanosecond-mtime guard
continues to catch a log file opened after planning.

## Compatibility

Plan loading remains backward-compatible with `aihf-retention-plan-v1` files
that omit the new `active_simulation_ids` field. No API or database schema
change is required. The retention command remains dry-run by default and still
requires an explicitly approved plan file for deletion.
