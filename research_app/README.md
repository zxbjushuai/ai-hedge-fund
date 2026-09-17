# Research Web application — migration stage 1

This entrypoint reuses the existing simulation, cache and connection management.
The original `app/` entrypoint remains available; run only one entrypoint on the
default ports at a time. No daemon or Flow editor is required.

From the repository root:

```powershell
poetry install
npm.cmd --prefix research_app/frontend ci
.\research_app\run.bat
```

The launcher uses the existing Windows Ctrl+C process-tree cleanup mechanism.
Interactive Ctrl+C acceptance is still pending; do not treat automated API tests
as proof of console cleanup. It refuses to start if ports 8000/5173 are occupied.

For separate terminals:

```powershell
poetry run python -m research_app.backend
npm.cmd --prefix research_app/frontend run dev
```

## Stable data paths

Root `.env` is loaded without overriding existing environment variables.
Relative paths are resolved against the repository root, not the shell directory.

| Variable | Default |
| --- | --- |
| FUND_DB_PATH | fund.db |
| LLM_DB_PATH | app/backend/hedge_fund.db |
| FUND_SPEC_PATH | hedge_fund/fund/example.yaml |
| PROMPT_CACHE_DIR | .v2_cache/llm |

These defaults deliberately retain existing storage. Nothing moves or deletes
the original databases. For migration testing, override both database paths with
disposable copies **before** starting the process. Do not test migration against
the only copy of your data. Provider credentials must never be committed.

## Offline acceptance

```powershell
poetry run pytest research_app/backend/ hedge_fund/ app/backend/ -q
npm.cmd --prefix research_app/frontend run build
npm.cmd --prefix research_app/frontend run lint
```

The isolated startup test uses temporary SQLite files; API parity reuses the
existing deterministic fake-model fixture. No real provider inference is needed.
See `openspec/changes/integrate-upstream-and-isolate-research-app/` for migration
gates. Upstream merge, package rename, dependency pruning and visual redesign
have not yet happened.
