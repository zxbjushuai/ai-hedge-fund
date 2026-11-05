"""Stable client contract and response wrappers shared by all transports."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import httpx
from hedge_fund.simulation.observation import emit, http_request, http_response


class ResponseError(ValueError):
    def __init__(self, category: str, status_code: int | None = None):
        super().__init__("empty text response" if category == "empty_response" else category)
        self.diagnostic_category = category
        self.status_code = status_code


def response_metadata(result):
    metadata = getattr(result, "response_metadata", {}) or {}
    reason = metadata.get("finish_reason") or getattr(result, "stop_reason", None)
    incomplete = getattr(result, "incomplete_details", None)
    reason = reason or getattr(incomplete, "reason", None)
    usage = getattr(result, "usage_metadata", None) or getattr(result, "usage", None)
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    safe_usage = {k: v for k, v in (usage or {}).items() if isinstance(v, (int, float))} if isinstance(usage, dict) else None
    emit("response_metadata", finish_reason=reason if reason in {"stop", "length", "max_tokens", "max_output_tokens", "end_turn", "tool_calls", "content_filter"} else None, usage=safe_usage)
    if reason in {"length", "max_tokens", "max_output_tokens"}:
        raise ResponseError("truncated_response")


@runtime_checkable
class LLMClient(Protocol):
    provider: str
    protocol: str
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
    def __init__(
        self,
        provider: str,
        protocol: str,
        model: str,
        chat: Any,
        session_id: str | None = None,
    ) -> None:
        self.provider = provider
        self.protocol = protocol
        self.model = model
        self._chat = chat
        self.session_id = session_id

    @property
    def identity(self) -> str:
        return f"{self.provider}:{self.protocol}:{self.model}"

    def complete(self, system: str, user: str) -> str:
        result = self._chat.invoke([("system", system), ("human", user)])
        response_metadata(result)
        text = normalize_response_content(result.content)
        if not text.strip():
            raise ResponseError("empty_response")
        return text


class ResponsesLLM:
    def __init__(
        self,
        provider: str,
        protocol: str,
        model: str,
        client: Any,
        session_id: str | None = None,
        max_output_tokens: int = 4096,
        reasoning_effort: str = "low",
    ) -> None:
        self.provider = provider
        self.protocol = protocol
        self.model = model
        self._client = client
        self.session_id = session_id
        self.max_output_tokens = max_output_tokens
        self.reasoning_effort = reasoning_effort

    @property
    def identity(self) -> str:
        return f"{self.provider}:{self.protocol}:{self.model}"

    def complete(self, system: str, user: str) -> str:
        result = self._client.responses.create(
            model=self.model,
            instructions=system,
            input=user,
            max_output_tokens=self.max_output_tokens,
            reasoning={"effort": self.reasoning_effort},
        )
        text = normalize_response_content(getattr(result, "output_text", ""))
        response_metadata(result)
        if not text.strip():
            raise ResponseError("empty_response")
        return text


class AnthropicMessagesLLM:
    """Small protocol-native client suitable for Anthropic-compatible APIs.

    Keeping response decoding here avoids vendor-specific assumptions made by
    higher-level SDK response models while preserving the standard Messages
    wire contract.
    """

    def __init__(
        self,
        provider: str,
        protocol: str,
        model: str,
        base_url: str,
        api_key: str,
        *,
        default_headers: dict[str, str] | None = None,
        session_id: str | None = None,
        timeout: float = 60.0,
        max_tokens: int = 4096,
    ) -> None:
        self.provider = provider
        self.protocol = protocol
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_headers = dict(default_headers or {})
        self.session_id = session_id
        self.timeout = timeout
        self.max_tokens = max_tokens

    @property
    def identity(self) -> str:
        return f"{self.provider}:{self.protocol}:{self.model}"

    def complete(self, system: str, user: str) -> str:
        url = (
            f"{self.base_url}/messages"
            if self.base_url.endswith("/v1")
            else f"{self.base_url}/v1/messages"
        )
        headers = {
            "content-type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            **self.default_headers,
        }
        request = httpx.Request("POST", url)
        http_request(request)
        response = httpx.post(
            url,
            headers=headers,
            json={
                "model": self.model,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                "max_tokens": self.max_tokens,
            },
            timeout=self.timeout,
            follow_redirects=False,
        )
        http_response(response)
        if 300 <= response.status_code < 400:
            raise ValueError("LLM endpoint redirect refused to protect the API key")
        if response.status_code >= 400:
            error = ResponseError("http_error", response.status_code)
            error.response = response
            raise error
        try:
            payload = response.json()
        except ValueError as exc:
            raise ResponseError("invalid_response", response.status_code) from exc
        if not isinstance(payload, dict):
            raise ResponseError("invalid_response", response.status_code)
        from types import SimpleNamespace
        response_metadata(SimpleNamespace(stop_reason=payload.get("stop_reason"), usage=payload.get("usage")))
        text = normalize_response_content(payload.get("content"))
        if not text.strip():
            raise ResponseError("empty_response", response.status_code)
        return text
