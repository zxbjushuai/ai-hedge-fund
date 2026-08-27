## Why

The v2 simulation currently loses PEAD whenever Yahoo omits analyst EPS estimates or surprise values. It also reconstructs valuation from every daily close and embeds the exact values in a prompt whose cache was designed around quarterly filings, turning an intended filing-level LLM analysis into a daily paid call. Finally, ticker selection and synchronous cache fetching do not scale beyond a small manually entered universe.

## What Changes

The work is delivered in three ordered phases:

1. **Signal correctness:** use Yahoo's point-in-time actual-versus-analyst-estimate EPS surprise when complete, keep PEAD neutral when it is genuinely missing, freeze the fundamental LLM valuation at the filing-date close, and estimate cold-cache calls from distinct filing snapshots rather than trading days.
2. **Event-driven LLM:** persist the latest valid persona signal per ticker, refresh it only for defined events, and materialize a complete daily signal set by reusing still-valid opinions for non-event tickers.
3. **Scalable universe and cache UX:** maintain a local security catalog, provide searchable multi-selection, and fetch historical data through bounded background batch jobs with progress and retry support.

## Capabilities

### New Capabilities

- `event-driven-llm`: Stateful, point-in-time persona refresh and reuse across a multi-ticker universe.
- `security-universe`: Locally synchronized searchable securities and bounded batch cache jobs.

### Modified Capabilities

- `data-cache`: Yahoo earnings history preserves complete numeric surprises and represents missing EPS inputs explicitly without fabricating a PEAD event.
- `simulation-engine`: Fundamental prompts are stable between filings and preflight estimates filing-level cold calls.

## Non-Goals

- Phase 1 does not implement persistent persona state or valuation-triggered refresh; those belong to Phase 2.
- Phase 1 does not implement the security catalog or batch-job UI; those belong to Phase 3.
- The work does not make LLMs place orders directly or bypass deterministic portfolio and risk logic.

## Impact

- **Phase 1:** `v2/data/`, `v2/features/`, `v2/simulation/`, dashboard cache/preflight routes, environment documentation, and tests.
- **Phase 2:** persona signal persistence, event detection, pipeline signal materialization, and simulation usage estimates.
- **Phase 3:** new security/job tables, Yahoo/market-directory synchronization, cache worker APIs, and React selectors/progress UI.
