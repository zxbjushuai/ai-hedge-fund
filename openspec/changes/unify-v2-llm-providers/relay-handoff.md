# Protocol-only Web connections — 2026-10-20

## Latest operational status

The relay database repair below completed successfully at 23:42 Asia/Shanghai on
2026-10-20. Public settings and real administrator login both returned HTTP 200
with API code 0 afterward. Earlier diagnostic notes are historical, not pending
restart work. No OpenCode Go account was created by the agent.

New Web connections expose exactly OpenAI Chat Completions, OpenAI Responses and
Anthropic Messages. They are saved as `vendor=custom` with explicit protocol,
Base URL and a per-connection key. This avoids applying an upstream vendor's
special headers or request-body options to a generic relay.

Existing non-Go connections keep their vendor, ID, models and key when edited.
Blank API-key edits retain the saved key. Switching protocol during creation
preserves a user-entered relay URL. Protocol changes on saved connections still
require a separate connection, consistent with the existing API.

Legacy `opencode_go` / `opencode_go_responses` connections are hidden in both
Providers and the new-simulation selector. No database records or API adapters
are deleted, disabled or rewritten. Historical simulation/audit remains visible.

The backend `OpenCodeGoVendor` remains operational and registered. Its code now
documents why: older managed connections, explicit CLI/API clients and direct
access still require the established per-run session header behavior. The new
Web workflow delegates upstream-specific compatibility to Sub2API instead.
There is no automatic migration of a Go key into a relay connection: the relay
must hold the upstream key and issue a separate downstream key to this project.

Validation: 28 frontend tests passed, TypeScript/Vite build passed, full ESLint
zero warnings; 42 existing backend provider/service tests passed. New workflow
tests cover all three protocols, hidden legacy rows, retained relay URL and
unchanged existing vendor/key on edit. No real inference, commit or push.

## Management page access

The supplied login note only names a loopback URL, not a remotely exposed endpoint.
Tailscale identified the online Lenovo laptop; direct TCP 18081 was refused.
Existing SSH config `ubuntu-tailscale` points to that laptop. SSH recognized the
public key, but the local private key requires interactive passphrase unlock.
A visible PowerShell window was opened to run:

```powershell
ssh -N -L 127.0.0.1:18081:127.0.0.1:18080 -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o StrictHostKeyChecking=yes ubuntu-tailscale
```

After unlocking, browse `http://127.0.0.1:18081`. Keep the tunnel window open while
using the relay; close it with Ctrl+C when finished. Add the OpenCode Go account
in Sub2API, issue its downstream API key, then create a protocol-only connection
in this project using the forwarded API URL. No credentials are stored in this
document. Remote listener diagnostics confirmed loopback port **18080** and a running
`personal-relay-sub2api-1` container. The note's **18081 is the client-side forwarded
port**, not the laptop's listening port. Earlier forwards to remote 18081/8080/8081
were refused. After user unlock, `http://127.0.0.1:18081` returned HTTP 200 with title
`Sub2API - AI API Gateway`. Browser launch from the shell was rejected by the tool
approval policy. The user can open that URL in their browser and keep the successful
SSH window open. No Go account/downstream key was created and no inference was sent.

## Windows SSH authentication — 2026-10-20

At the user's request, Windows OpenSSH Authentication Agent (`ssh-agent`) was changed
from stopped/manual to running/automatic, using the normal Windows UAC elevation flow.
The current user's existing Ed25519 identity was already stored in the agent; no new
private key, passphrase removal, or private-key content change was necessary. Two
independent `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes ubuntu-tailscale ...`
commands succeeded without interactive input. Future laptop diagnostics can use that
SSH alias directly without repeatedly asking the user to unlock a private key.

The separate Sub2API login failure was diagnosed from sanitized container logs:
`weishaw/sub2api:0.2.17` is running, but repeated database queries fail with
`pq: could not open shared memory segment ...: No such file or directory`.
The home page and /health return 200 while /api/v1/settings/public returns 500.
Database shared-memory failure is confirmed; its trigger and corrective maintenance
remain to be investigated. No database or Sub2API restart was performed by this step.
Read-only follow-up confirmed Sub2API uses the dedicated loopback PostgreSQL port
15432 (postgres PID 255294) and Redis port 16379. The system PostgreSQL 18-main
cluster is separately on port 5432; do not restart that unrelated cluster as a
blanket fix for the relay's database error.

### Likely shared-memory cleanup cause (read-only diagnosis)

