# Proposal: Add Simulation Cancellation

## Why

A running simulation can consume provider capacity for many minutes, but the Web
dashboard has no way to stop it. The only current recovery path is to wait for
completion, let it fail, or restart the backend, which marks active runs failed
and loses useful progress information.

## What Changes

- Add `POST /dashboard/sim/{sim_id}/cancel` and a `SimRunner.cancel` contract.
- Represent an accepted request as `cancelling` and terminate cooperatively as
  `cancelled`, preserving completed cycles, NAV snapshots, and trades.
- Check cancellation before each cycle, during persona signal preparation, and
  before order execution so a cancelled request cannot create a new committed
  cycle.
- Add a Cancel button to the active-run and history views; polling treats
  `cancelled` as terminal and refreshes history.
- Count `cancelling` and `cancelled` in runtime status, and recover stale
  `cancelling` rows as `cancelled` on backend startup.
- Cover the runner, API contract, and UI behavior with deterministic tests.

## Compatibility

The change is additive. `sim_run` already stores status as free text, so no
migration is required. Completed, failed, and pending behavior remains the same.
Cancellation is cooperative: an inference request already in flight may finish,
but no later request or trade is started after cancellation is observed.

## Non-goals

- Resuming an interrupted run from its last committed cycle; that remains
  AIHF-019.
- Cancelling HTTP or provider requests at the transport layer.
- Changing cache-job cancellation or deleting any simulation history.
