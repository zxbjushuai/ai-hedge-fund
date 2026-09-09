# Design: Run-scoped LLM Selection

## Registry and Identity

`v2.llm.registry` owns canonical provider ids, credential names, default
models, fixed compatible endpoints, and the model catalog. A selection is the
pair `(provider, model)` and its cache identity is `provider:model`.

## Client Factory

`make_llm(provider, model, credential)` constructs a provider transport and
wraps it in one `ChatLLM`. `ChatLLM.complete` is the sole response-normalizing
path. It retains text blocks and drops reasoning, thinking, tool, and signature
blocks before the existing JSON extraction step.

Legacy `get_llm()` and named provider helpers remain compatibility shims for
CLI/scheduler code. Web simulation never uses environment variables as mutable
request state.

## Managed Connections and Credentials

The application database stores multiple named OpenAI/Anthropic connections,
each with its own normalized Base URL, API key, and enabled state. Public HTTPS
is required; HTTP is limited to localhost, loopback, and literal private IPs.
Secrets are write-only in the managed API: responses expose only presence and a
four-character mask. Existing OpenAI/Anthropic API-key rows are copied once into
default connections without deleting the legacy rows.

Legacy provider/model callers continue to resolve the existing API-key table or
environment. A managed simulation resolves only the selected connection and
never mutates process-global environment state.

## Model Discovery

OpenAI connections request `<base_url>/models`; Anthropic connections request
the protocol's paginated `/v1/models` resource. Redirects are refused so a key
cannot cross origins. A failed test/sync records a safe error but preserves the
last cache. Missing remote models become unavailable rather than being deleted;
manual models remain available independently. Known registry models default to
enabled, while unknown remote models require explicit enablement.

## Runtime Injection

The API resolves and validates an immutable connection/model selection before creating a run.
`SimRunner` owns the resulting LLM client and passes it to `Fund`. `Fund`
injects it only into `LLMAgent` subclasses; quant models retain their existing
constructors. This prevents concurrent runs from sharing model selection.

## Persistence and Compatibility

Nullable `sim_run.llm_provider`, `sim_run.llm_model`, connection id, connection
name, and Base URL columns use the additive SQLite migration. The connection
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
available so the user can add a manual model. Transport and parse failures continue to abstain
inside the current LLMAgent contract; the richer failed/abstained audit model
remains Workstream 3.
