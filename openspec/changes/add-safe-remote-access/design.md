# Design: Safe Remote Access

## Trust Boundaries

The FastAPI process remains bound to a loopback address. The Tailscale Serve
daemon, not Uvicorn, terminates tailnet HTTPS and forwards only requests that
reached this node through the tailnet. Tailscale ACL/grant policy therefore
controls which users and devices can open the app. Tailscale Funnel is never
used because it would expose the unauthenticated API beyond the tailnet.

## Backend Bind Guard

`research_app.backend.__main__` validates `--host` before importing Uvicorn.
Loopback names, IPv4 loopback addresses, and IPv6 loopback addresses are
accepted. Wildcard, LAN, tailnet, and DNS names are rejected with a concise
error that points to Tailscale Serve. Accepted addresses are normalized before
Uvicorn receives them (for example, `[::1]` becomes `::1`). Direct
`uvicorn --host 0.0.0.0` is outside the supported entrypoint and is called out
in the runbook.

## Same-Origin Routing

Tailscale Serve maps one HTTPS origin as follows:

```text
/dashboard/*  -> http://127.0.0.1:8000
/health       -> http://127.0.0.1:8000
/*            -> http://127.0.0.1:5173
```

The frontend API helper keeps the configured backend URL when the page host is
loopback. On a non-loopback page it returns `window.location.origin`, so remote
requests go back through the same tailnet origin. This avoids wildcard CORS and
works with the existing Vite dev server.

## Helper Contract

`scripts/tailscale_remote_access.py` is safe by default:

- `plan` prints the exact Serve commands and does not mutate host state;
- `apply` requires the Tailscale CLI, verifies the node is online, applies the
  three mappings, and prints the tailnet HTTPS URL;
- failures are non-destructive and do not reset unrelated Serve configuration.

Rollback is an explicit operator action (`tailscale serve reset`) because
blindly resetting Serve could remove mappings owned by another application.

## Tests

Tests cover accepted and rejected bind hosts, loopback versus remote API base
resolution, and deterministic Serve command generation/application using a fake
runner. Verification does not open a tailnet listener or call a remote service.
