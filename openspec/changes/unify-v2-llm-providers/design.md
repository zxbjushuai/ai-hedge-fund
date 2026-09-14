# Design: Run-scoped LLM Selection

## Registry and Identity

`v2.llm.registry` retains canonical legacy provider ids, credential names, and
the known-model catalog. Managed connections select `(vendor, protocol, model)`
and use `vendor:protocol:model` as the cache identity, so the same model routed
through two wire protocols cannot reuse the wrong cached response.

## Client Factory

`VendorAdapter` owns endpoint policy, supported protocols, special headers,
session creation, and vendor request options. `ProtocolAdapter` owns client
construction and model discovery for OpenAI Chat Completions, OpenAI Responses,
or Anthropic Messages. `make_connection_llm(config)` validates the combination
and composes the two strategies behind one synchronous `complete(system, user)`
contract. This is the extension point for new vendors and protocols.

Anthropic Messages uses a small protocol-native HTTP client. This avoids SDK
response-model assumptions that break otherwise valid compatible responses on
Python 3.14. Answer text is retained while reasoning, thinking, tool, and
signature blocks are excluded before JSON extraction.

Legacy `get_llm()` and named provider helpers remain compatibility shims for
CLI/scheduler code. Web simulation never uses environment variables as mutable
request state.

## Managed Connections and Credentials

The application database stores multiple named connections,
each with its own normalized Base URL, API key, and enabled state. Public HTTPS
is required; HTTP is limited to localhost, loopback, and literal private IPs.
Secrets are write-only in the managed API: responses expose only presence and a
four-character mask. Existing OpenAI/Anthropic API-key rows are copied once into
default connections without deleting the legacy rows.

Legacy provider/model callers continue to resolve the existing API-key table or
environment. A managed simulation resolves only the selected connection and
never mutates process-global environment state.

OpenCode Go is a vendor policy rather than a protocol. Each simulation creates
one UUID and sends it as
`x-opencode-session` on every inference request made by that run, together with
the application User-Agent. Existing OpenAI connections whose Base URL exactly
matches the official Go endpoint are reclassified once by an Alembic data
migration without changing their key or model cache. Runtime compatibility code
does not infer a vendor from its URL. Catalog testing remains a `/models`
request and does not consume an inference call.

The official endpoint remains the default, but an OpenCode Go connection may
use another valid Base URL for a compatible proxy. Selecting this vendor means
the endpoint accepts OpenCode's special User-Agent and per-simulation
`x-opencode-session` request headers.

The same OpenCode Go vendor supports independent Chat Completions and Responses
connections. Existing compound `provider_type` values are backfilled into
`vendor` and `protocol`; migration does not clone connections or credentials.
The old field remains as a compatibility projection for old callers.

ModelScope similarly supports OpenAI Chat Completions and Anthropic Messages.
Its protocol changes the default Base URL and wire format without creating a
new vendor implementation.

The Responses client defaults to low reasoning effort and 4096 output tokens.
It uses the same stable per-simulation session UUID as the Chat Completions
client. Simulation calls remain serial, so no concurrency limiter is added.

## Model Discovery

OpenAI-compatible protocols request `<base_url>/models`; Anthropic Messages requests
the protocol's paginated `/v1/models` resource. Redirects are refused so a key
cannot cross origins. A failed test/sync records a safe error but preserves the
last cache. Every model in the latest successful `200` response is cached as
available, regardless of whether it was known to the previous application
version. Remote models missing from that complete snapshot become unavailable
rather than being deleted; manual models remain available independently. Known
registry models default to enabled on the matching protocol connection, while
unknown remote models are visible but require explicit enablement. Enabling a
model under a Chat Completions or Responses connection is the administrator's
explicit protocol choice.

## Runtime Injection

The API resolves and validates an immutable connection/model selection before creating a run.
`SimRunner` owns the resulting LLM client and passes it to `Fund`. `Fund`
injects it only into `LLMAgent` subclasses; quant models retain their existing
constructors. This prevents concurrent runs from sharing model selection.

## Persistence and Compatibility

Nullable `sim_run.llm_provider`, `sim_run.llm_protocol`, `sim_run.llm_model`,
connection id, connection name, and Base URL columns use the additive SQLite migration. The connection
fields are snapshots for historical display and reproducibility; the API key is
never copied into the simulation database. Legacy rows return nulls.

## API and UI

`/dashboard/llm/providers` manages connections and their models.
`GET /dashboard/llm/options` returns only enabled connections with enabled,
available models. New simulation requests carry `llm_connection_id` and model;
the former provider/model request remains compatible. Settings provides the
provider management page and simulation uses a two-stage selector.

## Failure Semantics

Disabled connections, missing keys, and unavailable models fail preflight with
actionable messages. A connection can still be saved if its Models API is not
available so the user can add a manual model. The adjacent Workstream 3 change
records transport and parse failures as typed failed signals rather than
successful neutral views or insufficient-data abstentions.
