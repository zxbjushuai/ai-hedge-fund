# Current Handoff

## Status

completed

## Scope

Workstream 2 only: explicit per-run provider/model selection, provider factory,
managed OpenAI/Anthropic connections, dynamic model discovery, response
normalization, persistence, and Web controls.

## Stable Inputs

- Workstream 1 is complete in `da62597`.
- Runtime universe and benchmark are explicit and persisted.
- Historical execution remains T signal / T+1 open / T+1 close.
- SQLite and the React/Vite plus FastAPI application remain authoritative.

## Non-goals

- SSE/token streaming.
- Per-persona models or automatic provider fallback.
- Complete LLM/cycle audit persistence.
- Event-driven persona refresh.

## Implemented

- Added a v2-owned provider/model registry and data-driven model catalog.
- Added one `make_llm(provider, model, credential)` factory covering Anthropic,
  OpenAI, DeepSeek, Google, xAI, Kimi, Groq, Ollama, ModelScope, and OpenRouter.
- Preserved `get_llm` and named provider helpers for non-Web compatibility.
- Normalized strings, single content blocks, lists of blocks, and object-style
  blocks while dropping reasoning, thinking, tool, and signature content.
- Added `provider:model` to prompt-cache identity and persisted prompt records.
- Added run-scoped LLM injection from `SimRunner` through `Fund` to every
  `LLMAgent`; quant models do not receive the client.
- Added multiple named OpenAI/Anthropic connections with independent Base URLs,
  write-only keys, enabled state, test status, and idempotent legacy-key import.
- Added remote model synchronization, availability tracking, enablement, and
  manual models. Failed synchronization preserves the previous cache.
- Added `llm_connection_id + model` simulation requests and immutable connection
  resolution. Old provider/model and environment callers remain compatible.
- Added an LLM Providers management page and two-stage connection/model picker.
  Other implemented transports remain in the registry but are not advertised
  by the managed connection UI.
- Fixed leaked fund-ledger Sessions in the dashboard polling endpoints. Repeated
  summary/trades/positions/NAV requests now release their SQLite connections,
  so cache and simulation endpoints cannot be starved by normal UI polling.
- Ported the current upstream registry direction, including Sonnet 5, Opus 5,
  Fable 5.1, GPT-5.6, and GPT-6 Astra, without merging upstream wholesale.

## Database Changes

- Added nullable `sim_run.llm_provider VARCHAR(32)`.
- Added nullable `sim_run.llm_model VARCHAR(200)`.
- Added nullable connection id, connection name, and Base URL snapshots to
  `sim_run`; no credential is copied.
- Added application-database connection and model-cache tables through an
  additive Alembic migration and startup-safe table creation.
- Migration is additive. Historical runs return null provider/model values and
  render as `N/A`.

## Concurrency Verification

`v2/simulation/test_llm_isolation.py` runs two real `SimRunner` instances in a
`ThreadPoolExecutor`. Their fake clients wait on the same `threading.Barrier(2)`
inside `complete`, forcing the calls to overlap. One run remains
`openai:gpt-test`, the other `anthropic:claude-test`; both persisted rows match,
and sentinel global environment settings remain unchanged.
Managed-client coverage additionally forces simultaneous construction with
different Base URLs and credentials and verifies that all four selected values
remain isolated.

## Validation

- `poetry run pytest v2/ app/backend/services/test_llm_provider_service.py`
  - 182 passed, 38 live tests deselected by project configuration.
- `npm.cmd run build` from `app/frontend`
  - passed; existing font, sourcemap, Browserslist, and bundle-size warnings remain.
- ESLint on all changed frontend files
  - passed with zero warnings.
- Repository-wide `npm run lint`
  - still fails on 248 pre-existing issues outside the changed files.
- Python compileall and `git diff --check`
  - passed; Git reports only the repository's LF-to-CRLF notices.
- Alembic upgrade from the previous `d5e78f9a1b2c` revision
  - passed against a temporary SQLite database and imported a legacy OpenAI key.
- `poetry run ruff check ...`
  - unavailable because Ruff is not installed in the Poetry environment.

## Known Limits

- No live provider calls were made; Models API and constructor coverage use
  deterministic fakes. Real credentials are required for an end-to-end smoke test.
- Managed connection UI currently supports only OpenAI and Anthropic protocols.
- The legacy `v2.llm.client` definitions remain behind exported compatibility
  aliases; new code uses `v2.llm.providers`.
- Full cycle/LLM failure audit remains Workstream 3.

## Git State

- Branch: `zxb_dev`.
- Workstream 2 changes are uncommitted.
- The parent roadmap/handoff files remain untracked and were not modified.

## Stable Contract for Workstream 3

- Every new Web simulation resolves and persists one immutable provider/model.
- All persona agents in that run share the run-scoped client.
- Prompt cache identity includes provider and model.
- Credentials are resolved at the API boundary and never become global request
  state or persisted simulation data.
