# AGENTS.md — ai-hedge-fund (Linux deployment)

This file is the operating contract for coding agents working in this repository.
Read it before changing code.

## What this is

`aihf` is an AI hedge-fund research project. The upstream CLI/TUI lives in
`hedge_fund/`; the fork-specific Web app lives in `research_app/` (FastAPI backend
+ React/Vite frontend). Simulations consume cached US market data and call an LLM
through a managed provider connection.

The project is **educational only**; it does not place real trades.

## Runtime

- Repo: `/home/zxbjushuai/codespace/ai-hedge-fund`
- Agent branch: `agent/daily` (agent-maintained). Never commit to `main` or
  `zxb_dev`. Never force-push. Never merge `main`/`zxb_dev` into the agent branch.
- Python: `.venv` (3.12) created by Poetry. Node 22 + npm.
- Backend: `systemd` unit `aihf-backend`, listening on `127.0.0.1:8000`.
- Frontend: `systemd` unit `aihf-frontend`, Vite on `127.0.0.1:5173`.
- Access is via SSH tunnel from Windows (`localhost:8000`, `localhost:5173`).
  Services are deliberately not exposed on the LAN/Tailscale.
- Health: `curl -s http://127.0.0.1:8000/health`

## Commands

```bash
# install / refresh
.venv/bin/poetry install --no-interaction
npm --prefix research_app/frontend ci

# backend
.venv/bin/python -m research_app.backend --host 127.0.0.1 --port 8000

# backend tests
.venv/bin/python -m pytest research_app/backend hedge_fund -q

# frontend
npm --prefix research_app/frontend run test
npm --prefix research_app/frontend run lint
npm --prefix research_app/frontend run build

# formatting checks
.venv/bin/black --check .
.venv/bin/isort --check-only .
.venv/bin/flake8
```

## On-demand simulation (agent)

There is no scheduled data/simulation pipeline by design. The agent decides
when to fetch data and run simulations:

```bash
.venv/bin/python scripts/aihf_ops.py status
.venv/bin/python scripts/aihf_ops.py fetch --tickers AAPL,MSFT --days 30
.venv/bin/python scripts/aihf_ops.py backtest --days 180
.venv/bin/python scripts/aihf_ops.py simulate --start 2026-01-02 --end 2026-06-30
.venv/bin/python scripts/aihf_ops.py cumulative --since 2026-01-02
.venv/bin/python scripts/aihf_ops.py matrix --spec docs/agent/backtest-matrix.example.json
.venv/bin/python scripts/aihf_ops.py analyze --last 5
```

- `backtest` = historical range for strategy comparison and optimization.
- `matrix` = reproducible, sequential comparison across several date ranges or
  universes from one JSON spec; outputs JSON plus a ranked Markdown report.
- `cumulative` = interim continuous window from a fixed start (recomputed).
- `continue` / carried-book daily mode = backlog AIHF-016 (not implemented).
- Results are saved under `logs/ops/`; the old `scripts/daily-pipeline.py` is a
  manual rolling-window tool, not a timer.

## Privileged operations

Codex full access does **not** grant Linux root. The agent runs as user
`zxbjushuai`:

- Restart the backend with `scripts/restart_services.sh` or
  `sudo -n systemctl restart aihf-backend`. Plain `systemctl restart` fails with
  polkit: "Access denied ... requires interactive authentication".
- The user has `NOPASSWD: ALL`, so `sudo -n ...` works non-interactively.
- The wrapper restarts backend/frontend and pushes once after a successful
  commit. Those steps happen **after Codex exits**, so the agent's own report
  may not reflect them.
- Do not start a temporary backend on another port unless you need to test
  during the run; prefer the restart helper.

## LLM configuration

- Provider DB: `~/.hedge-fund/research/providers.db` (SQLite, plaintext keys,
  mode 600). Do not commit it.
- Simulation connection: `sub2api opencode go` (id `4`), `vendor=custom`,
  `protocol=openai_chat_completions`, `base_url=http://127.0.0.1:18080/v1`,
  model `deepseek-v4.1-flash`. It uses Sub2API group `opencode go` (group 8),
  which routes to the OpenCode Go account.
- Fallback direct connection: id `1`, `vendor=opencode_go`,
  `protocol=openai_chat_completions`, `base_url=https://opencode.ai/zen/go/v1`,
  same model.
- Sub2API groups: `openai-default` (key 1, OpenAI account) and `opencode go`
  (group 8, key 2, OpenCode Go account). The OpenAI-group key cannot see
  `deepseek-v4.1-flash`; use key 2 for Go models.
- Key: `~/.config/ai-hedge-fund/agent.env` → `OPENCODE_API_KEY` (mode 600).
  Never print or commit it.
