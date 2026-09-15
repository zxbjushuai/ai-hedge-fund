# Current Handoff

## Status

completed

## Scope

Workstream 2 only: explicit per-run vendor/protocol/model selection, polymorphic
adapter composition, managed connections, dynamic model discovery, response
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
- Added `vendor:protocol:model` to prompt-cache identity and persisted prompt records.
- Added run-scoped LLM injection from `SimRunner` through `Fund` to every
  `LLMAgent`; quant models do not receive the client.
- Added multiple named OpenAI, Anthropic, OpenCode Go, ModelScope, and custom
  compatible connections with independent Base URLs,
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
- Replaced compound managed provider types with independent `vendor` and
  `protocol` fields. `VendorAdapter` handles endpoint/header/session policy;
  polymorphic `ProtocolAdapter` implementations handle OpenAI Chat Completions,
  OpenAI Responses, and Anthropic Messages transports and model discovery.
- Added OpenCode Go as a managed vendor. Every simulation creates a
  new UUID and reuses it as `x-opencode-session` across all requests in that
  run, with `ai-hedge-fund/2.0` as its User-Agent.
- The OpenCode Go vendor supports separate Chat Completions and Responses
  connections. Responses models such as GPT-5.6 Luna share the same run-scoped
  session semantics and default to low reasoning effort.
- Existing compound connection types are additively backfilled into vendor and
  protocol fields. Credentials are not cloned into sibling connections.
- Existing generic OpenAI connections pointing exactly at the official Go Base
  URL are reclassified once by Alembic without changing their API key or cache;
  runtime backfill no longer infers vendors from URLs.
- OpenCode Go uses its official endpoint by default but accepts another valid
  Base URL for compatible proxies. The settings page explains that this vendor
  applies the special User-Agent and per-simulation session headers.
- Go discovery treats every model in the latest successful `/models` response
  as remotely available and marks models absent from that snapshot unavailable.
  It no longer filters new models through a stale name whitelist. The selected
  connection determines Chat Completions versus Responses transport; known
  models default enabled only for their registered protocol, while newly
  discovered unknown models remain visible and disabled until explicitly enabled.
- Registered `deepseek-v4.1-flash` for the OpenCode Go Chat Completions
  connection so the current remote model becomes selectable after synchronization.
- Added ModelScope as one vendor supporting both OpenAI Chat Completions and
  Anthropic Messages. Anthropic-compatible calls use a protocol-native HTTP
  client to avoid Python 3.14 SDK response parsing failures.
- “Save & Test” explicitly tests only the model catalog and makes no inference call.

## Database Changes

- Added nullable `sim_run.llm_provider VARCHAR(32)`.
- Added nullable `sim_run.llm_model VARCHAR(200)`.
- Added nullable `sim_run.llm_protocol VARCHAR(40)`.
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

- `poetry run pytest v2/ app/backend/services/test_llm_provider_service.py -q`
  - 206 passed, 38 live tests deselected by project configuration.
- `npm.cmd run build` from `app/frontend`
  - passed; existing font, sourcemap, Browserslist, and bundle-size warnings remain.
- ESLint on all changed frontend files
  - passed with zero warnings.
- Repository-wide `npm run lint`
  - still fails on 248 pre-existing issues outside the changed files.
- Python compileall and `git diff --check`
  - passed; Git reports only the repository's LF-to-CRLF notices.
- Alembic upgrade from `e8a1c4d2f907` through `f4c2a8d19e73` and
  `b7d9e2a4c631`
  - passed against in-memory SQLite, including the startup-compatible case in
    which `vendor` and `protocol` columns already exist before Alembic runs.
- `poetry run ruff check ...`
  - unavailable because Ruff is not installed in the Poetry environment.

## Live Smoke Test

- A user-configured provider connection successfully synchronized its remote
  model list through the Web settings page.
- The original simulation reached `completed`, but later Workstream 3 audit
  proved that its persona calls returned HTTP 400 `MissingSessionID`; only
  quant signals succeeded. The earlier completion-only check was a false
  positive and must not be treated as an inference smoke test.
- The test also confirmed that Cached Data remains readable after restarting
  the backend with the dashboard Session-leak fix.
- Post-fix Chat Completions simulation completed 31/31 cycles. A live Responses
  smoke test through the managed client returned valid JSON from GPT-5.6 Luna
  in 2.49 seconds. Catalog testing itself remains free of inference calls.
- A ModelScope `/v1/models` call returned 200. Live inference with
  `Qwen/Qwen3.5-35B-A3B` succeeded through both OpenAI Chat Completions and
  Anthropic Messages; the latter was verified again through the final
  protocol-native adapter. The listed `Qwen/Qwen3-4B` had no active inference
  provider and was replaced as the known default.
- No API key, private endpoint, prompt content, or local simulation identifier
  is recorded in this handoff.

## Known Limits

- OpenCode Go supports separate Chat Completions and Responses connections.
  Because its `/models` catalog does not encode the required transport,
  administrators must enable unknown models only under the matching connection.
- Simulation inference is serial; no concurrency limiter is currently needed.
- The legacy `v2.llm.client` definitions remain behind exported compatibility
  aliases; new code uses `v2.llm.providers`.
- Full cycle/LLM failure audit is implemented in the adjacent Workstream 3 change.

## Git State

- Branch: `zxb_dev`.
- Initial Workstream 2 implementation was committed as `5becce1`.
- The final provider polymorphism, OpenCode Go compatibility, and Workstream 3
  baseline were committed together as `dd467f1`.

## Stable Contract for Workstream 3

- Every new Web simulation resolves and persists one immutable
  vendor/protocol/model selection.
- All persona agents in that run share the run-scoped client.
- Prompt cache identity includes vendor, protocol, and model.
- Credentials are resolved at the API boundary and never become global request
  state or persisted simulation data.
