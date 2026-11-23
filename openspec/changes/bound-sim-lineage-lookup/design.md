# Design: bounded lineage lookup

## Shape

`get_sim_lineage(db_path, sim_id, max_children=50)` loads the run by id, then:

1. Loads `carried_from_run_id` directly, so a parent outside the 50-newest
   window is still resolvable.
2. Queries children with `carried_from_run_id == sim_id`, newest first, limited
   to `max_children + 1` to detect truncation.
3. Reuses `_run_summaries()` so every summary has the same fields and
   `carryable` semantics as history.

The response is `{run_id, parent, children, children_truncated,
max_children}`. Unknown runs return `None` at the helper and 404 at the route.

## UI behavior

The result panel requests lineage when a run is selected. While the request is
in flight it keeps using the visible-window map; once lineage arrives it uses
the authoritative parent/children lists. Errors are non-blocking and offer a
retry. Children beyond the cap are labelled with the newest-N notice.

## Why bounded

Lineage is opt-in per selected run. The existing history payload is unchanged,
and a child list cannot grow without limit even for heavily chained runs.

## Determinism

Children are ordered by `created_at DESC, id DESC`. Tests set explicit
timestamps and assert both parent resolution across the window and truncation.
