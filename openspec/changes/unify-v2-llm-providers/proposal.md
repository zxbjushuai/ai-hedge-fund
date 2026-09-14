# Proposal: Unify v2 LLM Providers

## Why

The v2 simulation previously selected its LLM from process-global environment
variables. The first Workstream 2 implementation added a static provider/model
picker, but it did not give users a way to configure a named endpoint or obtain
the models actually available from that endpoint.

## What Changes

- Add a v2-owned provider/model registry and a single `make_llm` factory.
- Normalize text and content-block responses before JSON parsing.
- Model a connection as independent `vendor + protocol` fields instead of
  encoding both concerns in a growing `provider_type` enum. Compose vendor
  policy with polymorphic OpenAI Chat Completions, OpenAI Responses, or
  Anthropic Messages transports.
- Add managed named connections with a Base URL and write-only API key.
  OpenAI, Anthropic, OpenCode Go, ModelScope, and custom compatible endpoints
  expose only the protocols each vendor supports.
- Test connections, synchronize and cache remote model lists, and support manual
  model IDs for compatible endpoints without a Models API.
- Make provider/model explicit per simulation and inject one run-scoped client
  into all persona agents.
- Persist provider/model and a non-secret connection snapshot, including legacy nulls.
- Select an enabled connection first and then one of its enabled models.

## Scope

The legacy transport registry retains Anthropic, OpenAI, DeepSeek, Google, xAI,
Kimi, Groq, Ollama, ModelScope, and OpenRouter. Managed connections use the new
vendor/protocol composition. Streaming, per-persona selection, automatic
fallback, and full cycle audit are excluded.
