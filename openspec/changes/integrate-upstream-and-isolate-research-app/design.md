# Design

## Boundaries

research_app owns Web startup, HTTP routes, managed connection persistence and React UI. Phase 1 retains v2 imports; phase 2 moves the shared core to hedge_fund without retaining duplicate cores. Existing functions and UI components are extracted mechanically, not reimplemented. The original app remains a rollback entrypoint until deletion approval.

## Persistence

Keep FUND_DB_PATH and FUND_SPEC_PATH. Add LLM_DB_PATH and PROMPT_CACHE_DIR; relative settings resolve from the repository root, never the launch directory. Defaults point at existing fund.db, app/backend/hedge_fund.db, v2/funds/example.yaml and .v2_cache/llm during phase 1. No live database migration during fixture validation. SQLite backup API captures both databases under ignored .v2_cache.

## Routes and UI

Reuse simulations, cache explorer, providers, audit and their dependency closure. New shell has Simulation, Data and Providers navigation. Preserve /dashboard request/response contracts. Extract catalog, universes, cache, providers and simulations routers. Legacy flow routes and scheduler status are absent from the new entrypoint.

## Merge decisions

Preserve T/T+1 semantics, local-only simulation data access, runtime credential snapshots, event-driven Persona state, atomic audit/NAV/fills/actions persistence. Upstream CLI/TUI retain their file receipts; no history import/export is promised. Keep necessary opt-in extension parameters on shared pipeline interfaces. Resolve lockfile from dependency declarations.

## Rollback

Keep zxb_dev at 5fca1b4 and original app code during phase 1. Switch entrypoints to roll back; databases retain their original locations. Before merge or obsolete-file removal, review exact deletion targets and obtain approval.

