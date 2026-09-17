"""Polymorphic wire-protocol transports and model-catalog discovery."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from hedge_fund.llm.base import AnthropicMessagesLLM, ChatLLM, LLMClient, ResponsesLLM
from hedge_fund.llm.types import DiscoveredModel, LlmProtocol, LlmRuntimeConfig
from hedge_fund.llm.vendors import VendorAdapter


class ProtocolAdapter(ABC):
    id: LlmProtocol

    @abstractmethod
    def create_client(
        self, config: LlmRuntimeConfig, vendor: VendorAdapter,
    ) -> LLMClient:
        raise NotImplementedError

    @abstractmethod
    async def discover_models(
        self, config: LlmRuntimeConfig, vendor: VendorAdapter,
    ) -> list[DiscoveredModel]:
        raise NotImplementedError


class OpenAICompatibleProtocolAdapter(ProtocolAdapter):
    async def discover_models(
        self, config: LlmRuntimeConfig, vendor: VendorAdapter,
    ) -> list[DiscoveredModel]:
        headers = {
            "accept": "application/json",
            "authorization": f"Bearer {config.api_key}",
            **vendor.extra_headers(config.session_id, catalog=True),
        }
        payload = await _get_json(
            f"{config.base_url.rstrip('/')}/models", headers=headers,
            timeout=min(config.timeout, 15.0),
        )
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ValueError("model endpoint returned an invalid model list")
        return _models_from_rows(rows)


class OpenAIChatCompletionsAdapter(OpenAICompatibleProtocolAdapter):
    id = LlmProtocol.OPENAI_CHAT

    def create_client(
        self, config: LlmRuntimeConfig, vendor: VendorAdapter,
    ) -> LLMClient:
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": config.model,
            "api_key": config.api_key,
            "base_url": config.base_url,
            "timeout": config.timeout,
            "max_retries": 1,
            "max_tokens": config.max_tokens,
        }
        headers = vendor.extra_headers(config.session_id)
        if headers:
            kwargs["default_headers"] = headers
        kwargs.update(vendor.chat_options())
        return ChatLLM(
            config.vendor, config.protocol.value, config.model,
            ChatOpenAI(**kwargs), session_id=config.session_id,
        )


class OpenAIResponsesAdapter(OpenAICompatibleProtocolAdapter):
    id = LlmProtocol.OPENAI_RESPONSES

    def create_client(
        self, config: LlmRuntimeConfig, vendor: VendorAdapter,
    ) -> LLMClient:
        from openai import OpenAI

        kwargs: dict[str, Any] = {
            "api_key": config.api_key,
            "base_url": config.base_url,
            "timeout": config.timeout,
            "max_retries": 1,
        }
        headers = vendor.extra_headers(config.session_id)
        if headers:
            kwargs["default_headers"] = headers
        return ResponsesLLM(
            config.vendor, config.protocol.value, config.model,
            OpenAI(**kwargs), session_id=config.session_id,
            max_output_tokens=config.max_tokens,
        )


class AnthropicMessagesAdapter(ProtocolAdapter):
    id = LlmProtocol.ANTHROPIC_MESSAGES

    def create_client(
        self, config: LlmRuntimeConfig, vendor: VendorAdapter,
    ) -> LLMClient:
        headers = vendor.extra_headers(config.session_id)
        return AnthropicMessagesLLM(
            config.vendor,
            config.protocol.value,
            config.model,
            config.base_url,
            config.api_key,
            default_headers=headers,
            session_id=config.session_id,
            timeout=config.timeout,
            max_tokens=config.max_tokens,
        )

    async def discover_models(
        self, config: LlmRuntimeConfig, vendor: VendorAdapter,
    ) -> list[DiscoveredModel]:
        headers = {
            "accept": "application/json",
            "x-api-key": config.api_key,
            "anthropic-version": "2023-06-01",
            **vendor.extra_headers(config.session_id, catalog=True),
        }
        root = config.base_url.rstrip("/")
        url = f"{root}/models" if root.endswith("/v1") else f"{root}/v1/models"
        params: dict[str, str | int] = {"limit": 100}
        discovered: dict[str, DiscoveredModel] = {}
        for _ in range(10):
            payload = await _get_json(
                url, headers=headers, params=params,
                timeout=min(config.timeout, 15.0),
            )
            rows = payload.get("data")
            if not isinstance(rows, list):
                raise ValueError("model endpoint returned an invalid model list")
            for model in _models_from_rows(rows):
                discovered[model.model_id] = model
            if not payload.get("has_more"):
                break
            last_id = payload.get("last_id")
            if not last_id or len(discovered) >= 1000:
                break
            params["after_id"] = str(last_id)
        return [discovered[key] for key in sorted(discovered)]


async def _get_json(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    params: dict[str, str | int] | None = None,
) -> dict:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.get(url, headers=headers, params=params or {})
    if 300 <= response.status_code < 400:
        raise ValueError("model endpoint redirect refused to protect the API key")
    if response.status_code >= 400:
        raise ValueError(f"model endpoint returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("model endpoint returned an invalid response") from exc
    if not isinstance(payload, dict):
        raise ValueError("model endpoint returned an invalid response")
    return payload


def _models_from_rows(rows: list) -> list[DiscoveredModel]:
    discovered: dict[str, DiscoveredModel] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("id", "")).strip()
        if model_id:
            discovered[model_id] = DiscoveredModel(
                model_id=model_id,
                display_name=str(row.get("display_name") or model_id),
            )
    return [discovered[key] for key in sorted(discovered)]
