# Handoff: bounded lineage lookup

## Summary

The Simulation result panel now resolves a run's parent and children by id
through `GET /dashboard/sim/lineage/{sim_id}`, so chains remain navigable when
one side falls outside the 50-newest history payload.

`get_sim_lineage()` reuses `_run_summaries()` (extracted from
`list_sim_runs()`), resolves the parent directly, and caps children at 50 with
an explicit `children_truncated` flag. History rows still use the visible-window
map and keep their existing `From Sim #N` links.

## Files

- `hedge_fund/simulation/runner.py`
- `hedge_fund/simulation/test_historical_semantics.py`
- `research_app/backend/routes/simulations.py`
- `research_app/backend/test_sim_lineage_api.py`
- `research_app/frontend/src/services/simulation-api.ts`
- `research_app/frontend/src/components/backtest/simulation-workspace.tsx`
- `research_app/frontend/src/components/backtest/simulation-workspace.test.tsx`

## Verification

- Backend: `.venv/bin/python -m pytest research_app/backend hedge_fund -q`.
- Frontend: test, lint, build commands from `AGENTS.md`.

No simulation run was needed: this is a read-only navigation feature and does
not touch strategy, data, or performance behavior.

## Known limitations

- Children are capped at 50 per run; the response reports truncation rather
  than paginating.
- The history table still shows only the 50 newest runs; older runs are reached
  through lineage links.
- Repo-wide `black`/`isort` debt remains at the base commit; the changed-file
  test suite is the gate.
