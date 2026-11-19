# Handoff: Surface Runtime Status UI

## Implemented

- `simulationApi.getSystemStatus()` exposes a typed view of the existing
  `/dashboard/system/status` response.
- `RuntimeStatusPanel` shows startup recovery counts and timestamp, aggregate
  simulation statuses, and process-local cache-job counts.
- The panel handles initial loading, request failure with a retained snapshot,
  retry/manual refresh, and inactive-page rendering without fetching.
- Component tests cover loading, populated counts, failed refresh plus retry,
  and inactive behavior. Workspace tests provide a deterministic status mock.

## Verification

- Focused runtime-status test: 3 passed.
- Frontend: 35 tests passed; lint and production build passed.
- Backend regression: 431 passed, 39 deselected.
- Self-review found no critical or major issues. The first
  `codex exec review --uncommitted` attempt could not reach its OpenAI
  transport; the Sub2API fallback completed with no actionable findings.

## Follow-up

- The panel is snapshot-based and does not poll. Users can refresh it manually
  or by changing the workspace revision.
- No schema, backend, simulation, cache, or retention behavior changed.
