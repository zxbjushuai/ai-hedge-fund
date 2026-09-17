"""Canonical v2 LLM provider and model registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    display_name: str
    credential_names: tuple[str, ...]
    default_model: str
    base_url: str | None = None

    @property
    def requires_credential(self) -> bool:
        return bool(self.credential_names)


@dataclass(frozen=True)
class ModelSpec:
    display_name: str
    model: str
    provider: str
    vendor: str | None = None
    protocol: str | None = None


PROVIDERS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec("anthropic", "Anthropic", ("ANTHROPIC_API_KEY",), "claude-sonnet-5"),
    "deepseek": ProviderSpec("deepseek", "DeepSeek", ("DEEPSEEK_API_KEY",), "deepseek-chat"),
    "google": ProviderSpec("google", "Google", ("GOOGLE_API_KEY",), "gemini-3.1-pro-preview"),
    "groq": ProviderSpec("groq", "Groq", ("GROQ_API_KEY",), "llama-3.3-70b-versatile"),
    "kimi": ProviderSpec("kimi", "Kimi", ("MOONSHOT_API_KEY", "KIMI_API_KEY"), "kimi-k2.6", "https://api.moonshot.ai/v1"),
    "modelscope": ProviderSpec("modelscope", "ModelScope", ("MODELSCOPE_API_KEY", "MODELSCOPE_SDK_TOKEN"), "Qwen/Qwen3.5-35B-A3B", "https://api-inference.modelscope.cn/v1/"),
    "ollama": ProviderSpec("ollama", "Ollama", (), "llama3.1:latest", "http://localhost:11434"),
    "openai": ProviderSpec("openai", "OpenAI", ("OPENAI_API_KEY",), "gpt-5.6"),
    "opencode_go": ProviderSpec(
        "opencode_go",
        "OpenCode Go (Chat Completions)",
        ("OPENCODE_GO_API_KEY",),
        "deepseek-v4-flash",
        "https://opencode.ai/zen/go/v1",
    ),
    "opencode_go_responses": ProviderSpec(
        "opencode_go_responses",
        "OpenCode Go (Responses)",
        ("OPENCODE_GO_API_KEY",),
        "gpt-5.6-luna",
        "https://opencode.ai/zen/go/v1",
    ),
    "openrouter": ProviderSpec("openrouter", "OpenRouter", ("OPENROUTER_API_KEY",), "openrouter/free", "https://openrouter.ai/api/v1"),
    "xai": ProviderSpec("xai", "xAI", ("XAI_API_KEY",), "grok-4.3"),
}

_ALIASES = {
    **{key: key for key in PROVIDERS},
    **{spec.display_name.lower(): key for key, spec in PROVIDERS.items()},
    "model_scope": "modelscope",
    "open_router": "openrouter",
}
_MODEL_PATH = Path(__file__).with_name("api_models.json")

LEGACY_CONNECTION_KINDS = {
    "openai": ("openai", "openai_chat_completions"),
    "openai_responses": ("openai", "openai_responses"),
    "anthropic": ("anthropic", "anthropic_messages"),
    "opencode_go": ("opencode_go", "openai_chat_completions"),
    "opencode_go_responses": ("opencode_go", "openai_responses"),
    "modelscope": ("modelscope", "openai_chat_completions"),
    "modelscope_anthropic": ("modelscope", "anthropic_messages"),
}


def normalize_provider(provider: str) -> str:
    key = provider.strip().lower().replace("-", "_")
    try:
        return _ALIASES[key]
    except KeyError as exc:
        raise ValueError(
            f"unsupported LLM provider {provider!r}; available: {', '.join(PROVIDERS)}"
        ) from exc


def provider_spec(provider: str) -> ProviderSpec:
    return PROVIDERS[normalize_provider(provider)]


def load_models() -> list[ModelSpec]:
    try:
        raw = json.loads(_MODEL_PATH.read_text(encoding="utf-8"))
        models = [ModelSpec(**entry) for entry in raw]
    except (OSError, ValueError, KeyError, TypeError):
        models = []
    return [model for model in models if model.provider in PROVIDERS]


def models_for(provider: str) -> list[ModelSpec]:
    provider_id = normalize_provider(provider)
    return [model for model in load_models() if model.provider == provider_id]


def connection_kind_for_legacy(provider_type: str) -> tuple[str, str]:
    key = provider_type.strip().lower()
    try:
        return LEGACY_CONNECTION_KINDS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported legacy provider_type {provider_type!r}") from exc


def legacy_provider_type(vendor: str, protocol: str) -> str:
    pair = (vendor.strip().lower(), protocol.strip())
    for provider_type, kind in LEGACY_CONNECTION_KINDS.items():
        if kind == pair:
            return provider_type
    return pair[0]


def models_for_connection(vendor: str, protocol: str) -> list[ModelSpec]:
    result = []
    for model in load_models():
        model_vendor = model.vendor
        model_protocol = model.protocol
        if model_vendor is None or model_protocol is None:
            try:
                model_vendor, model_protocol = connection_kind_for_legacy(model.provider)
            except ValueError:
                continue
        if (model_vendor, model_protocol) == (vendor, protocol):
            result.append(model)
    return result


def validate_selection(provider: str, model: str) -> tuple[str, str]:
    provider_id = normalize_provider(provider)
    model_id = model.strip()
    if not model_id:
        raise ValueError("LLM model is empty")
    if provider_id == "ollama":
        return provider_id, model_id  # discovered dynamically from the local daemon
    registered = {entry.model for entry in models_for(provider_id)}
    if model_id not in registered:
        raise ValueError(
            f"model {model_id!r} is not registered for {provider_id}; "
            f"available: {', '.join(sorted(registered)) or 'none'}"
        )
    return provider_id, model_id


def catalog() -> list[dict]:
    entries = load_models()
    return [
        {
            "id": provider.id,
            "display_name": provider.display_name,
            "credential_names": list(provider.credential_names),
            "models": [
                {"display_name": model.display_name, "model": model.model}
                for model in entries if model.provider == provider.id
            ],
        }
        for provider in PROVIDERS.values()
    ]
from pathlib import Path

API_MODELS_PATH = Path(__file__).resolve().parent / "api_models.json"

# Provider names are the strings used in api_models.json.
PROVIDER_ENV_VARS = {
    "Anthropic": "ANTHROPIC_API_KEY",
    "OpenAI": "OPENAI_API_KEY",
    "xAI": "XAI_API_KEY",
    "DeepSeek": "DEEPSEEK_API_KEY",
    "Google": "GOOGLE_API_KEY",
    "Kimi": "KIMI_API_KEY",
}

# Providers v2 has a client for (see client.py:make_llm). Anything in the
# registry but missing here is shown in the picker and not selectable — better
# a greyed row than a run that dies on an id the transport rejects.
SUPPORTED_PROVIDERS = frozenset(PROVIDER_ENV_VARS)

_FALLBACK = ("Opus 5", "claude-opus-5", "Anthropic")


def load_api_models() -> list[tuple[str, str, str]]:
    """The registry as (display name, model id, provider), file order kept.

    Falls back to the built-in default alone if the file is missing or
    malformed — a broken registry should cost you the picker, not the app.
    """
    try:
        entries = json.loads(API_MODELS_PATH.read_text())
        models = [(e["display_name"], e.get("model_name", e.get("model")),
                   {"openai": "OpenAI", "anthropic": "Anthropic", "xai": "xAI", "google": "Google", "deepseek": "DeepSeek", "kimi": "Kimi"}.get(e["provider"], e["provider"]))
                  for e in entries if e["provider"].lower() in {p.lower() for p in SUPPORTED_PROVIDERS}]
    except (OSError, ValueError, KeyError, TypeError):
        return [_FALLBACK]
    return models or [_FALLBACK]


def provider_for(model_id: str) -> str | None:
    """Which provider serves a model id. None if it is not in the registry —
    a hand-exported HEDGE_FUND_LLM_MODEL should not be second-guessed."""
    return next((prov for _, mid, prov in load_api_models() if mid == model_id),
                None)


def env_var_for(provider: str) -> str | None:
    """The environment variable a provider's key is read from."""
    return PROVIDER_ENV_VARS.get(provider)


def is_supported(provider: str) -> bool:
    """Can v2 actually talk to this provider?"""
    return provider in SUPPORTED_PROVIDERS