- Bootstrap or rotate a managed connection through the API:
  `.venv/bin/python scripts/bootstrap_llm_provider.py --api-key-file ~/.config/ai-hedge-fund/agent.env`.
  The script is idempotent, never accepts a key argument, and verifies
  `/dashboard/llm/options`; see `docs/agent/provider-bootstrap.md`.
- Codex CLI daily agent: profile `opencode-go-sub2api` (provider
  `sub2api-opencode`, base `http://127.0.0.1:18080/v1`, Responses API) uses the
  Sub2API `opencode go` group and its separate key/quota. The direct
  `opencode-go` profile remains as fallback. The daily profile uses a 256k
  context window to limit quota usage.
- History: the direct key hit `429 Too Many Requests` on 2026-11-06/07/09; the
  daily agent now uses the Sub2API OpenCode Go key (`oc_sk_6c58ca…`) to avoid
  that quota.

## Data and state

- `fund.db` (ignored): simulations, price/metrics/earnings cache, NAV history.
  Never reset or delete it; use SQLite backup.
- `.v2_cache/` (ignored): prompt cache. Keep it.
- `logs/` (ignored): backend, simulation and agent logs.
- On-demand run results: `logs/ops/` (JSON + analysis Markdown).
- Legacy rolling-window results: `logs/daily/`.
- Agent daily reports: `docs/agent-daily/` (ignored; Chinese Markdown).
- Agent backlog: `docs/agent/backlog.md` (tracked).
- Universe list: `docs/agent/universe.txt` (tracked).

## Daily automation

- `scripts/agent-daily.sh` runs the autonomous loop: lock → backup → audit →
  Codex (full access) → tests → review → commit → report → optional push →
  health check/rollback.
- `aihf-agent.timer` runs the agent daily 09:00 Asia/Shanghai (weekends included).
- There is no scheduled data/simulation timer; the agent uses
  `scripts/aihf_ops.py` on demand. Do not recreate a fixed simulation timer
  unless the user asks.
- `docs/agent/priority.md`, when present, overrides the backlog choice for the
  next run; rename it to `priority.done.md` when complete.
- **Push policy**: the agent must not run `git push`. The wrapper pushes at most
  once per day (`PUSH_ENABLED=1` plus `~/.local/state/aihf-last-push-date`); a
  pre-push hook blocks pushes unless the wrapper sets `AIHF_ALLOW_PUSH=1`.
- **Commit management**: one or a few coherent commits per run; no commit spam,
  no amend, no force-push. Accumulate work and let the wrapper push once.
  Commit incrementally before long operations so tested work survives provider
  failures.
- **Failure salvage**: if Codex exits nonzero (e.g. provider 429/timeout), the
  wrapper keeps the WIP and runs the test gate. Passing work is salvaged and
  committed; failing work is tagged `wip-*` and reverted.
- **Resource limits**: at most 4 simulation/backtest runs per agent run; reuse
  results. The agent may improve `scripts/aihf_ops.py` and backtest tooling.
- Full access is enabled at the user's request. Backups, tags, test gates and
  rollback are mandatory to compensate.
- Only push `agent/daily` when `PUSH_ENABLED=1` in `agent.env`. Unless the user
  says otherwise, never push to `main`/`zxb_dev`.

## Boundaries

- Do not modify `.env`, `fund.db`, or `providers.db` except through approved
  scripts; never delete them.
- Do not print secrets (API keys, tokens, SSH keys) in output or commits.
- Do not delete files without explicit approval (see the global Codex rules and
  `~/.codex/AGENTS.md`).
- Keep services running. Restart only after tests pass; verify `/health`.
- One feature per run; small, reviewable diff; update tests.
- For non-trivial work, use OpenSpec (`openspec/changes/<name>/`) and the
  `openspec-*` skills.
- Simulation correctness matters: no lookahead, raw price mode, benchmark
  coverage, persona abstention, and deterministic tests.
- The daily simulation is currently an **independent** rolling-window run
  (fresh `initial_capital` each day). Continuous carried-book paper trading is
  backlog item AIHF-016; do not claim that NAV carries over until it is
  implemented.

## Known gaps (see `docs/agent/backlog.md`)

- No in-process scheduler for `research_app`; the daily pipeline is external.
- Cache freshness is keyed by exact requested range; incremental updates pending.
- Cache jobs and simulation runners are in-memory; stale `running` rows possible
  after restart.
- Simulation ticker cap is 50.
- The Web API has no authentication; it is only safe behind localhost/SSH tunnel.
- `Sub2API` cannot serve `deepseek-v4.1-flash` today.
