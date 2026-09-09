"""LLM provider protocol + the Anthropic and DeepSeek implementations.

Mirrors the DataClient pattern (v2/data/protocol.py): agents depend on the
`LLMClient` protocol, never a concrete provider. Any class with a
`complete(system, user) -> str` method plugs in — community providers welcome.

We deliberately do NOT use langchain's structured-output machinery: its
forced-tool mode breaks on Anthropic reasoning models (v1 carries the same
workaround). We ask for JSON in the prompt and parse it ourselves.
"""

from __future__ import annotations

import json
import os
import re
from typing import Protocol, runtime_checkable

DEFAULT_MODEL = "claude-sonnet-5"
DEEPSEEK_DEFAULT_MODEL = "deepseek-chat"
MODELSCOPE_DEFAULT_MODEL = "Qwen/Qwen3-4B"
MODELSCOPE_DEFAULT_BASE_URL = "https://api-inference.modelscope.cn/v1/"
OPENROUTER_DEFAULT_MODEL = "openrouter/free"
OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class LLMParseError(ValueError):
    """The model's response did not contain parseable JSON."""


@runtime_checkable
class LLMClient(Protocol):
    """Protocol all LLM providers must satisfy.

    complete() returns the model's raw text. Providers should raise on
    transport failure — the LLMAgent layer decides to abstain, not the
    provider.
    """

    model: str

    def complete(self, system: str, user: str) -> str: ...


class AnthropicLLM:
    """Anthropic provider via the existing langchain-anthropic dependency
    (transport only — no structured-output magic)."""

    def __init__(
        self,
        model: str | None = None,
        timeout: float = 60.0,
        max_tokens: int = 1024,
    ) -> None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not found. Set it in your .env to use LLM agents."
            )
        from langchain_anthropic import ChatAnthropic

        self.model = model or os.getenv("V2_LLM_MODEL", DEFAULT_MODEL)
        self._chat = ChatAnthropic(
            model=self.model,
            api_key=api_key,
            timeout=timeout,
            max_retries=1,
            max_tokens=max_tokens,
        )

    def complete(self, system: str, user: str) -> str:
        result = self._chat.invoke([("system", system), ("human", user)])
        content = result.content
        # Anthropic reasoning models return a list of content blocks.
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        return content


class DeepSeekLLM:
    """DeepSeek provider via langchain-deepseek."""

    def __init__(
        self,
        model: str | None = None,
        timeout: float = 60.0,
        max_tokens: int = 1024,
    ) -> None:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY not found. Set it in your .env or environment to use LLM agents."
            )
        from langchain_deepseek import ChatDeepSeek

        self.model = model or os.getenv("V2_LLM_MODEL", DEEPSEEK_DEFAULT_MODEL)
        self._chat = ChatDeepSeek(
            model=self.model,
            api_key=api_key,
            timeout=timeout,
            max_retries=1,
            max_tokens=max_tokens,
        )

    def complete(self, system: str, user: str) -> str:
        result = self._chat.invoke([("system", system), ("human", user)])
        content = result.content
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        return content


class ModelScopeLLM:
    """ModelScope hosted inference through its OpenAI-compatible endpoint."""

    def __init__(
        self,
        model: str | None = None,
        timeout: float = 60.0,
        max_tokens: int = 1024,
    ) -> None:
        api_key = os.getenv("MODELSCOPE_API_KEY") or os.getenv("MODELSCOPE_SDK_TOKEN")
        if not api_key:
            raise ValueError(
                "MODELSCOPE_API_KEY not found. Restart the backend after setting the user environment variable."
            )
        from openai import OpenAI

        self.model = model or os.getenv("V2_LLM_MODEL", MODELSCOPE_DEFAULT_MODEL)
        self._max_tokens = max_tokens
        self._client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("V2_LLM_BASE_URL", MODELSCOPE_DEFAULT_BASE_URL),
            timeout=timeout,
            max_retries=1,
        )

    def complete(self, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=self._max_tokens,
            temperature=0.2,
            extra_body={"enable_thinking": False},
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("ModelScope returned an empty response")
        return content


class OpenRouterLLM:
    """OpenRouter inference through its OpenAI-compatible endpoint."""

    def __init__(self, model: str | None = None, timeout: float = 60.0, max_tokens: int = 1024) -> None:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENROUTER_API_KEY not found. Restart the backend after setting the environment variable."
            )
        from openai import OpenAI

        self.model = model or os.getenv("V2_LLM_MODEL", OPENROUTER_DEFAULT_MODEL)
        self._max_tokens = max_tokens
        self._client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("V2_LLM_BASE_URL", OPENROUTER_DEFAULT_BASE_URL),
            timeout=timeout,
            max_retries=1,
            default_headers={
                "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "https://github.com/virattt/ai-hedge-fund"),
                "X-Title": os.getenv("OPENROUTER_APP_NAME", "AI Hedge Fund Simulation"),
            },
        )

    def complete(self, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=self._max_tokens,
            temperature=0.2,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("OpenRouter returned an empty response")
        return content


def get_llm() -> LLMClient:
    """Return the configured LLM client based on environment variables.

    Priority:
      1. V2_LLM_PROVIDER env var (e.g. 'openrouter', 'modelscope', 'deepseek')
      2. OPENROUTER_API_KEY present -> OpenRouterLLM
      3. MODELSCOPE_API_KEY present -> ModelScopeLLM
      4. DEEPSEEK_API_KEY present -> DeepSeekLLM
      5. Fallback to AnthropicLLM (will raise if no key)
    """
    provider = os.getenv("V2_LLM_PROVIDER", "").lower()
    if provider == "openrouter":
        return OpenRouterLLM()
    if provider == "modelscope":
        return ModelScopeLLM()
    if provider == "deepseek":
        return DeepSeekLLM()
    if provider == "anthropic":
        return AnthropicLLM()
    if os.getenv("OPENROUTER_API_KEY"):
        return OpenRouterLLM()
    if os.getenv("MODELSCOPE_API_KEY") or os.getenv("MODELSCOPE_SDK_TOKEN"):
        return ModelScopeLLM()
    if os.getenv("DEEPSEEK_API_KEY"):
        return DeepSeekLLM()
    return AnthropicLLM()


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response.

    Tries: ```json fence -> whole string -> first balanced {...} block.
    Raises LLMParseError if nothing parses.
    """
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass

    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break

    raise LLMParseError(f"no JSON object found in response: {text[:200]!r}")


# Unified implementations override the legacy definitions above while keeping
# direct imports from v2.llm.client backward compatible.
from v2.llm.providers import (  # noqa: E402,F401
    AnthropicLLM,
    ChatLLM,
    DeepSeekLLM,
    LLMClient,
    ModelScopeLLM,
    OpenRouterLLM,
    get_llm,
    make_llm,
    normalize_response_content,
)
