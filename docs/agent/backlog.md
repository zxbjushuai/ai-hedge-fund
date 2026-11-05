# Agent backlog

One item per day. Pick the highest-priority unfinished item that can be completed
and verified in one run. Update status with the date and commit hash.

## P0 — daily pipeline and reliability

### AIHF-001 — Daily data + simulation pipeline
Status: done (2026-11-05, `17b97a0`; verified with AAPL/MSFT/SPY, sim #12)
Goal: implement `scripts/daily-pipeline.py` that syncs/pulls US prices for the
configured universe, waits for the cache job, preflights, runs a simulation with
`llm_connection_id=1` / `deepseek-v4.1-flash`, polls to completion, and writes
`logs/daily/YYYY-MM-DD.json` + a short Markdown summary.
Acceptance: a manual end-to-end run succeeds; `aihf-daily.timer` enabled; failures
exit non-zero and are visible in logs.

### AIHF-002 — Incremental cache updates
Status: open
Goal: stop refetching the full requested range when only the end date changes.
Fetch the gap since the last `actual_end` per ticker/kind and update coverage.
Acceptance: two consecutive daily runs fetch only the new sessions; tests cover
gap detection and no-data days.

### AIHF-003 — Stale run/job recovery
Status: open
Goal: on backend startup, mark orphaned `sim_run.status='running'` rows as failed
or resumable; restore or clean in-memory cache jobs. Add a status endpoint/field.
Acceptance: restart during a run no longer leaves a permanently running row;
tests cover recovery.

### AIHF-004 — Tests for the daily path
Status: open
Goal: deterministic tests for catalog → cache job → preflight → run → result,
using fixtures/mocks (no network).
Acceptance: tests run in CI/locally with `-m 'not live'`.

## P1 — correctness and operations

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
