# Provider bootstrap and key rotation

`scripts/bootstrap_llm_provider.py` creates or updates one managed LLM
connection and enables one model through the Web API. It never edits
`providers.db` directly, accepts the secret only from an environment variable or
env file, and verifies that `/dashboard/llm/options` exposes the result.

## Initial setup

The defaults create the direct OpenCode Go fallback used by the project:

```bash
.venv/bin/python scripts/bootstrap_llm_provider.py \
  --api-key-file ~/.config/ai-hedge-fund/agent.env
```

The default key variable is `OPENCODE_API_KEY`; the default connection is
`opencode go` with vendor `opencode_go`, protocol `openai_chat_completions`, the
API's normalized base URL, and model `deepseek-v4.1-flash`. Success prints JSON
with the connection id and whether the connection/model were created or reused.

An environment variable works the same way:

```bash
export OPENCODE_API_KEY=... # do not commit this value
.venv/bin/python scripts/bootstrap_llm_provider.py
```

For the Sub2API connection, pass its identity explicitly:

```bash
.venv/bin/python scripts/bootstrap_llm_provider.py \
  --name "sub2api opencode go" \
  --vendor custom \
  --protocol openai_chat_completions \
  --base-url http://127.0.0.1:18080/v1 \
  --api-key-file ~/.config/ai-hedge-fund/agent.env
```

The backend must be healthy first: `curl -s http://127.0.0.1:8000/health`.
The script is safe to rerun with the same arguments. A same-name connection with
a different vendor/protocol is rejected because the update API intentionally
does not change connection kind.

## Key rotation

1. Rotate the credential at the provider or Sub2API key store first.
2. Replace only the value of `OPENCODE_API_KEY` in
   `~/.config/ai-hedge-fund/agent.env`; keep the file mode at `600`.
3. Rerun the same bootstrap command. The existing connection is patched and the
   requested model is re-enabled; no duplicate rows are created. If the key
   change invalidated any remote-discovered model, the script calls the existing
   model-sync endpoint so the rotated credential and all model availability are
   checked. That call lists models; it does not run a completion.
4. Confirm the command reports the model and that
   `GET /dashboard/llm/options` contains the connection/model.
5. Optionally use the Web settings **Test** action for a live credential check.

If the old key is still visible in shell history or logs, revoke it at the
source. Never pass a key with `--api-key`, because process listings and shell
history expose it.

## Tests

The tests use fake HTTP responses plus a subprocess with temporary
`FUND_DB_PATH` and `LLM_DB_PATH`; they do not call a model endpoint:

```bash
.venv/bin/python -m pytest research_app/backend/test_provider_bootstrap.py -q
```
