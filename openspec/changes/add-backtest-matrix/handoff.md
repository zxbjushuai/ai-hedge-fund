# Handoff: Reproducible Backtest Matrix

Added `aihf_ops.py matrix --spec <json>` as the first complete slice of AIHF-017.
The command loads shared defaults, validates every run against the simulation
API's ticker, benchmark, ten-year-range, capital, and concurrency constraints,
then executes variants sequentially through the existing cached-data
simulation path.

The checked-in example is `docs/agent/backtest-matrix.example.json`. Matrix and
run names are filename-safe, and simulation names use `<matrix>-<run>` within
the API's 100-character limit.

Each invocation writes two timestamped artifacts under `logs/ops/`:

- `matrix-<timestamp>-<name>.json`: source path, SHA-256 digest, normalized run
  parameters, full records or errors, extracted metrics, and `stopped_after`.
- `matrix-<timestamp>-<name>.md`: ranked comparison table, best excess return,
  and lowest drawdown.

Terminal preflight/setup failures are recorded and later variants continue.
Ambiguous submission, lost monitoring, or a missing result stop the matrix
before another paid run can overlap the uncertain one.

Verification:

- `.venv/bin/python -m pytest research_app/backend hedge_fund -q` — 366 passed,
  39 deselected.
- `npm --prefix research_app/frontend run test` — 28 passed.
- `npm --prefix research_app/frontend run lint` — clean.
- `npm --prefix research_app/frontend run build` — passed.
- Final independent review — no actionable regressions.

Committed as `60354fe`.
