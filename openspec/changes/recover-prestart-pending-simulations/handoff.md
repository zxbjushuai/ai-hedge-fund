# Handoff: Recover Pre-Start Pending Simulations

## Implemented

- `SimRunner.recover_orphaned_runs()` now selects `pending`, `running`, and
  `cancelling` rows. A recovered pending row becomes `failed` with a distinct
  restart message stating that no cycle ran, while the existing running and
  cancelling transitions are unchanged.
- The startup recovery report and runtime status counts therefore include
  recovered pre-start rows without an API shape change.
- `hedge_fund/simulation/test_recovery.py` covers the direct runner transition,
  preserved `current_day`, absent final NAV, and idempotency.
- `research_app/backend/test_startup_recovery.py` covers the real FastAPI
  lifespan and status/detail endpoints for a create-before-start pending row.

## Invariants

- Terminal simulation rows are never modified.
- Pending rows are recovered only during startup recovery, before the API serves
  requests; the current single-process worker registry cannot own them at that
  point.
- No NAV snapshot, trade, or cycle audit is fabricated for a run that never
  started.
- Resuming from a committed cycle remains AIHF-019.

## Verification

- Focused: `pytest hedge_fund/simulation/test_recovery.py
  research_app/backend/test_startup_recovery.py -q` -> 6 passed.
- Backend: `pytest research_app/backend hedge_fund -q` -> 431 passed,
  39 deselected.
- Frontend: 32 tests passed; lint and production build passed.
- `git diff --check` passed. `runner.py` and `test_recovery.py` already failed
  repository-wide Black/isort/flake8 checks at the base commit; this change did
  not reformat unrelated code.

## Follow-up

- No new backlog item. Recovery counts are still not surfaced in the Web UI;
  that is AIHF-021.
