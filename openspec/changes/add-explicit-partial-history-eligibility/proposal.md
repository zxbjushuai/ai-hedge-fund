# Add explicit partial-history eligibility

## Why

LLM personas currently require four visible filed TTM periods. Securities with
less history abstain, but the threshold is a module constant: operators cannot
deliberately admit a newly listed company, and the same warning appears whether
the configured policy is four periods or something else. AIHF-013 requires an
explicit eligibility policy so partial-history abstention is predictable rather
than surprising.

## What Changes

- Add `minimum_history_periods` to the run-scoped persona policy, defaulting to
  four and restricted to 1-20 periods.
- Make snapshot construction accept the configured threshold and report both the
  available and required counts when it abstains.
- Pass the policy through persona evaluation, cached-data preflight, and the
  event-schedule estimate.
- Surface the threshold in the Web preflight/results policy display.
- Document that the default remains conservative and lowering it is an explicit
  per-mandate eligibility decision.

## Impact

- Runtime behavior changes only when a mandate explicitly sets a non-default
  threshold.
- API response shape gains one numeric policy field; database schema is
  unchanged because the policy is already persisted as JSON.
- Backlog item: AIHF-013.
