# Handoff: Protect Active Simulation Logs During Retention

## Implemented

- `scripts/aihf_retention.py` discovers `pending`, `running`, and `cancelling`
  IDs through a read-only SQLite connection and protects matching
  `simulations/sim-{id}.log` files during age and size-budget planning.
- `scripts/aihf_ops.py` resolves `FUND_DB_PATH` with the same repository `.env`,
  relative-path, home-directory, and absolute-path semantics as the backend. It
  re-reads active run IDs at apply time and aborts retention if state cannot be
  read.
- Plan JSON records the active IDs used for review; plan loading remains
  compatible with older plans that do not contain the field.
- `docs/agent/ops-retention.md` documents active-run protection and the
  apply-time recheck.

## Invariants

- `pending`, `running`, and `cancelling` simulation logs are never selected by a
  fresh retention plan.
- A saved plan is revalidated against current run state before deletion.
- Run-state reads use SQLite read-only mode and never modify `fund.db`.
- State-read failures abort retention rather than assuming no runs are active.
- Existing dry-run, plan-file approval, path, symlink, file-type, size, and mtime
  protections remain in force.

## Verification

- Focused: `pytest research_app/backend/test_ops_retention.py -q` -> 22 passed.
- Backend: `pytest research_app/backend hedge_fund -q` -> 429 passed,
  39 deselected.
- Frontend: 32 tests passed; lint and production build passed.
- Black, isort, and `git diff --check` passed for modified Python files.
- Initial `codex exec review --base backup-20261117-090503` found one P1 about
  loading `.env`/`~` consistently with the backend. Fixed with regression tests.
- Final review found no actionable regressions.

## Follow-up

- No new backlog item. Retention remains manual and still requires explicit
  approval of the saved plan before `--apply`.
- Feature commit: `97a6f88` (`fix(agent): protect active simulation logs from retention`).