Dedicated postgres PID 255294 runs as ordinary user `zxbjushuai` (UID 1000),
started at 11:03:36 on 2026-10-20, with data directory
`/home/zxbjushuai/api-relay/native-postgres`. `dynamic_shared_memory_type=posix`.
The user's linger is disabled; logind configuration retains the documented
`RemoveIPC=yes` default. Journal entries show sessions removed at 18:40:48 and
18:40:58; /dev/shm's modification time is 18:40. The segment named in the
database errors is absent, and surviving PostgreSQL shared-memory objects are
owned by the separate system postgres account. This strongly supports logind
IPC cleanup on user-session exit; it does not establish which particular client
ended the session. A second Sub2API web login alone does not explain these files.

Restarting only Sub2API may rebuild connections but does not rebuild the failed
database instance's missing shared memory. Corrective maintenance should target
the dedicated port-15432 instance, preserve its data, and address its lifetime /
IPC ownership. No restart, database change or logind policy change was executed.

## Completed repair — 2026-10-20 23:42 Asia/Shanghai

User explicitly authorized repair. The dedicated service now runs as system user
`relay-postgres` (UID 994, group 972, nologin), with data copied to
`/var/lib/personal-relay-postgres` (0700) and sockets under
`/run/personal-relay-postgres` (0755). The systemd unit remains
`personal-relay-postgres.service`, enabled at boot, now with fast graceful shutdown
(`KillSignal=SIGINT`), RuntimeDirectory and ProtectHome=true. Port 15432 and existing
database roles/passwords are unchanged. Global logind/RemoveIPC settings were not changed.

The application was stopped briefly, PostgreSQL was cleanly stopped and verified as
shut down, then a compressed physical backup was created and SHA-256 checked before
copying data. The original data directory remains intact. After starting the repaired
database, a SQL query, roles backup and custom-format application database dump succeeded;
the application was then restarted using its existing `weishaw/sub2api:0.2.17` image.

Backup directory (private, root-owned):
`/home/zxbjushuai/api-relay/backups/postgres-service-20261020T154221Z`

Includes original unit/config files, `cluster.tar.gz`, `SHA256SUMS`, `globals.sql`,
`sub2api.dump` and migration metadata. Size approximately 13 MiB. Dumps can contain
credential material and must remain private. No backup contents were printed.

Live validation:

- Cold-backup SHA-256 rechecked and matched; pg_restore could list the logical dump.
- Database cluster identifier preserved: `7698580337684870159`.
- The original administrator remains; successful login returned a valid access token
  which was used only as an in-memory success check and not persisted or printed.
- `/health`: 200; `/api/v1/settings/public`: 200 / code 0;
  `/api/v1/auth/login`: 200 / code 0 / authenticated.
- Current container startup log: zero ERROR lines and no missing-shared-memory errors.
- New shared-memory objects are owned by `relay-postgres`.
- Unrelated system PostgreSQL 18-main on port 5432 retained PID 254388 throughout.

Repair implementation is retained in `ops/repair_relay_postgres.py` and was staged on
the laptop as `/home/zxbjushuai/api-relay/repair_relay_postgres_20261020.py`. It refuses
an existing destination and keeps the original data/unit for failure rollback; do not
rerun it against the repaired service. No source changes to Sub2API were made.

### Maintenance and rollback boundary

Operate the dedicated database using `sudo systemctl status/restart personal-relay-postgres`.
The old home-directory cluster is a migration-time copy, not the live database. Never
start it alongside the repaired service, and do not restore it after new accounts or
keys have been added without first backing up and accounting for the new data.

If immediate migration rollback is needed before accepting new writes: stop Sub2API
and the dedicated database, restore the backed-up systemd unit, daemon-reload, and
start the original service then Sub2API. This returns to the original normal-user
deployment and its known IPC vulnerability. After any new writes, prefer recovery of
the current cluster or a fresh current backup rather than that old directory.

Current management URL: `http://127.0.0.1:18081`, forwarded to laptop loopback 18080.
Keep its SSH tunnel running. Windows ssh-agent now permits reconnecting without repeated
passphrase prompts. Creating the upstream Go account and downstream relay key remains
a user-managed operation; no inference/model tests were performed during this repair.

## Public admin ingress — 2026-10-21 Asia/Shanghai

The owner subsequently created the Go upstream account, group and downstream key.
Authenticated public GET /v1/models returned 200 with that key, including
deepseek-v4.1-flash. No inference was requested. Python urllib requests to the public
hostname returned 403 while curl succeeded; client-dependent filtering remains uninvestigated.

