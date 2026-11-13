# Design: Add Simulation Cancellation

## API contract

`POST /dashboard/sim/{sim_id}/cancel` returns the current status payload:

- `404` when the run does not exist;
- `409` when the run is already `completed`, `failed`, or `cancelled`;
- `200` with `status=cancelling` when a process-local worker accepted the
  request;
- `200` with `status=cancelled` when no worker exists to observe the request,
  including a row created before its thread started.

Repeated cancellation while `cancelling` is idempotent and returns the current
status.

Cancellation targets workers hosted by the backend process. The ops CLI and the
Web UI both create and cancel runs through this API, so no second process owns a
live worker. If a `running` row has no worker after a backend restart, startup
recovery marks it `failed` instead of pretending it was cancelled.

## Runner lifecycle

Each `SimRunner` owns a `threading.Event`. `cancel` sets the event before or
while the worker runs. The worker checks it:

1. before promoting itself to `running`;
2. before each trading cycle;
3. while persona signal work is being prepared, before new work is submitted
   and before results are applied;
4. inside `run_cycle` after signals, immediately before order execution, and
   after execution before the cycle record is returned.

`SimulationCancelled` is handled separately from failures. It records
`status=cancelled`, a UTC completion timestamp, and the last persisted NAV, but
does not write a failed cycle audit. The current uncommitted cycle is discarded
because all broker mutations are in memory until `persist_completed_cycle`.

## Restart recovery

Startup recovery already fails rows that were `running` without a surviving
worker. A row left in `cancelling` has the same process-local limitation and is
therefore marked `cancelled` rather than left active forever. Pending rows stay
reserved for AIHF-020.

## Frontend

The Running view shows a Cancel run action for `pending` and `running`, disables
it while `cancelling`, and keeps polling until `completed`, `failed`, or
`cancelled`. History also exposes cancellation for active rows. Status text and
types are extended without changing result rendering; a cancelled run may show
the partial NAV curve already persisted.
