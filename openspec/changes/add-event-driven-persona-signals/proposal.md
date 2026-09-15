# Proposal: Event-Driven Persona Signals

## Problem

Historical simulations currently ask every LLM persona for every tradeable
ticker on every cycle. Prompt caching avoids some remote calls, but there is
no explicit effective-opinion state, event provenance, expiry policy, or safe
fallback when an event-triggered refresh fails.

## Change

- Persist run-scoped effective persona state.
- Refresh personas only for bootstrap, universe entry, new filings,
  actionable Yahoo earnings, material valuation changes, maximum age, or a
  due retry.
- Reuse valid opinions between events and preserve them across transient
  refresh failures.
- Materialize complete daily signals before the existing deterministic
  portfolio, risk, and T/T+1 execution pipeline.
- Expose event-aware call estimates and decision-audit provenance.

## Compatibility

Existing Fund YAML, simulation request fields, result endpoints, prompt cache,
NAV/trade persistence, and non-simulation `run_cycle` callers remain valid.
Old simulations have no persona policy/state and continue to render normally.

## Non-goals

- Cross-run persona-state reuse.
- Per-persona event mappings, automatic provider fallback, or SSE streaming.
- Security catalog and batch cache UX (Workstream 5).
