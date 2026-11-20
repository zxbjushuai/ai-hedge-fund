# Handoff: fix persona bootstrap retry identity

Status: completed 2026-11-20.

Backlog item: AIHF-012.

## Implemented

- Added `initial_refresh_reason` to run-scoped `_PersonaState`.
- The first refresh evaluation with sufficient snapshot data records `bootstrap`
  in cycle 1 or `universe_entry` later, and subsequent no-signal evaluations
  reuse that reason.
- A failed bootstrap now keeps the same event fingerprint until the configured
  retry cycle or a genuinely different event.
- Insufficient-data evaluations do not initialize the reason, so a security that
  becomes eligible later still enters as `universe_entry`.

## Validation

- Code commit: `dd67319` `fix(simulation): preserve persona bootstrap retry identity`.
- Focused regression file: `3 passed` for the new retry/backoff, non-retryable,
  and later-entry cases.
- Backend: `.venv/bin/python -m pytest research_app/backend hedge_fund -q` ->
  `434 passed, 39 deselected`.
- Frontend: `35 passed`; ESLint and production build passed.
- Built-in review found no actionable issues; manual `aihf-code-review` verdict:
  APPROVE. Evidence: `logs/agent/review-20261120-aihf012.md`.
- Targeted flake8 still reports two E3xx findings that also exist at the base
  tag; repository-wide Black/isort drift is pre-existing and was not rewritten.

## Residual

- `initial_refresh_reason` is engine-local and derived. Durable restoration of
  this identity remains part of AIHF-019 resume work.
