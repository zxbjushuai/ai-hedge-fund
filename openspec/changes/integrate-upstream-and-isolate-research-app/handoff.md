# Migration handoff

## Status

### Post-integration provider storage relocation

User stopped the backend and authorized relocation. SQLite backup API copied
`app/backend/hedge_fund.db` to `~/.hedge-fund/research/providers.db` without
overwriting a destination. Integrity and all table contents match (3 connections,
41 models, and legacy tables preserved). The old database remains a backup,
not an active synchronized copy. LLM_DB_PATH still overrides the new default.
Fund DB and prompt cache were not relocated. `.vite/` is now ignored.
Deletion of old app/src/v2 Python caches was blocked by execution policy; none
were removed. Old node_modules and other residual files were left untouched.

### Current delivery: stages 1–3 complete

- Authorized stage 1 checkpoint: `5b714d2`.
- Real merge: `5d1c480`, with upstream `fc1bf25` as a parent. No unmerged paths.
- One core namespace: `hedge_fund`; standalone Web: `research_app`.
- Stage 3 removed Flow/editor dependencies from frontend declarations/lock and
  unregistered the legacy static `/dashboard/llm/models` route. Existing helper
  code is retained internally for compatibility; it is not a public route.
- Preserved all OpenSpec history documents. Missing historical docs from the
  broad upstream-deletion comparison were restored from the checkpoint during
  final cleanup review; no history or acceptance evidence is intentionally lost.
- Fixed a duplicate index declaration in the preserved Alembic revision chain,
  without changing revision IDs; empty database upgrade twice passes.
- Final full suite: **296 passed, 39 live tests deselected, 71 dependency warnings**.
- Fresh temporary frontend directory: npm ci, build and zero-warning lint pass.
  No old Flow JS module is imported. Old unused local node_modules are not deleted.
- Chrome DevTools, on disposable database copies: three tabs render; sim8 result
  and Decision Audit load; connections/models/key masks display; cache search for
  AAPL and its historical detail open. No live model/data requests were made.
- Existing font-asset/Browserslist build warnings remain cosmetic and documented;
  visual redesign is not included. The missing favicon request is avoided.
- Existing DB filenames, legacy tables/IDs and API Key import history are retained.
  The application does not depend on old `app/` source even though its default
  LLM database file is still `app/backend/hedge_fund.db`.

### Remaining stage 4 gates

User confirmed sim9 ran successfully on 2026-09-17. Read-only verification of
fund.db confirms status completed, requested interval 2026-06-03 through
2026-09-16, 71 completed cycle records (no failed cycles), 72 NAV snapshots and
112 trade records. This closes the user-run simulation acceptance gate; it is
not a claim that every model response or investment decision was independently
audited. No additional live requests were initiated for this verification.
On 2026-09-17 the user authorized development-branch integration with a backup.
Created `zxb_dev_bak` at `5fca1b4` before modifying `zxb_dev`. Committed sim9
acceptance as `628f993`, then fast-forwarded `zxb_dev` to that migration checkpoint.
The upstream merge ancestry is preserved. Remote push remains unperformed.
All prior status notes below are historical, superseded by this section.

Current gate: user confirmed manual acceptance on 2026-09-17. Stage 0/1 acceptance
is complete, including the corrected split-sizing regression. The pending/manual
statements below are historical investigation notes. Stage 2 has not started;
checkpoint commit and exact deletion approvals are still required. Chrome DevTools
MCP setup is separate local tooling work, not evidence of automated UI acceptance.

### Follow-up verification

Final post-fix offline run: `poetry run pytest v2/ app/backend/ research_app/backend/
-q --disable-warnings` — **258 passed, 39 deselected, 580 warnings**.
No commit, deletion, upstream merge or original-database modification performed.

