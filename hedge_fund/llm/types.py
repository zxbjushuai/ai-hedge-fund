"""Provider-independent types for run-scoped LLM connections."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LlmProtocol(str, Enum):
    OPENAI_CHAT = "openai_chat_completions"
    OPENAI_RESPONSES = "openai_responses"
    ANTHROPIC_MESSAGES = "anthropic_messages"


@dataclass(frozen=True)
class LlmRuntimeConfig:
    vendor: str
    protocol: LlmProtocol
    model: str
    base_url: str
    api_key: str
    session_id: str | None = None
    timeout: float = 60.0
    max_tokens: int = 4096


@dataclass(frozen=True)
class DiscoveredModel:
    model_id: str
    display_name: str
