"""Unified run-scoped LLM clients and provider construction."""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable

from v2.llm.registry import PROVIDERS, normalize_provider, provider_spec, validate_selection


@runtime_checkable
class LLMClient(Protocol):
    provider: str
    model: str

    @property
    def identity(self) -> str: ...

    def complete(self, system: str, user: str) -> str: ...


def _block_value(block: Any, name: str) -> Any:
    return block.get(name) if isinstance(block, dict) else getattr(block, name, None)


def normalize_response_content(content: Any, separator: str = "\n") -> str:
    """Keep answer text while discarding reasoning and tool blocks."""
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, dict) or _block_value(content, "type") is not None:
        return normalize_response_content([content], separator=separator)
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if _block_value(block, "type") not in {"text", "output_text"}:
                continue
            value = _block_value(block, "text")
            if isinstance(value, dict):
                value = value.get("value", "")
            elif value is not None and not isinstance(value, str):
                value = getattr(value, "value", "")
            if value:
                parts.append(str(value))
        return separator.join(parts)
    return str(content)


class ChatLLM:
    def __init__(self, provider: str, model: str, chat: Any) -> None:
        self.provider = provider
        self.model = model
        self._chat = chat

    @property
    def identity(self) -> str:
        return f"{self.provider}:{self.model}"

    def complete(self, system: str, user: str) -> str:
        result = self._chat.invoke([("system", system), ("human", user)])
        text = normalize_response_content(result.content)
        if not text.strip():
            raise ValueError(f"{self.provider} returned an empty text response")
        return text


def credential_from_environment(provider: str) -> str | None:
    spec = provider_spec(provider)
    return next((os.getenv(name) for name in spec.credential_names if os.getenv(name)), None)


def make_llm(
    provider: str,
    model: str,
    credential: str | None = None,
    base_url: str | None = None,
    allow_unregistered_model: bool = False,
    timeout: float = 60.0,
    max_tokens: int = 4096,
) -> ChatLLM:
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

    if provider_id == "anthropic":
        from langchain_anthropic import ChatAnthropic
        chat = ChatAnthropic(
            model=model_id, api_key=api_key, base_url=base_url,
            timeout=timeout, max_retries=1, max_tokens=max_tokens,
        )
    elif provider_id == "deepseek":
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
        if provider_id == "openai":
            kwargs["base_url"] = base_url or os.getenv("OPENAI_API_BASE")
        elif provider_id == "openrouter":
            kwargs["base_url"] = os.getenv("OPENROUTER_BASE_URL") or os.getenv("V2_LLM_BASE_URL") or spec.base_url
            kwargs["default_headers"] = {
                "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "https://github.com/virattt/ai-hedge-fund"),
                "X-Title": os.getenv("OPENROUTER_APP_NAME", "AI Hedge Fund Simulation"),
            }
        elif provider_id == "modelscope":
            kwargs["base_url"] = os.getenv("MODELSCOPE_BASE_URL") or os.getenv("V2_LLM_BASE_URL") or spec.base_url
            kwargs["extra_body"] = {"enable_thinking": False}
        elif provider_id == "kimi":
            kwargs["base_url"] = os.getenv("MOONSHOT_BASE_URL") or os.getenv("KIMI_BASE_URL") or spec.base_url
        chat = ChatOpenAI(**kwargs)
    return ChatLLM(provider_id, model_id, chat)


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
