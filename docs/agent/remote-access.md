# Safe remote access

The default deployment remains two loopback-only services plus an SSH tunnel:

```text
127.0.0.1:8000  aihf-backend
127.0.0.1:5173  aihf-frontend
```

The API has no application authentication. Keep it on loopback. A LAN bind or
Tailscale Funnel would expose unauthenticated simulation, provider, and cache
controls to anyone who can reach the port.

## Tailscale-only option

Tailscale Serve can publish the local development app to devices allowed by the
tailnet policy. It terminates HTTPS and forwards to the loopback listeners; it
does not change the Uvicorn bind or the localhost CORS settings.

Prerequisites:

- the host node is connected with `tailscale up`;
- HTTPS certificates are enabled for the tailnet;
- the tailnet ACL/grant policy restricts this node to intended users/devices;
- ports `8000` and `5173` are already healthy on loopback.

Plan the mappings without changing host state:

```bash
.venv/bin/python scripts/tailscale_remote_access.py plan
```

Apply them explicitly:

```bash
.venv/bin/python scripts/tailscale_remote_access.py apply
```

The helper maps one HTTPS origin:

```text
/dashboard/*  -> 127.0.0.1:8000
/health       -> 127.0.0.1:8000
/*            -> 127.0.0.1:5173
```

It prints the MagicDNS access URL, normally
`https://<node>.<tailnet>.ts.net/`. Open that URL from another device on the
tailnet. The frontend detects a non-loopback page and sends API calls to the
same origin, so no wildcard CORS rule is needed.

Verify from the remote device:

```bash
curl -fsS https://<node>.<tailnet>.ts.net/health
tailscale serve status
```

## Rollback

`tailscale serve reset` removes the node's Serve configuration. Before using it,
check `tailscale serve status` and make sure this node does not host Serve
mappings for another application. The helper does not run reset automatically,
so a partial or failed apply cannot erase unrelated mappings.

## Security boundary

Tailscale identity and tailnet policy are the authentication boundary. This is
not per-user authorization inside ai-hedge-fund: every tailnet user/device
allowed to reach the Serve port can operate the same unauthenticated Web API.
Do not enable Tailscale Funnel or bind either service to the LAN.

The supported Python entrypoint rejects non-loopback `--host` values. Direct
`uvicorn --host 0.0.0.0` use is unsupported. For SSH-only access, keep using the
existing local port forwards instead of enabling Serve.
