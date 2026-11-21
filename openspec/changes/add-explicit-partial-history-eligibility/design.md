# Design: explicit partial-history eligibility

## Context

`build_snapshot` raises `InsufficientData` when fewer than `MIN_PERIODS` filed
metrics are visible. `PersonaSignalEngine` catches that exception and records a
typed abstention, while preflight and the frontend use a separate hard-coded
four-period warning. This is safe by default but hides the policy decision from
the mandate and prevents an operator from admitting a well-covered newly listed
security without changing code.

## Decision

Extend `PersonaRefreshPolicy` with `minimum_history_periods: int = 4`
(`ge=1`, `le=20`). The policy is already persisted on each `sim_run`, exposed by
preflight, and attached to the fund spec, so no migration is needed.

`build_snapshot` accepts an optional threshold, defaulting to the existing
four-period constant. `InsufficientData` carries `available_periods` and
`required_periods` so the abstention message is actionable. The persona engine
passes the configured threshold to the agent snapshot builder. The event
schedule estimate and cached-data validation use the same threshold, keeping
preflight and runtime consistent.

The default remains four. Lowering the threshold does not bypass point-in-time
visibility: the data client still filters by `filing_date <= as_of`, and the
resulting snapshot contains only periods filed by the signal date. Independent
quant models remain unaffected.

## Alternatives Considered

- **Always require four periods:** safe but does not implement an eligibility
  decision for newly listed names.
- **Always allow one period:** silently weakens every mandate and makes the
  abstention behavior dependent on data coverage rather than an explicit choice.
- **Infer eligibility from listing age:** listing dates are not available in the
  current point-in-time cache contract and would introduce another data source.

## Risks

- A mandate that sets a low threshold asks personas to reason from sparse
  history. This is visible in the persisted policy and preflight UI, and should
  be treated as a research choice rather than a default.
- Prompt-cache keys include the snapshot content, so changing the threshold can
  legitimately produce a different prompt and a new LLM call.
