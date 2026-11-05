# Frontend redesign handoff

Implementation complete (2026-09-23). Backend contracts, schemas and core simulation code
are unchanged by this change. Pre-existing provider database relocation edits and
the untracked research_app/README_ZH.md belong to earlier/user work and are preserved.

Implemented cached-stock selection, coverage analysis/timeline, inline review,
explicit cost confirmation, run tracking/history, Data prefill and shared light/
dark styling. Vitest/jsdom/testing-library are development-only dependencies.
Existing SVG results and audit are reused; no chart library was added.

Final verification: 22 frontend tests pass, TypeScript/Vite build passes and
ESLint has zero warnings. Existing stale Browserslist warning remains. Missing
Geist font imports and legacy Flow CSS were replaced by the workbench stylesheet.

Chrome DevTools verified all three pages, 1440px desktop and 390px mobile (no
document-level horizontal overflow), dark appearance, cached A selection and
common-range initialization, Data prefilled tickers/dates, and sim9 results plus
Decision Audit. No console errors/warnings in the checked flows. Existing NAV
chart end labels now anchor inward to avoid clipping; chart calculations unchanged.

Browser fetch interception supplied offline preflight/run/status responses:
Review made zero run calls; warning acknowledgement was required; two rapid clicks
produced exactly one run request with confirm_cost=true and the existing fields.
The fake run completed. Interceptors and fake UI state were cleared afterward.
Real Network requests observed were existing read endpoints (200). No live
preflight, inference, provider sync or market-data fetch was initiated. User's
running services were not restarted. No credential contents were exposed.

Validation commands from research_app/frontend:

```
npm test
npm run build
npm run lint
```

Tests cover disjoint/common histories, weekend boundaries, gaps and mixed modes,
missing benchmark/adjusted close, point-in-time financial warnings, saved-universe
missing members, manual date preservation, bounded concurrency, stale generation
and preflight responses, failure retries, explicit confirmation/single submission,
active run across hidden pages, Data prefill and legacy nullable result fields.

Frontend-only work: no backend regression suite rerun for this change. Prior
backend edits visible in git status predate this task; they were not changed.

See design.md for the no-backend-change limitations, especially benchmark calendar
completeness and price-filter pagination. No commit/push.
