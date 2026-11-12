# Proposal: Add Provider Bootstrap Script

## Why

Creating or rotating a managed LLM connection currently requires either the Web
settings form, a one-off Sub2API-specific script, or direct database edits. Those
paths are not a safe or repeatable way to rebuild a fresh `providers.db`, and key
rotation has no documented operator procedure.

## What Changes

- Add `scripts/bootstrap_llm_provider.py`, an idempotent CLI that creates or
  updates a provider connection and one enabled model through the existing
  `/dashboard/llm/providers` API.
- Read the secret from an environment variable or an env file; never accept it
  as a command-line argument or print it.
- Verify the result through `/dashboard/llm/options` so success means the model
  is usable by simulations, not merely persisted.
- Add offline tests for create, update, key rotation, kind conflicts, and a
  fresh isolated provider database.
- Document initial setup and key rotation without recording secrets.

## Compatibility

The change is additive. It uses the current provider and model API contract,
does not require a schema migration, and leaves the existing Sub2API helper in
place. An existing connection with the same name but a different vendor/protocol
is rejected rather than silently rewritten because the update API does not
change connection kind.

## Non-goals

- Storing, encrypting, or rotating secrets outside the existing provider DB and
  operator-managed env file.
- Calling a paid model endpoint during bootstrap verification.
- Replacing the Web settings UI or deleting the legacy Sub2API helper.
- Managing more than one connection/model in a single invocation.
