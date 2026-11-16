# Handoff: Ops Retention and Observability

## Implemented

- `scripts/aihf_retention.py` provides a side-effect-free planner and a guarded
  apply helper for `logs/simulations`, `logs/ops`, and `logs/daily`.
- `scripts/aihf_ops.py` adds `retention` (dry-run by default, `--plan-file`,
  `--apply`, `--json`) and enriches `status` with simulation/cache counts,
  newest failure, startup recovery, and retention pressure.
- `docs/agent/ops-retention.md` documents inspection, cleanup, and safety.
- `research_app/backend/test_ops_retention.py` covers age pruning, newest-file
  protection, size budgets, the minimum-age floor, symlink/root rejection,
  changed-file revalidation, dry-run behavior, and status summaries.

## Invariants

- No file is deleted without `--apply --plan-file` and explicit operator
  approval of that saved dry-run target set.
- Apply never rescans; newly eligible files are not deleted until a new plan is
  reviewed. Plans from another root, schemas other than `aihf-retention-plan-v1`,
  duplicate entries, and unsafe paths are rejected.
- Only regular files in the three managed directories can be selected.
- The newest file in each managed directory is always retained.
- Age pruning uses `min(keep_days, min_age_days)`, so recent evidence survives
  even when `keep_days` is set below the minimum age.
- Budget pruning only selects files older than `min_age_days`.
- Apply re-checks containment, symlinks, file type, size, and `mtime_ns`; a
  changed file is skipped instead of deleted.
- `status` reports current managed-log pressure, not projected post-cleanup
  pressure.
- No API, database schema, or service change is required.

## Verification

- Focused: `pytest research_app/backend/test_ops_retention.py -q` -> 14 passed.
- Full backend/frontend suite and self-review results are recorded in the daily
  report and backlog entry for AIHF-009.
- No real cleanup was applied during development; the dry run found 23 managed
  files (458,817 B) and zero candidates.

## Follow-up

- Retention does not inspect `sim_run` rows, so `--apply` cannot yet exclude a
  log file that belongs to an active or pending simulation. The current guard is
  the dry-run-first workflow and explicit approval. A follow-up should join
  candidates to run state (suggested AIHF-022).
- Retention remains manual; it is not wired into the daily wrapper by design.
