# Handoff: add explicit partial-history eligibility

Status: completed 2026-11-21.

Backlog item: AIHF-013.

## Implemented

- Added `persona_refresh.minimum_history_periods` to the run-scoped mandate
  policy, defaulting to four filed TTM periods and validated to 1-20.
- Passed the configured threshold through `LLMAgent.build_snapshot`,
  `PersonaSignalEngine`, the event-schedule estimate, and cached-data preflight.
- Extended `InsufficientData` with available/required period counts and an
  actionable abstention message such as `only 3 filed periods (need 4)`.
- Surfaced the threshold in Web preflight/results policy text.
- Backfilled older persisted run policies with the four-period default when
  returned by status, result, and history APIs.
- Kept point-in-time semantics unchanged: metrics remain filtered by
  `filing_date <= as_of`, and the threshold is per mandate rather than per ticker.

## Validation

- Code commit: `620a139` `feat(simulation): make persona history eligibility explicit`.
- Focused regressions covered the default abstention, explicit lower threshold,
  preflight estimate/warning, policy validation, and legacy policy reads.
- Backend: `.venv/bin/python -m pytest research_app/backend hedge_fund -q` ->
  `440 passed, 39 deselected`.
- Frontend: `35 passed`; ESLint and production build passed.
- Built-in review found no actionable issues; manual `aihf-code-review` verdict:
  APPROVE. Evidence: `logs/agent/review-20261121-aihf013.md`.
- Repository-wide Black/isort drift and CRLF/LF mixed checkouts are pre-existing;
  no unrelated formatting rewrite was performed.

## Residual

- The frontend coverage helper still describes the default four-period policy
  generically; the authoritative configured threshold is shown in preflight.
- No simulation or backtest was run because this change affects eligibility
  semantics, not strategy parameters or expected performance.
