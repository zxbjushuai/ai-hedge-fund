# Design: Surface Runtime Status UI

## Placement

The panel belongs on the Simulation page, directly below the page heading and
before the New/Running/History views. All three tabs describe simulation work,
so a page-level summary remains visible regardless of the selected tab while the
Simulation page is active.

## Data flow

`simulationApi.getSystemStatus()` calls the existing
`/dashboard/system/status` endpoint and returns a narrow TypeScript interface.
`RuntimeStatusPanel` fetches when the page becomes active, when the workspace
revision changes, or when the user requests a refresh. Requests are ignored
after unmount or after a newer request supersedes them.

## Presentation

The summary uses three semantic groups:

- startup recovery: recovered, failed, cancelled, cache-job failures, and the
  last recovery timestamp;
- simulations: active statuses (`pending`, `running`, `cancelling`), failed,
  completed, and cancelled counts;
- cache jobs: active and total process-local jobs plus failed/partial counts.

The endpoint exposes aggregate counts rather than status rows or IDs, so the UI
must not imply a live worker exists merely because a persisted row is active.
Copy explicitly describes cache jobs as process-local.

## States

- Initial loading: `role="status"` message.
- Request failure: `role="alert"` message plus a retry action. A previous
  successful snapshot remains visible below the error.
- Success: semantic definition list with counts and recovery timestamp.
- Inactive page: no request is made and the panel renders nothing.

## Testing

Component tests mock the service and verify loading, populated copy, error plus
retry recovery, and inactive behavior. Existing workspace tests receive a
default status mock so unrelated simulation behavior remains deterministic.
