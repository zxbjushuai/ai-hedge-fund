# Agent backlog

One item per day. Pick the highest-priority unfinished item that can be completed
and verified in one run. Update status with the date and commit hash.

## Current behavior

- There is **no scheduled data/simulation timer**. The agent runs
  `scripts/aihf_ops.py` on demand: `fetch`, `backtest`, `simulate`,
  `cumulative`, `continue`, `analyze`.
- `backtest` = historical range for strategy optimization.
- `cumulative` = interim continuous window from a fixed start (recomputed).
- `continue` = carried-book daily paper trading from a completed parent run.
- `scripts/daily-pipeline.py` is a legacy/manual rolling-window tool (independent
  runs); it is not scheduled.
- Backend startup fails stale `running` simulations and reports recovery/runtime
  counts at `GET /dashboard/system/status`; cache jobs remain process-local.

## P0 — daily pipeline and reliability

### AIHF-001 — Daily data + simulation pipeline
Status: done (2026-11-05, `17b97a0`; verified with AAPL/MSFT/SPY, sim #12 direct and sim #13 via Sub2API). Scheduled timer disabled by design; kept as a manual tool behind `scripts/aihf_ops.py`.
Goal: implement `scripts/daily-pipeline.py` that syncs/pulls US prices for the
configured universe, waits for the cache job, preflights, runs a simulation with
`llm_connection_id=1` / `deepseek-v4.1-flash`, polls to completion, and writes
`logs/daily/YYYY-MM-DD.json` + a short Markdown summary.
Acceptance: a manual end-to-end run succeeds; `aihf-daily.timer` enabled; failures
exit non-zero and are visible in logs.

### AIHF-002 — Incremental cache updates
Status: done (2026-11-06, a9479be; 343 tests)
Goal: stop refetching the full requested range when only the end date changes.
Fetch the gap since the last `actual_end` per ticker/kind and update coverage.
Acceptance: two consecutive daily runs fetch only the new sessions; tests cover
gap detection and no-data days.

### AIHF-003 — Stale run/job recovery
Status: done (2026-11-08, `4f0148b`; backend 347 tests, frontend 28 tests + lint/build). Startup recovery fails orphaned running simulations, clears their runner registry entries, cancels process-local cache jobs, and exposes `/dashboard/system/status`.
Goal: on backend startup, mark orphaned `sim_run.status='running'` rows as failed
or resumable; restore or clean in-memory cache jobs. Add a status endpoint/field.
Acceptance: restart during a run no longer leaves a permanently running row;
tests cover recovery.
Follow-up: pending rows created before the worker starts are tracked in AIHF-020;
the Web UI does not yet consume the new status endpoint (AIHF-021).

### AIHF-004 — Tests for the daily path
Status: done (2026-11-10, `108b3c3`; backend 348 tests, frontend 28 tests + lint/build). Adds a deterministic no-network integration test spanning catalog selection, cache-job prices, preflight, background simulation, status/result, benchmark NAV, trade isolation, and cycle audit persistence.
Goal: deterministic tests for catalog → cache job → preflight → run → result,
using fixtures/mocks (no network).
Acceptance: tests run in CI/locally with `-m 'not live'`.

## P1 — correctness and operations

### AIHF-016 — Carried-book daily simulation (paper trading)
Status: done (2026-11-05, `1173976`; verified run #15 → #16 carried AAPL/MSFT/SPY final cash and positions).
Goal: make the daily run continue from the previous run instead of starting
fresh. Seed the next run's broker with the prior run's closing cash/positions
(including corporate actions), advance one trading day, and persist a
continuous NAV/position history.
Acceptance: a multi-day chain of runs shows carried cash/positions; NAV
continuity tests; no lookahead; docs updated.
Notes: ROADMAP "persistent ledger read half"; `nav_snapshot`,
`position_snapshot`, and `sim_*` tables already stored state; the completed
change seeds `SimBroker` only when `carried_from_run_id` is explicitly set.
Follow-up: expose the chain in the Web UI (AIHF-018) and support resuming an
interrupted run from its last committed cycle (AIHF-019).

### AIHF-017 — Backtest / optimization harness
Status: done (2026-11-10, `60354fe`; backend 366 tests, frontend 28 tests + lint/build). Adds a reproducible JSON matrix command with API-aligned validation, persisted per-run metrics, ranked Markdown comparison, and safe stop behavior for ambiguous submission or lost monitoring.
Goal: make historical backtests first-class: run a matrix of date ranges,
universes, personas/risk settings, persist metrics, compare runs, and feed the
best candidates into the agent's decisions. `scripts/aihf_ops.py
backtest/analyze` is the starting point.
Acceptance: reproducible command; metrics persisted; comparison report; tests.
Follow-up: persona/risk axes still require per-run simulation API support; the
current matrix varies dates, universes, connection/model, capital, concurrency,
and benchmark.

### AIHF-005 — Provider bootstrap script
Status: open
Goal: idempotent script/API flow to create/update the `opencode_go` connection
and `deepseek-v4.1-flash` model without manual DB edits; document key rotation.
Acceptance: running it on a fresh `providers.db` yields a usable connection.

### AIHF-006 — Simulation cancel/resume
Status: open
Goal: add cancellation and optional resume for simulations; clean up threads and
status safely.
Acceptance: API + UI; tests for cancel during signals/execution.

### AIHF-007 — Auth/reverse-proxy hardening
Status: open
Goal: document and implement a safe remote access path (Caddy + Basic Auth or
Tailscale-only) without weakening localhost defaults.
Acceptance: no unauthenticated route exposed beyond localhost; docs updated.

### AIHF-008 — Filing-date data quality (PEAD)
Status: open
Goal: replace estimated `report_period + 45d` filing visibility with
source-aware timestamps where available; abstain when uncertain.
Acceptance: no lookahead; fixtures for before/after-market releases; PEAD
behavior documented.

### AIHF-009 — Cache/job retention and observability
Status: open
Goal: retention policy for simulation JSONL/logs, heartbeat/metrics for the
daily pipeline, and a simple failure summary.
Acceptance: disk usage bounded; last-run status visible.

## P2 — scale and features

### AIHF-010 — Raise the 50-ticker simulation cap
Status: open
Goal: support larger universes with batching and cost controls.
Acceptance: schema/engine/UI updated; performance measured; tests.

### AIHF-011 — Universe screening
Status: open
Goal: deterministic liquidity/eligibility filter (and optional top-K) to replace
the ad-hoc cached universe.
Acceptance: reproducible universe; documented; tests.

### AIHF-012 — Persona bootstrap retry defect
Status: open
Goal: fix cycle-2 relabeling that bypasses retry backoff; add regression test.
Files: `hedge_fund/simulation/persona_state.py`.

### AIHF-013 — Newly listed / partial-history eligibility
Status: open
Goal: define and implement eligibility when fewer than four quarters exist;
avoid silent abstention surprises.
Acceptance: docs + tests.

### AIHF-018 — Carried-run chain UI
Status: open
Goal: expose `carried_from_run_id` in the Web simulation form, offer continuing
a selected completed run, and show parent/child links in history.
Acceptance: users can create and identify carried runs without the ops CLI;
tests cover the form/preflight/result states.

### AIHF-019 — Resume interrupted simulation
Status: open
Goal: resume an interrupted or orphaned run from its last committed cycle with
its exact book, rather than only starting a child from a completed parent.
Acceptance: restart-safe recovery with no duplicate trades or NAV points;
tests cover resume after partial completion.

### AIHF-014 — Production frontend serving
Status: open
Goal: serve the built frontend and API from one origin (Caddy) as an optional
deployment, keeping the Vite dev setup for development.
Acceptance: documented and tested; CORS unchanged for dev.

### AIHF-015 — Upstream sync report
Status: open
Goal: daily check of `origin/main` (upstream) and a report of new commits and
conflicts; never auto-merge into `agent/daily`.
Acceptance: report section in the daily doc; manual merge workflow documented.

### AIHF-020 — Recover pre-start pending simulations
Status: open
Goal: handle `sim_run.status='pending'` rows left by a crash after row creation
but before the background runner starts.
Acceptance: startup recovery fails or resumes pending rows safely; regression
test covers the create-before-start crash window.

### AIHF-021 — Surface runtime recovery in the Web UI
Status: open
Goal: display startup recovery counts and current running/failed simulation plus
cache-job status from `/dashboard/system/status`.
Acceptance: status is visible with loading/error states; frontend tests cover it.
