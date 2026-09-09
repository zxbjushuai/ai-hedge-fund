# Proposal: Unify v2 LLM Providers

## Why

The v2 simulation previously selected its LLM from process-global environment
variables. The first Workstream 2 implementation added a static provider/model
picker, but it did not give users a way to configure a named endpoint or obtain
the models actually available from that endpoint.

## What Changes

- Add a v2-owned provider/model registry and a single `make_llm` factory.
- Normalize text and content-block responses before JSON parsing.
- Add managed, named OpenAI/Anthropic connections with a Base URL and write-only
  API key. Multiple connections may use the same protocol.
- Test connections, synchronize and cache remote model lists, and support manual
  model IDs for compatible endpoints without a Models API.
- Make provider/model explicit per simulation and inject one run-scoped client
  into all persona agents.
- Persist provider/model and a non-secret connection snapshot, including legacy nulls.
- Select an enabled connection first and then one of its enabled models.

## Scope

The transport registry retains Anthropic, OpenAI, DeepSeek, Google, xAI, Kimi,
Groq, Ollama, ModelScope, and OpenRouter. Managed connection UI is intentionally
limited to OpenAI and Anthropic protocols. Streaming, per-persona selection,
automatic fallback, and full cycle audit are excluded.
