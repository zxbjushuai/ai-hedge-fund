## Context

`FundamentalsSnapshot` was designed so identical filed fundamentals render an identical prompt between filings. Historical simulation later added daily point-in-time P/E, P/B, and market-cap reconstruction to that same object. Because the prompt cache hashes the full rendered prompt, ordinary price movement now invalidates the cache every trading day.

Yahoo supplies reported EPS, analyst `EPS Estimate`, `Surprise(%)`, and the announcement timestamp for most actively traded stocks. Actual EPS alone cannot represent analyst surprise, so PEAD remains neutral when the estimate or numeric surprise is genuinely missing.

## Goals / Non-Goals

**Goals:**

- Restore filing-level prompt stability without using current valuation data in historical runs.
- Preserve valuation context by valuing the latest visible filing at its own filing-date close.
- Treat Yahoo as the sole EPS-surprise source for this phase.
- Keep missing surprise local to a ticker instead of fabricating a PEAD signal.
- Define, but do not yet implement, event-driven persona state and scalable security selection.

**Non-Goals for Phase 1:**

- Daily valuation-event refresh.
- Carry-forward persona state independent of prompt cache.
- Full-market catalog synchronization and cache job orchestration.

## Decisions

### 1. Yahoo-only earnings surprise

Yahoo is the sole earnings-surprise source in the simulation cache path. An event is actionable only when Yahoo supplies a numeric surprise percentage or both reported EPS and the contemporaneous analyst estimate. If those inputs are incomplete, the record may retain the available values but the ticker receives no PEAD view for that event. Missing PEAD never prevents other tickers or models from running.

**Rationale:** Live sampling found Yahoo complete for 188 of 200 recent quarters across 50 randomly selected high-volume stocks. Other free providers added almost no safely timestamped coverage and frequently used different GAAP/adjusted or analyst-consensus conventions. A local neutral result is safer than joining incompatible values or inventing an event date.

### 2. Explicit numeric surprise

`EarningsData` carries `eps_surprise_percent` in addition to the BEAT/MISS/MEET label. Cache persistence uses Yahoo's percentage when available and otherwise derives it from actual and estimated EPS. A label-only BEAT/MISS is not actionable because it cannot demonstrate the analyst estimate used; no directional sentinel is fabricated.

### 3. Filing-date valuation for the quarterly prompt

The latest visible fundamentals row is valued using the last close on or before its `filing_date`, not the simulation `as_of` close. The value is therefore point-in-time honest and stable until another filing becomes visible.

**Alternative rejected:** removing valuation entirely would make value personas reason without a price anchor. Exact daily valuation belongs in a separate market context introduced by Phase 2.

### 4. Filing-level preflight estimate

The cold-cache estimate counts one bootstrap prompt per ticker/persona plus each distinct filing date that becomes visible over signal dates. Duplicate use of the same persona across strategies counts once because the prompt cache is shared.

### 5. Phase 2 effective-signal contract

Event-driven execution will persist one effective state per `(ticker, persona)`. New filings, actionable earnings events, material valuation-bucket changes, universe entry, or maximum age may refresh it. On every cycle, event tickers contribute refreshed signals and non-event tickers contribute their last still-valid signals. Failed refreshes do not overwrite a valid prior opinion; absent or expired opinions abstain.

### 6. Phase 3 scope

A local security catalog will back search, filters, and multi-select. Historical caching will use bounded in-memory background jobs for the current single-machine simulation use case. Completed cached coverage is idempotent; process-restart recovery is intentionally deferred. Price batches and low-concurrency fundamentals/earnings fetches retain bounded backoff and expose failed tickers for manual retry.

## Risks / Trade-offs

- Filing-date valuation ignores price movement between filings until Phase 2 adds material valuation events.
- Yahoo is an unofficial upstream interface and can omit or temporarily fail to parse earnings rows; the cache response exposes this condition and PEAD remains neutral for affected ticker-events.
- EPS values may use GAAP or adjusted conventions; Phase 1 does not mix fields across providers or attempt to normalize those accounting bases.
- A current security catalog introduces survivorship bias for older backtests; point-in-time universe membership remains future work.
