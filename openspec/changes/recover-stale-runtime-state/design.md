# Design: Recover Stale Runtime State

## Startup sequence

The FastAPI lifespan initializes the fund database first. It then runs one
idempotent recovery pass before serving requests:

1. Select `sim_run` rows whose status is `running`.
2. Mark each row `failed`, record a UTC completion timestamp, and replace the
   error message with a bounded restart explanation.
3. Remove recovered ids from the in-memory runner registry.
4. Ask the process-local cache-job manager to fail and cancel pending, running,
   or cancelling jobs.
5. Store a startup recovery snapshot for status reporting.

A second recovery pass finds no active rows and changes nothing.

## Why failed rather than running

The backend cannot prove that a process-local thread survived a restart. Leaving
the row `running` is observably false. Marking it failed is safe and truthful;
resuming from the last committed cycle requires the distinct recovery machinery
planned in AIHF-019. The original `current_day`, NAV snapshots, trades, and cycle
audits remain available for diagnosis.

## Cache jobs

Cache jobs are in-memory by design. In a normal new process there are no prior
jobs to recover. The manager nevertheless has an explicit recovery operation so
an in-process lifespan restart, or a future persisted adapter, has the same
cleanup contract. Active jobs receive a failed status, a completion timestamp,
an error reason, and a cancellation signal.

## Observability

`GET /dashboard/system/status` returns:

- the latest startup recovery summary;
- simulation counts grouped by status;
- cache-job counts grouped by status.

The endpoint contains no database paths, provider credentials, or run payloads.
