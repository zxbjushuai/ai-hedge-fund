# Proposal: Test the Deterministic Daily Path

## Why

The research workspace exercises catalog selection, cache jobs, simulation
preflight, background execution, and result persistence as separate units. There
is no single deterministic regression test proving those contracts still compose
without network access or a live LLM. A break at a boundary could therefore pass
the focused suites while leaving the operator-facing daily path unusable.

## What Changes

- Add one backend integration test that seeds a security catalog and selects a
  ticker through the catalog route.
- Run the real cache-job manager against a mocked batch price adapter and assert
  complete price coverage for the ticker and benchmark.
- Run simulation preflight, start the real background runner with a deterministic
  price-momentum-only fund spec, and verify the persisted status and result.
- Keep all dates, prices, and cache responses fixed and local.

## Compatibility

No production behavior, API shape, schema, or simulation semantics change. The
test uses the existing local SQLite and cache-job contracts.

## Non-goals

- Live Yahoo or LLM calls.
- A production scheduler or carried-book continuation.
- Replacing the existing focused unit tests for any component.
