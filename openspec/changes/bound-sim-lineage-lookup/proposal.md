# Proposal: Bounded lineage lookup beyond the history window

## Why

`list_sim_runs()` returns the 50 newest runs, and the Simulation workspace
derives parent/child links only from that payload. A run viewed by id can have
children older than the window, and a child's parent can fall out of the
window, leaving the result panel unable to show the complete chain without
growing the default history payload.

## What Changes

- Add `GET /dashboard/sim/lineage/{sim_id}` returning the run's parent and up
  to 50 children, resolved directly by id and independent of the history
  window.
- Refactor run summaries into one shared helper so window and lookup payloads
  stay identical.
- Fetch lineage on demand in the Simulation result panel, show loading/error
  states with retry, and fall back to the visible-window map while loading.
- Report `children_truncated` instead of returning an unbounded child list.
- Cover parent-outside-window, child-outside-window, bounded-children, unknown
  run, and UI lookup behavior with backend and component tests.

## Compatibility

The new endpoint is additive; `GET /dashboard/sim/runs` keeps its exact
payload and 50-run bound. No schema migration, data change, or service restart
is required.

## Non-goals

- Changing the history window size or paginating history.
- Resuming interrupted runs (AIHF-019).
- Changing carried-book validation or lineage persistence.

## Impact

- Backlog item: AIHF-023.
- Old chains remain navigable without increasing the default history payload.
