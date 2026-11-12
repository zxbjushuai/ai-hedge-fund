# Handoff: Provider Bootstrap Script

## Implemented

`scripts/bootstrap_llm_provider.py` now creates or updates one managed LLM
connection and one enabled model through the existing provider API. It:

- reads the secret only from an environment variable or `KEY=value` env file;
- defaults to `opencode go` / `opencode_go` / `openai_chat_completions` /
  `deepseek-v4.1-flash`;
- creates a missing connection/model, or patches existing rows idempotently;
- rejects a same-name connection with a different vendor/protocol;
- re-syncs model availability when a credential/endpoint change invalidated any
  remote-discovered model;
- verifies the enabled connection/model through `/dashboard/llm/options`; and
- redacts the submitted secret before truncating API error details.

`docs/agent/provider-bootstrap.md` documents initial setup, Sub2API usage, and
key rotation. `AGENTS.md` points operators at the script.

## Verification

- Focused: `research_app/backend/test_provider_bootstrap.py` → 9 passed.
- Backend: `.venv/bin/python -m pytest research_app/backend hedge_fund -q` →
  375 passed, 39 deselected.
- Frontend: `npm --prefix research_app/frontend run test` → 28 passed;
  `lint` and `build` passed.
- Black and isort checks passed for the new Python files.
- `codex exec review --base backup-20261112-090058` final pass found no
  actionable correctness or security defects. Earlier review findings drove the
  redact-before-truncate and all-remote-model re-sync fixes.

## Notes

The integration test runs the real FastAPI routes against temporary
`FUND_DB_PATH` and `LLM_DB_PATH` values. No external network, paid completion,
real provider database, or simulation run was used. The existing
`scripts/configure_sub2api.py` helper remains in place; the new script covers
both direct OpenCode Go and Sub2API identities without deleting the old path.

The OpenSpec CLI is not installed on this host, so artifacts are maintained
directly in the repository's existing `openspec/changes/` format.
