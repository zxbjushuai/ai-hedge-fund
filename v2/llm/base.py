"""Stable client contract and response wrappers shared by all transports."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import httpx


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
        text = normalize_response_content(result.content)
        if not text.strip():
            raise ValueError(f"{self.provider} returned an empty text response")
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
        if not text.strip():
            status = getattr(result, "status", None)
            details = getattr(result, "incomplete_details", None)
            reason = getattr(details, "reason", None) if details is not None else None
            suffix = f" ({status}: {reason})" if status or reason else ""
            raise ValueError(f"{self.provider} returned an empty text response{suffix}")
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
        if 300 <= response.status_code < 400:
            raise ValueError("LLM endpoint redirect refused to protect the API key")
        if response.status_code >= 400:
            raise ValueError(f"LLM endpoint returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError("LLM endpoint returned an invalid response") from exc
        if not isinstance(payload, dict):
            raise ValueError("LLM endpoint returned an invalid response")
        text = normalize_response_content(payload.get("content"))
        if not text.strip():
            stop_reason = payload.get("stop_reason")
            suffix = f" ({stop_reason})" if stop_reason else ""
            raise ValueError(
                f"{self.provider} returned an empty text response{suffix}"
            )
        return text