Latest update: user authorized the split fix. Git blame attributes the action-before-
cycle integration to custom Workstream 5 commit `5fca1b4`, not this migration.
Sizing now converts T marks into post-split share units, leaving analyst prices
and T+1 execution/closing marks untouched. Audit adds backward-compatible
`sizing_marks`; no schema change. The overdraft regression now passes. Additional
tests cover forward/reverse splits and fractional cash-in-lieu. The failure
description below is retained as investigation history, not current test status.

Integrated event/action fixture added: bootstrap → reuse → valuation refresh,
two fake calls, persisted persona state, split/dividend audit and exact NAV/fills.
It exposed a baseline split-sizing defect; see `split-sizing-blocker.md`.
The observational comparison passes, but the new no-overdraft acceptance assertion
fails intentionally on current production behavior. The earlier 253-pass result
predates this new test and must not be interpreted as current full acceptance.
No production simulation logic was altered to conceal the failure.

Launcher PowerShell syntax checked. Ports 8000/5173 were already occupied, so
existing user services were left untouched and actual Ctrl+C validation remains
manual. See `manual-acceptance.md` for the numbered checklist and isolated-data setup.
Stages 0/1 remain blocked from promotion, not completed. No merge/commit/deletion.

Stages 0/1 in progress on migration/upstream-web-isolation. Original zxb_dev remains at 5fca1b4. Upstream target fc1bf25 is fixed. No commits or deletions performed.

## Backup

Ignored .v2_cache/migration-20260917-phase0/ contains consistent fund.db/providers.db backups and manifest.json with hashes and table counts. Both integrity checks: ok. Simulation DB: 8 runs, 155 cycles, 253 NAV rows, 329 fills, 4444 price rows, 13241 securities. Provider DB: 2 connections, 41 model rows. Secrets are present only in the local DB backup, not in manifest or Git.

## Pending gates

## Implemented and verified

- Added standalone `research_app` backend, five extracted router modules and the
  existing simulation/data/provider frontend components under a simple new shell.
- Preserved `/dashboard/...` contracts and existing Alembic revision IDs. Old source
  remains deliberately present pending deletion approval; core remains `v2`.
- Stable root-relative FUND_DB_PATH / FUND_SPEC_PATH / LLM_DB_PATH /
  PROMPT_CACHE_DIR; copied startup script points at the new independent API.
- `poetry run pytest v2/ app/backend/ research_app/backend/ -q --disable-warnings`:
  253 passed, 39 deselected, 580 warnings (existing dependency deprecations).
- New frontend build passed; full new frontend ESLint passed with zero warnings.
  Build still reports pre-existing absent Geist font assets and stale Browserslist.
- Isolated startup twice and different-cwd path checks passed. The deterministic
  original runner fixture and new/old result/audit API comparison passed; frozen
  NAV/fill subset is in `research_app/backend/fixtures/migration-baseline.json`.
- Disposable copies of both backups passed reads for connections, selectable models,
  securities, universes, cached data, historical runs, sim8 result and cycle audit.
  No inference or network data fetch was performed, no original DB was modified.
- `poetry check` passes with existing Poetry metadata deprecation notices.

## Remaining before stage acceptance

- Stages 0/1 are **not yet fully accepted**: integrated event/action fixtures and
  the split-sizing fix are now implemented; browser interaction needs checking,
  and real Windows Ctrl+C/port release is unverified.
- Stage 1 imports no legacy backend at runtime; the parity test intentionally
  imports the old router until phase 2 replaces that test dependency.
- Frontend dependencies/CSS are intentionally retained for now; phase 3 prunes
  unused packages after approval. This is not a visual redesign.
- `deletion-candidates.md` lists exact tracked paths for the fixed upstream diff;
  it excludes local databases, keys and ignored data. Approval has not been given.
- Obtain a checkpoint commit authorization separately; no commit/merge/push has
  occurred. Do not start stage 2 while stage 1 acceptance is incomplete.

Stage 2 requires exact deletion-target approval before a real merge changes/removes existing files. Final Git commits/development branch integration/push remain subject to explicit authorization. Visual redesign is deferred.
