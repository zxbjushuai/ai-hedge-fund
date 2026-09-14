"""Unified run-scoped LLM clients and provider construction."""

from __future__ import annotations

import os
from typing import Any

from v2.llm.adapter_registry import validate_vendor_protocol
from v2.llm.base import ChatLLM, LLMClient, ResponsesLLM, normalize_response_content
from v2.llm.registry import PROVIDERS, normalize_provider, provider_spec, validate_selection
from v2.llm.types import LlmProtocol, LlmRuntimeConfig


def credential_from_environment(provider: str) -> str | None:
    spec = provider_spec(provider)
    return next((os.getenv(name) for name in spec.credential_names if os.getenv(name)), None)


def make_connection_llm(config: LlmRuntimeConfig) -> LLMClient:
    """Compose one vendor policy with one wire-protocol implementation."""
    vendor, protocol = validate_vendor_protocol(config.vendor, config.protocol)
    return protocol.create_client(config, vendor)


def make_llm(
    provider: str,
    model: str,
    credential: str | None = None,
    base_url: str | None = None,
    allow_unregistered_model: bool = False,
    timeout: float = 60.0,
    max_tokens: int = 4096,
    session_id: str | None = None,
) -> LLMClient:
    if allow_unregistered_model:
        provider_id = normalize_provider(provider)
        model_id = model.strip()
        if not model_id:
            raise ValueError("LLM model is empty")
    else:
        provider_id, model_id = validate_selection(provider, model)
    spec = provider_spec(provider_id)
    api_key = credential or credential_from_environment(provider_id)
    if spec.requires_credential and not api_key:
        names = " or ".join(spec.credential_names)
        raise ValueError(
            f"{spec.display_name} credential is missing. Configure {names} in Settings or the environment."
        )

    managed = {
        "openai": ("openai", LlmProtocol.OPENAI_CHAT),
        "anthropic": ("anthropic", LlmProtocol.ANTHROPIC_MESSAGES),
        "opencode_go": ("opencode_go", LlmProtocol.OPENAI_CHAT),
        "opencode_go_responses": ("opencode_go", LlmProtocol.OPENAI_RESPONSES),
        "modelscope": ("modelscope", LlmProtocol.OPENAI_CHAT),
    }
    if provider_id in managed:
        vendor_id, protocol_id = managed[provider_id]
        vendor, _ = validate_vendor_protocol(vendor_id, protocol_id)
        resolved_base_url = base_url
        if provider_id == "openai":
            resolved_base_url = resolved_base_url or os.getenv("OPENAI_API_BASE")
        elif provider_id == "modelscope":
            resolved_base_url = (
                resolved_base_url or os.getenv("MODELSCOPE_BASE_URL")
                or os.getenv("V2_LLM_BASE_URL")
            )
        normalized_base_url = vendor.normalize_base_url(
            resolved_base_url or "", protocol_id,
        )
        resolved_session_id = session_id or vendor.new_session_id()
        return make_connection_llm(LlmRuntimeConfig(
            vendor=vendor_id,
            protocol=protocol_id,
            model=model_id,
            base_url=normalized_base_url,
            api_key=api_key or "",
            session_id=resolved_session_id,
            timeout=timeout,
            max_tokens=max_tokens,
        ))

    if provider_id == "deepseek":
        from langchain_deepseek import ChatDeepSeek
        chat = ChatDeepSeek(model=model_id, api_key=api_key, timeout=timeout, max_retries=1, max_tokens=max_tokens)
    elif provider_id == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        chat = ChatGoogleGenerativeAI(model=model_id, api_key=api_key, timeout=timeout, max_retries=1)
    elif provider_id == "groq":
        from langchain_groq import ChatGroq
        chat = ChatGroq(model=model_id, api_key=api_key, timeout=timeout, max_retries=1, max_tokens=max_tokens)
    elif provider_id == "xai":
        from langchain_xai import ChatXAI
        chat = ChatXAI(model=model_id, api_key=api_key, timeout=timeout, max_retries=1, max_tokens=max_tokens)
    elif provider_id == "ollama":
        from langchain_ollama import ChatOllama
        ollama_host = os.getenv("OLLAMA_HOST", "localhost")
        chat = ChatOllama(
            model=model_id,
            base_url=os.getenv("OLLAMA_BASE_URL", f"http://{ollama_host}:11434"),
        )
    else:
        from langchain_openai import ChatOpenAI
        kwargs: dict[str, Any] = {
            "model": model_id, "api_key": api_key, "timeout": timeout,
            "max_retries": 1, "max_tokens": max_tokens,
        }
        if provider_id == "openrouter":
            kwargs["base_url"] = os.getenv("OPENROUTER_BASE_URL") or os.getenv("V2_LLM_BASE_URL") or spec.base_url
            kwargs["default_headers"] = {
                "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "https://github.com/virattt/ai-hedge-fund"),
                "X-Title": os.getenv("OPENROUTER_APP_NAME", "AI Hedge Fund Simulation"),
            }
        elif provider_id == "kimi":
            kwargs["base_url"] = os.getenv("MOONSHOT_BASE_URL") or os.getenv("KIMI_BASE_URL") or spec.base_url
        chat = ChatOpenAI(**kwargs)
    return ChatLLM(
        provider_id, LlmProtocol.OPENAI_CHAT.value, model_id, chat,
        session_id=session_id,
    )


def get_llm() -> LLMClient:
    requested = os.getenv("V2_LLM_PROVIDER", "").strip()
    if requested:
        provider = normalize_provider(requested)
    else:
        provider = next(
            (candidate for candidate in ("openrouter", "modelscope", "deepseek", "anthropic")
             if credential_from_environment(candidate)),
            "anthropic",
        )
    model = os.getenv("V2_LLM_MODEL") or PROVIDERS[provider].default_model
    return make_llm(provider, model)


def AnthropicLLM(model: str | None = None, **kwargs) -> ChatLLM:  # noqa: N802
    return make_llm("anthropic", model or PROVIDERS["anthropic"].default_model, **kwargs)


def DeepSeekLLM(model: str | None = None, **kwargs) -> ChatLLM:  # noqa: N802
    return make_llm("deepseek", model or PROVIDERS["deepseek"].default_model, **kwargs)


def ModelScopeLLM(model: str | None = None, **kwargs) -> ChatLLM:  # noqa: N802
    return make_llm("modelscope", model or PROVIDERS["modelscope"].default_model, **kwargs)


def OpenRouterLLM(model: str | None = None, **kwargs) -> ChatLLM:  # noqa: N802
    return make_llm("openrouter", model or PROVIDERS["openrouter"].default_model, **kwargs)
