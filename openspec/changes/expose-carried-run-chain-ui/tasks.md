# Tasks

- [x] 1. Add failing workspace tests for continuing a completed run, carried
  preflight/run payloads, the review summary, cancelling a continuation, and
  parent/child lineage.
- [x] 2. Extend the frontend API types for the carried-book preflight response,
  run summaries, and status lineage.
- [x] 3. Add a failing backend regression test and expose each run's final
  `valuation_date` in `list_sim_runs` so the child starts on the actual NAV
  date rather than the requested end date.
- [x] 4. Implement history continuation, parent selection state, inherited form
  values, valuation-date handling, review copy, and lineage rendering.
- [x] 5. Run focused and full frontend verification plus backend regression
  tests.
- [x] 6. Self-review, update the backlog/handoff, and write the Chinese daily
  report.
