# Handoff: Add Simulation Cancellation

## Contract

- Endpoint: `POST /dashboard/sim/{sim_id}/cancel`
- Accepted status: `cancelling`
- Terminal status: `cancelled`
- No schema migration

## Invariants

- A cancelled run never commits a new cycle after cancellation is observed.
- Completed NAV snapshots and trades remain available for partial analysis.
- Cancellation is not a failure and must not create a failed cycle audit.
- In-flight provider work may complete; cancellation is cooperative.
- Resume from the last committed cycle is AIHF-019, not part of this change.
