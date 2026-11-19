# Proposal: Surface Runtime Status UI

## Why

The backend exposes startup recovery, persisted simulation counts, and
process-local cache-job state at `GET /dashboard/system/status`, but the Web UI
does not consume it. After a restart, users can see completed, failed, or stale
run rows without any explanation that startup recovery ran or whether cache jobs
still exist in the current process.

## What Changes

- Add a typed frontend API method for the system status endpoint.
- Show a compact runtime-status panel on the Simulation page.
- Display startup recovery counts and timestamp, current active/failed
  simulation counts, and active/total cache-job counts.
- Provide loading, empty/error, and manual refresh states with accessible status
  and alert roles.
- Add component tests for loading, populated data, errors, retry, and inactive
  rendering.

## Compatibility

This is a read-only frontend change. The backend response shape and simulation
semantics are unchanged. No database migration or service restart is required.

## Non-goals

- Adding polling or live log streaming.
- Automatically retrying, resuming, or cancelling recovered simulations.
- Changing startup recovery behavior, cache-job lifecycle, or retention.
