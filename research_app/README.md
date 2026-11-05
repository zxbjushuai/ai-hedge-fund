# Research Web application

Provider creation selects one of three protocols: OpenAI Chat Completions,
OpenAI Responses or Anthropic Messages. For Sub2API, enter the relay API URL and
its downstream API key. Legacy direct OpenCode Go connections remain supported
by the backend but are hidden from the Web connection list and new-run choices.

## Simulation progress and logs

Review shows the call estimate and accepts **Model concurrency 1–8** (default 4).
Confirm opens **Running**, showing current tickers/analysts, stages, elapsed time,
HTTP attempts and failures. The server caps aggregate in-flight requests at 8 and
does not prefetch future simulation dates. Higher concurrency can hit provider limits.

Each new run writes UTF-8 JSON Lines to
`<resolved FUND_DB_PATH parent>/logs/simulations/sim-{id}.log` (normally the root
`logs/simulations` directory). These contain structured summaries, not prompts or
raw responses. Existing prompt-cache storage is unchanged. After restart, live
activity is unavailable; selecting an old run does not resume it. Partial results
show Latest NAV and the last valued date rather than the initial investment.

Restart the backend after updating code; its existing additive migration adds nullable
`sim_run.execution_config` without resetting historical simulations.

This entrypoint reuses the existing simulation, cache and connection management.
The application now lives in `research_app/` and shares the `hedge_fund` core with
the upstream CLI/TUI. Old `app/` source and `v2/` are retired. No daemon or Flow
editor is required. Provider storage defaults to the user directory; explicit
LLM_DB_PATH overrides remain supported.

From the repository root:

```powershell
poetry install
npm.cmd --prefix research_app/frontend ci
.\research_app\run.bat
```

The launcher uses the existing Windows Ctrl+C process-tree cleanup mechanism.
Interactive Ctrl+C acceptance was confirmed by the user in stage 1; automated
API tests alone do not prove console cleanup. The launcher refuses to start if
ports 8000/5173 are occupied.

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
| LLM_DB_PATH | ~/.hedge-fund/research/providers.db |
| FUND_SPEC_PATH | hedge_fund/fund/example.yaml |
| PROMPT_CACHE_DIR | .v2_cache/llm |

Existing checkouts must copy the old `app/backend/hedge_fund.db` with SQLite's
backup API before using the new default, or set LLM_DB_PATH to the old absolute
path. Startup does not automatically move data. The local migration retained
the old file as a backup; after switching, it is not updated by new runs.
Fund and prompt-cache defaults are unchanged.
For migration testing, override both database paths with
disposable copies **before** starting the process. Do not test migration against
the only copy of your data. Provider credentials must never be committed.

## Offline acceptance

```powershell
poetry run pytest research_app/backend/ hedge_fund/ -q
npm.cmd --prefix research_app/frontend run build
npm.cmd --prefix research_app/frontend run lint
```

The isolated startup test uses temporary SQLite files; API parity reuses the
existing deterministic fake-model fixture. No real provider inference is needed.
See `openspec/changes/integrate-upstream-and-isolate-research-app/` for migration
gates. Upstream merge, package rename and dependency pruning are complete;
visual redesign remains separate.

## Upstream entrypoint and future merges

`poetry run aihf` starts the author's Textual TUI. For scripted execution use
`poetry run aihf <mandate.yaml> --tickers AAPL,MSFT --date YYYY-MM-DD --out result.json`.
CLI/TUI use `~/.hedge-fund/` files and their own environment credentials; they do
not read the Web's connection database or SQLite simulation history. Networked
CLI runs require the author's financial-data provider credentials.

Future sync: pin an upstream SHA, create an integration branch from the current
development baseline, merge that SHA, review the extension points documented in
`merge-decisions.md`, run both entrypoint suites and Web browser checks, then
request approval to integrate into the development branch. Never reset the DB or
replace a working environment with an upstream `.env` file.
