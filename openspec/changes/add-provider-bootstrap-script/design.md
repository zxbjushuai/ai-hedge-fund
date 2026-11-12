# Design: Provider Bootstrap Script

## Command Contract

The script defaults to the configured OpenCode Go fallback:

```bash
.venv/bin/python scripts/bootstrap_llm_provider.py \
  --api-key-file ~/.config/ai-hedge-fund/agent.env
```

Defaults are connection name `opencode go`, vendor `opencode_go`, protocol
`openai_chat_completions`, the API's normalized default base URL, and model
`deepseek-v4.1-flash`. The secret is read from `OPENCODE_API_KEY` by default.
`--api`, `--name`, `--vendor`, `--protocol`, `--base-url`, `--model`,
`--api-key-env`, and `--api-key-file` allow custom or Sub2API connections.

There is deliberately no `--api-key` argument: command-line secrets leak into
shell history and process listings. JSON output contains the connection id,
name, model, and create/update flags, but never the key.

## Idempotent Flow

1. Read and validate the secret and vendor/protocol pair locally.
2. `GET /dashboard/llm/providers`; find the connection by exact name.
3. Create it when absent. When present, require the same vendor/protocol and
   `PATCH` its base URL, key, and enabled state.
4. List the connection's models. Create the requested model when absent;
   otherwise `PATCH` its display name and enabled state. If a changed endpoint
   invalidated any remote-discovered model, call the existing model-sync
   endpoint before verification so unrelated enabled models also remain usable.
   This is a credential/model-list check, not a completion request.
5. `GET /dashboard/llm/options` and require the enabled connection/model pair.

Step 5 is the acceptance check: it uses the same API surface that the
simulation form consumes. A disabled model or connection is repaired on the
next run rather than reported as success.

## Failure Semantics

HTTP errors, unreadable key files, missing environment variables, unsupported
vendor/protocol pairs, and same-name connections with a different kind fail
with a concise non-secret error and exit non-zero. A failed later step leaves
the previous steps persisted so the operator can correct the input and rerun;
the operation is safe to repeat.

## Tests

Unit tests use a fake HTTP session to assert request order and idempotent
create/update behavior, including re-sync after remote-model invalidation. A
subprocess integration test starts the real FastAPI app with a temporary
`LLM_DB_PATH` and `FUND_DB_PATH`, bootstraps twice, rotates the key, and verifies
one connection and one enabled model through the real API and the database. No
external network or LLM calls are made.
