# Proposal: Recover Stale Runtime State

## Why

Simulation runners and cache jobs are process-local. A backend restart during a
run can therefore leave the persisted `sim_run.status` at `running` even though
no worker exists. The dashboard then reports a permanently active simulation,
and operators have no concise way to distinguish an interrupted run from a live
one. Cache jobs already disappear with the process, but their cleanup contract is
implicit and untested.

## What Changes

- On backend startup, mark persisted `running` simulations as `failed` with a
  restart-specific error message and completion timestamp.
- Remove recovered simulations from the process-local runner registry and make
  repeated recovery idempotent.
- Mark any active process-local cache jobs as failed during startup recovery and
  request cancellation so they cannot continue reporting as live work.
- Expose the latest startup recovery summary and current simulation/cache status
  counts at `GET /dashboard/system/status`.
- Add deterministic tests for direct recovery and the FastAPI lifespan path.

## Compatibility

The change is additive: no schema migration is required, terminal simulation
rows are not modified, and existing simulation/cache endpoints keep their shape.
Interrupted simulations become explicitly failed rather than resumable; resuming
from a partially completed book remains AIHF-019.

## Non-goals

- Persisting cache jobs across process restarts.
- Resuming an interrupted simulation from its last committed cycle.
- Automatically retrying failed simulations.
