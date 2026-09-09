"""v2 LLM layer — provider protocol, Anthropic/DeepSeek clients, prompt cache."""

from v2.llm.cache import PromptCache, prompt_key
from v2.llm.client import DEFAULT_MODEL, LLMParseError, extract_json
from v2.llm.providers import (
    AnthropicLLM, ChatLLM, DeepSeekLLM, LLMClient, ModelScopeLLM,
    OpenRouterLLM, get_llm, make_llm, normalize_response_content,
)
from v2.llm.registry import catalog, load_models, provider_spec, validate_selection

__all__ = [
    "AnthropicLLM",
    "ChatLLM",
    "DeepSeekLLM",
    "DEFAULT_MODEL",
    "LLMClient",
    "LLMParseError",
    "ModelScopeLLM",
    "OpenRouterLLM",
    "PromptCache",
    "extract_json",
    "get_llm",
    "make_llm",
    "normalize_response_content",
    "prompt_key",
    "catalog",
    "load_models",
    "provider_spec",
    "validate_selection",
]