The owner explicitly chose application login only, without Cloudflare Access email
restriction, and requested public management for Sub2API, NapCat and AstrBot.
Read-only checks found nonempty/non-known-default credentials, AstrBot's unauthenticated
config endpoint returned 401, and NapCat's login-info endpoint returned application
code -1 with no data. These are limited checks, not an authentication/security audit.

Applied laptop ingress through `ops/publish_admin_ingress.py`:

- relay.zxbjushuai.com -> http://127.0.0.1:18080
- napcat.zxbjushuai.com -> http://100.84.98.125:6099
- astrbot.zxbjushuai.com -> http://100.84.98.125:6185

The latter ports bind to the laptop Tailscale IP, not loopback. Application bindings,
credentials, database/OneBot ports and existing API/SSH/EasyTier routes are unchanged.
Validated candidate and applied cloudflared configuration; restarted only the shared
cloudflared container. Existing public model endpoint still returns expected 401
without a key. Original config backup:
`/opt/cloudflared/config/config.before-public-admin-20261020T160958Z.yml`.

DNS records are not yet created/confirmed. Three proxied CNAMEs must point to
`f66864f0-24ff-48a9-91e0-2b7a9862d81d.cfargotunnel.com`. At validation time relay/napcat
did not resolve and astrbot DNS timed out. HTTPS, WebSocket/SSE and browser login
acceptance remain pending DNS. Do not describe these admin URLs as already usable.
No files were deleted and no Git commit/push was created.

### Owner-selected hostname and first public checks

The owner created DNS using `sub2api.zxbjushuai.com`, not `relay`. Renamed only
that ingress rule using the helper's `--rename-relay-to-sub2api` mode; configuration
validated before/after the tunnel restart. Pre-rename backup:
`/opt/cloudflared/config/config.before-public-admin-20261020T161426Z.yml`.

Windows public HTTPS checks: Sub2API root 200 (HTML), public settings 200/code 0,
unauthenticated admin accounts 401/UNAUTHORIZED. Existing api /v1/models still
returns expected 401 without a key. No authenticated public login or model generation
was performed. NapCat public DNS initially failed; subsequent NapCat/AstrBot HTTPS
checks timed out, including a check using existing API DNS for the edge connection.
Origin HTTP remains reachable (NapCat root redirects, AstrBot root returns 200).
Do not claim these two public dashboards have passed verification; DNS/TLS/edge
connectivity and browser login/WebSocket checks remain pending.

### NapCat/AstrBot public timeout diagnosis

Follow-up confirmed DNS and TLS work for both public names. Robot origins return
200 directly and ingress rule matching is correct. The cloudflared container has
HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:7890 but NO_PROXY=localhost,127.0.0.1 only.
Robot origins use 100.84.98.125, unlike Sub2API's loopback origin. Controlled
AstrBot requests returned 200 with proxy bypass and timed out using that proxy.
Proxy handling of origin traffic is therefore the leading cause, not robot downtime.
Container Compose source: /opt/cloudflared/docker-compose.yml. Proposed fix:
add exact laptop IP 100.84.98.125 to proxy bypass and recreate only the cloudflared
container, preserving its external proxy. No robot restart or configuration change
was performed during diagnosis; public regression is pending the fix.

### Proxy bypass repair completed — 2026-10-21 Asia/Shanghai

With explicit owner approval to recreate `cloudflared-cloudflared-1`, applied
`ops/fix_tunnel_proxy_bypass.py`. Added 100.84.98.125 to NO_PROXY and matching
lowercase no_proxy in /opt/cloudflared/docker-compose.yml. Preserved tunnel egress
proxy and used --pull never; container image ID is unchanged. AstrBot and NapCat
container IDs are unchanged and neither service was restarted. Compose and ingress
configuration validation passed. Backup retained:
`/opt/cloudflared/docker-compose.before-proxy-bypass-20261020T162419Z.yml`.

Public HTTPS regression from Windows passed:

- Sub2API root 200 HTML; unauthenticated admin accounts 401/UNAUTHORIZED.
- NapCat /webui/ 200 HTML; unauthenticated login-info returns code -1, no data.
- AstrBot root 200 HTML; unauthenticated config endpoint 401.
- Model API /v1/models still returns expected 401/API_KEY_REQUIRED without a key.

This resolves the prior public dashboard HTTP timeouts and supports proxy bypass as
the cause. Authenticated browser workflows and WebSocket functionality still require
owner acceptance; no bot actions, model inference or credential changes were made.
No backup/source files were deleted; no commit/push was created.
