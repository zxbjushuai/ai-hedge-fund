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


PROVIDERS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec("anthropic", "Anthropic", ("ANTHROPIC_API_KEY",), "claude-sonnet-5"),
    "deepseek": ProviderSpec("deepseek", "DeepSeek", ("DEEPSEEK_API_KEY",), "deepseek-chat"),
    "google": ProviderSpec("google", "Google", ("GOOGLE_API_KEY",), "gemini-3.1-pro-preview"),
    "groq": ProviderSpec("groq", "Groq", ("GROQ_API_KEY",), "llama-3.3-70b-versatile"),
    "kimi": ProviderSpec("kimi", "Kimi", ("MOONSHOT_API_KEY", "KIMI_API_KEY"), "kimi-k2.6", "https://api.moonshot.ai/v1"),
    "modelscope": ProviderSpec("modelscope", "ModelScope", ("MODELSCOPE_API_KEY", "MODELSCOPE_SDK_TOKEN"), "Qwen/Qwen3-4B", "https://api-inference.modelscope.cn/v1/"),
    "ollama": ProviderSpec("ollama", "Ollama", (), "llama3.1:latest", "http://localhost:11434"),
    "openai": ProviderSpec("openai", "OpenAI", ("OPENAI_API_KEY",), "gpt-5.6"),
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
