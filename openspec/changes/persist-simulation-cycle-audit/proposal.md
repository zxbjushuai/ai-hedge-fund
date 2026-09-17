# Proposal: Persist Simulation Cycle Audit

## Why

Simulation results currently retain NAV and executed trades but discard the
`CycleRecord` that explains how each signal became a target, risk-adjusted
weight, order, fill, and position. LLM transport and response failures are also
represented as neutral abstentions, so an operational failure can be mistaken
for an investment opinion.

## What Changes

- Give every strategy signal a typed outcome: produced, abstained, or failed.
- Categorize insufficient data, authentication, rate-limit, timeout, transport,
  invalid-response, data-provider, and internal failures without persisting
  credentials or raw provider responses.
- Persist one complete serialized `CycleRecord` for every completed decision
  cycle, plus compact run/date/ticker indexes for drill-down.
- Persist a failed cycle attempt when execution stops before a complete record
  can be produced.
- Save a completed cycle, NAV snapshot, and fills in one database transaction.
- Add read-only APIs and a minimal Decision Audit view explaining each trade.

## Scope

This change implements Workstream 3 only. It preserves T signal / T+1 open
execution / T+1 close valuation, existing NAV and trade APIs, prompt caching,
and historical simulation compatibility. It does not implement event-driven
persona reuse, full relational signal normalization, streaming, or a general
observability platform.
