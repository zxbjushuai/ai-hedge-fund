# Proposal: Add Safe Remote Access

## Why

The research Web app binds both services to loopback and is currently reached
through an SSH tunnel. Operators need a documented remote path that does not put
an unauthenticated FastAPI surface on the LAN or public internet. A one-off
`--host 0.0.0.0` launch or a browser pointing at loopback would be unsafe or
non-functional from another device.

## What Changes

- Reject non-loopback backend bind addresses in the supported Python entrypoint.
  Remote access must proxy to `127.0.0.1` rather than exposing Uvicorn directly.
- Resolve Web API requests to same-origin `/dashboard` and `/health` routes when
  the frontend is opened from a non-loopback host, while preserving the current
  localhost development URL.
- Add a Tailscale Serve plan/apply helper that exposes the Vite frontend at `/`
  and the backend paths through the same tailnet HTTPS origin. Tailnet policy is
  the authentication boundary; no Tailscale Funnel or LAN listener is enabled.
- Document the SSH-tunnel default, Tailscale prerequisites, access URL, rollback,
  and the security boundary.

## Compatibility

The default localhost services and SSH tunnel continue to work unchanged. The
change is opt-in and does not require a schema migration, CORS relaxation,
public DNS, or a reverse proxy on the LAN. Existing `VITE_API_URL` overrides on
loopback hosts retain precedence.

## Non-goals

- Public internet exposure, Tailscale Funnel, or anonymous remote access.
- An application login system or per-user authorization inside the Web app.
- Restoring the Vite build as a production static server.
- Changing service units, restarting services, or applying a live Serve mapping
  during automated verification.
