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

## LLM configuration

- Provider DB: `~/.hedge-fund/research/providers.db` (SQLite, plaintext keys,
  mode 600). Do not commit it.
- Active connection: id `1`, `vendor=opencode_go`, `protocol=openai_chat_completions`,
  `base_url=https://opencode.ai/zen/go/v1`, model `deepseek-v4.1-flash`.
- Key: `~/.config/ai-hedge-fund/agent.env` → `OPENCODE_API_KEY` (mode 600).
  Never print or commit it.
- Codex CLI: provider `opencode-go` (Responses API) in `~/.codex/config.toml`;
  profile `~/.codex/opencode-go.config.toml` uses `deepseek-v4.1-flash`.
- Sub2API on this machine currently exposes only OpenAI models, not
  `deepseek-v4.1-flash`; do not route this model through Sub2API.

## Data and state

- `fund.db` (ignored): simulations, price/metrics/earnings cache, NAV history.
  Never reset or delete it; use SQLite backup.
- `.v2_cache/` (ignored): prompt cache. Keep it.
- `logs/` (ignored): backend, simulation and agent logs.
- Daily pipeline results: `logs/daily/`.
- Agent daily reports: `docs/agent-daily/` (ignored; Chinese Markdown).
- Agent backlog: `docs/agent/backlog.md` (tracked).
- Universe list: `docs/agent/universe.txt` (tracked).

## Daily automation

- `scripts/agent-daily.sh` runs the autonomous loop: lock → backup → audit →
  Codex (full access) → tests → review → commit → report → optional push →
  health check/rollback.
- `systemd` timers: `aihf-agent.timer` (Mon–Fri 09:00 Asia/Shanghai) and
  `aihf-daily.timer` (Mon–Fri 06:30, data + simulation).
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

## Known gaps (see `docs/agent/backlog.md`)

- No in-process scheduler for `research_app`; the daily pipeline is external.
- Cache freshness is keyed by exact requested range; incremental updates pending.
- Cache jobs and simulation runners are in-memory; stale `running` rows possible
  after restart.
- Simulation ticker cap is 50.
- The Web API has no authentication; it is only safe behind localhost/SSH tunnel.
- `Sub2API` cannot serve `deepseek-v4.1-flash` today.
