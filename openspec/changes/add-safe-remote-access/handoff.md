# Handoff: Safe Remote Access

## Implemented

- `research_app.backend.__main__` now accepts only normalized loopback bind
  hosts. Wildcard, LAN, tailnet, and DNS binds fail before Uvicorn starts.
- The frontend resolves API calls to the page origin for non-loopback hosts.
  Localhost keeps the existing `VITE_API_URL` / `http://localhost:8000` path.
- `scripts/tailscale_remote_access.py` plans or applies tailnet-only Serve
  mappings for `/dashboard`, `/health`, and the Vite root. The target URLs
  preserve the API prefix because Tailscale strips the Serve mount before
  proxying.
- `docs/agent/remote-access.md` documents prerequisites, verification, rollback,
  and the fact that tailnet policy is the authentication boundary.

## Verification

- Focused backend guard/helper tests: 14 passed.
- Backend full suite: 397 passed, 39 deselected.
- Frontend tests: 32 passed; lint and production build passed.
- Changed Python files pass Black, isort, and flake8 with the project's
  420-column setting. The repository-wide bare flake8 command still reports
  pre-existing issues outside this change.
- Built-in Codex review against `backup-20261114-090721` found no actionable
  correctness or security defects.

## Operating Note

No live Tailscale Serve mapping was applied during this run, no service was
restarted, and no simulation/backtest was run. The current deployment remains
loopback-only with SSH-tunnel access until an operator runs the documented
`apply` command.
