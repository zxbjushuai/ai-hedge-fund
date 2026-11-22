# Design: carried-run chain UI

## Existing contract

`POST /dashboard/sim/preflight` and `/sim/run` already accept
`carried_from_run_id`. Preflight validates the parent and returns
`initial_capital` plus `carried_book` metadata. History and result payloads
already include `carried_from_run_id`. The child must start on the parent's
final valuation date, which the history summary exposes as `valuation_date`
(the latest NAV snapshot). This can precede the requested `end_date` when
cached trading data ends early.

## User flow

History rows for completed runs gain a `Continue` action. Selecting it:

1. Copies the parent universe, benchmark, connection, model, and final NAV into
   the New simulation form.
2. Records the parent run id and starts a fresh child date selection at the
   parent's final valuation date, falling back to `end_date` for older runs.
3. Shows a continuation banner identifying the parent and the fixed universe,
   benchmark, and inherited capital.
4. Includes `carried_from_run_id` in preflight and run requests; review shows
   the backend's carried-book summary.

The date picker still uses the existing cached-data coverage. A user chooses an
end date after the parent valuation date. A Cancel continuation action clears
the parent id and returns to a standalone simulation while keeping the visible
universe, benchmark, dates, capital, connection, and model.

## History and result lineage

History derives child links from the loaded run summaries. A child row shows
its parent, and a parent row lists direct children. Both are buttons that load
the corresponding result. The selected result shows its parent/child lineage as
plain text, using the same loaded summaries, so orphaned or old rows remain
safe when summaries are unavailable.

## Validation and failure behavior

The backend remains authoritative. Run summaries expose `carryable`, which is
true only for completed runs with a final NAV, at least one NAV snapshot, and a
completed cycle payload; the UI offers Continue only when it is true. Preflight
still re-validates the book and the existing error rendering covers stale cache,
NAV/cash inconsistency, or a mismatched parent. The UI never launches a run
after preflight failure. If the inherited universe has no common coverage, the
end date falls back to the benchmark's last cached session so the user still
has a usable range to edit. If a parent's saved connection/model is unavailable
in the current provider list, normal form validation blocks review until the
user fixes it.

## Alternatives considered

- Add a separate modal or carry-only page: unnecessary for one existing
  request field and would duplicate the simulation review flow.
- Infer lineage only from result payloads: history already has every run's
  parent id, so requiring a result fetch would add requests and empty states.
- Let the UI create the child with no date control: users need an explicit end
  date and coverage review before spending model calls.
