# Handoff: Recover Stale Runtime State

Implemented the startup recovery path from `proposal.md` and `design.md`.
Running simulations are failed idempotently, process-local cache jobs are failed
and cancelled, and `/dashboard/system/status` exposes recovery plus runtime
counts. Regression tests cover direct recovery, cache cleanup, and the real
FastAPI lifespan. The full backend/frontend verification suite passes.

The OpenSpec CLI is not installed in this environment, so the change artifacts
are maintained directly in the repository's existing `openspec/changes/` format.
