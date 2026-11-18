# Design: Recover Pre-Start Pending Simulations

## Crash window

Run creation commits the `sim_run` row first, then registers the process-local
runner, and finally starts its thread. The row is therefore briefly `pending`
while no worker exists. If the process dies in that window, the next startup is
the first point at which the orphan can be observed.

## Startup recovery

`SimRunner.recover_orphaned_runs()` selects rows in `pending`, `running`, and
`cancelling` order by id and applies one terminal transition per row:

- `pending` -> `failed` with a restart message that states the run was recovered
  before any cycle ran;
- `running` -> `failed` with the existing stale-running restart message;
- `cancelling` -> `cancelled` with the existing last-NAV preservation.

Every recovered row receives the same UTC `completed_at` stamp and is removed
from the process-local runner registry. The pass is idempotent: a second pass
finds no active rows and changes nothing.

## Why failed rather than resumed

A pre-start pending row has no committed book or cycle to continue from. The
truthful terminal state is `failed`; silently resuming would require the
distinct restart-safe machinery planned in AIHF-019. Preserving the row and its
observation log keeps the crash diagnosable.

## Retention and status interaction

Retention treats `pending` runs as active and protects their logs. Recovering
the row to `failed` releases that protection on the next retention pass. The
existing `startup_recovery` payload already reports recovered ids and
failed/cancelled counts, so no API or frontend shape changes are needed.

## Testing

- A direct runner test inserts a pending row with `current_day=0`, runs recovery,
  and asserts the failed status, timestamp, pending-specific message, preserved
  day counter, absent final NAV, and idempotency.
- A lifespan test starts the real FastAPI app against a temporary database with
  a pending row and asserts the status endpoint and simulation detail expose the
  recovered failure.
