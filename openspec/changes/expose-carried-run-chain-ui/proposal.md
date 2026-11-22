# Proposal: Expose the carried-run chain in the Web UI

## Why

The backend can start a carried-book simulation and persists
`carried_from_run_id`, but the Web simulation workspace exposes neither the
carry input nor the parent/child relationship. Users must currently use
`scripts/aihf_ops.py continue`, and history provides no way to identify which
run supplied a child's book.

## What Changes

- Add a Continue action to completed runs in Simulation history.
- Prefill the child configuration from the selected parent and keep the parent
  universe, benchmark, and inherited capital visible before submission.
- Send `carried_from_run_id` through preflight and run requests, starting
  the child on the parent's final valuation date.
- Expose each run's final `valuation_date` and a `carryable` eligibility flag
  in the run-summary API so the UI does not confuse the requested `end_date`
  with the actual NAV date or offer a continuation that cannot load a book.
- Show the carried-book summary in review and parent/child lineage in history
  and result views.
- Add component tests for selecting a completed parent, preflight/run payloads,
  incompatible parent states, and lineage rendering.

## Compatibility

This is a UI change over the existing carried-book API plus one additive
run-summary field (`valuation_date`). Standalone simulations remain unchanged,
and no schema migration or service restart is required. The server remains
authoritative for parent completion, valuation date, universe, benchmark, and
book consistency.

## Non-goals

- Resuming an interrupted run (AIHF-019).
- Automatically scheduling chained runs.
- Changing carried-book calculations or persistence.
- Allowing a child to alter the parent universe or benchmark.

## Impact

- Backlog item: AIHF-018.
- Web simulations can create and inspect carried runs without the ops CLI.
