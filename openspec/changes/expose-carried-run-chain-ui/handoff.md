# Handoff: carried-run chain UI

## Summary

Simulation history now offers `Continue Sim #N` for completed runs whose closing
book is usable.  Selecting it preloads the parent universe, benchmark,
connection, model, inherited capital, and the parent's final valuation date;
preflight and run requests carry `carried_from_run_id`.  History and result
views show parent/child links, and review shows the backend's carried-book
summary.

The run-summary API gained two additive fields:

- `valuation_date`: the latest `SimNavSnapshot.cycle_date` for the run.
- `carryable`: `true` only when the run is completed with a final NAV, at least
  one NAV snapshot, and a completed cycle payload.

`valuation_date` is essential because a run's requested `end_date` can be later
than its last cached valuation.  `load_carried_book` requires the child start to
equal the actual final snapshot date, so the UI must not use `end_date`.

## Files

- `hedge_fund/simulation/runner.py` — `list_sim_runs` valuation/carryability.
- `hedge_fund/simulation/test_historical_semantics.py` — regression tests.
- `research_app/frontend/src/services/simulation-api.ts` — API types.
- `research_app/frontend/src/components/backtest/simulation-workspace.tsx` —
  continuation flow, inheritance, gating, banner, review summary, lineage.
- `research_app/frontend/src/components/backtest/simulation-workspace.test.tsx`
  — component coverage.

## Verification

- `.venv/bin/python -m pytest research_app/backend hedge_fund -q` → 443 passed.
- `npm --prefix research_app/frontend run test` → 41 passed.
- `npm --prefix research_app/frontend run lint` → clean.
- `npm --prefix research_app/frontend run build` → success.

No simulation or backtest run was needed: this change does not alter strategy,
data, or performance behavior.  It only exposes an existing carried-book API.

## Known limitations / follow-ups

- Lineage is derived from the 50 newest runs returned by `list_sim_runs`.
  Children of a parent outside that window are not linked in the UI.
- `carryable` is an optimistic pre-check (completed NAV snapshot + completed
  cycle payload).  Preflight remains authoritative for NAV/cash consistency and
  universe/benchmark matching.
- Resume of interrupted runs (AIHF-019) is out of scope.
- Repo-wide `black`/`flake8` checks already fail at the base commit; only the
  required pytest + frontend suite was used as the gate.

## Rollback

Revert the feature commit; the API fields are additive so older clients are
unaffected.  No schema migration, data reset, or service restart is required.
