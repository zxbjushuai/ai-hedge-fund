# Handoff: US Security Catalog and Batch Cache

## Status

Implementation complete in the current uncommitted `zxb_dev` worktree.

## Decisions

- US only in this workstream; HK and CN are typed TODO adapters.
- Nasdaq Trader supplies the current catalog; Yahoo supplies data behind the US adapter.
- New price rows are raw and carry adjusted close plus corporate actions.
- Existing rows are `legacy_unknown` and must be refreshed before a new simulation.
- Cache jobs are in-memory and default to prices only.
- Simulation ticker request fields remain compatible.

## Implemented

- Current Nasdaq Trader catalog, search/filter APIs, inactive retention, saved universes, and a shared cache/simulation selector.
- Market-level polymorphism with a Yahoo-backed US adapter and explicit unsupported HK/CN TODO adapters.
- Raw Yahoo OHLCV, adjusted close, dividends, splits, provenance, coverage, categorized failures, batch download, fallback retry, and bounded background jobs.
- Corporate-action application before execution-day orders, atomic audit persistence, and adjusted-close benchmark NAV.
- Legacy synchronous cache API compatibility and legacy price-mode migration.
- Manual-review UX refinements: exact filtered selections are materialized as JSON ID arrays, directory filters use typed controls, pagination supports size/jump navigation, selected securities are collapsible/searchable, and saved universes are presented as reusable stock lists.
- Paginated cached-security inventory with search/status/mode/sort controls and lazy per-security detail for all effective prices, financial periods, earnings, coverage history, and an SVG raw/adjusted-close chart.

## Database Changes

- Added `security`, `saved_universe`, `saved_universe_member`, `cache_coverage`, and `sim_corporate_action`.
- Added nullable/additive price columns for adjusted close, dividends, split ratio, source, price mode, and update timestamp.
- Existing database rows become `legacy_unknown`; new ORM rows and Yahoo fetches are raw. No cache row is deleted by migration.

## Validation

- `poetry run pytest v2/ app/backend/ -q`: 230 passed, 39 deselected.
- Targeted catalog, migration, batch-job, corporate-action, route, and atomic-persistence tests: 29 passed, 1 live test deselected.
- New Python modules pass focused Flake8 (repository line-length rule excluded to match the existing code style).
- `poetry run pytest -m live v2/data/test_us_market.py -q`: 1 passed against live Nasdaq/Yahoo, including a two-symbol Yahoo batch.
- `openspec validate add-security-catalog-and-batch-cache --strict`: passed.
- `npm run build`: passed with existing bundle/font/source-map warnings.
- Modified frontend files pass focused ESLint with zero warnings.
- Full frontend lint remains blocked by 235 errors and 13 warnings in unrelated existing files.

## Known Limitations

- Catalog membership is current, not point-in-time.
- Jobs are in memory and do not recover after restart; committed cache rows remain.
- Yahoo filing dates may still be estimated at report period plus 45 days.
- Corporate-action cash-in-lieu uses the effective-day raw open and ignores taxes.
- HK/CN are intentionally unavailable.

## Stable Contract

- New simulations require raw universe prices and raw benchmark rows with adjusted close.
- Execution and valuation use raw prices; benchmark comparison uses adjusted close.
- Cache jobs default to prices and may optionally request metrics and earnings.
- Existing simulation requests still carry a normalized ticker list; selecting a saved universe resolves to that list before starting the run.
- `Select filtered` retains literal selection semantics: the frontend receives every matching ID, and manual deselection removes IDs from that concrete array. Selection requests are not represented as filter tokens.

## Git State

- No commit created by this implementation.
