# Proposal: Add a Reproducible Backtest Matrix

## Why

`scripts/aihf_ops.py backtest` runs one implicit date range at a time. Comparing
strategy behavior across several windows or universes therefore requires ad-hoc
commands, manually retaining run IDs, and hand-building comparison tables. That
is error-prone and makes experimental provenance hard to reproduce.

## What Changes

- Add an `aihf_ops.py matrix --spec <json>` command.
- Accept a checked-in or operator-supplied JSON file containing shared defaults
  and an ordered list of named run variants.
- Validate the whole matrix before starting any paid simulation: required keys,
  duplicate names, dates, universe size, numeric limits, and filename-safe run
  names.
- Run variants sequentially through the existing simulation contract and persist
  one JSON record plus one ranked Markdown comparison report under `logs/ops/`.
- Continue after an individual run failure, persist the failure, and exit
  non-zero so the operator can diagnose without losing completed results.

## Non-goals

- Varying personas or risk settings, which the current simulation API does not
  expose per run.
- Automatic strategy selection or claims of statistical significance.
- A scheduler, UI, database schema, or changes to simulation semantics.
