"""Provider registry/factory tests. No test makes a network request."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from v2.llm import load_models, make_llm, normalize_response_content, validate_selection
from v2.llm.registry import PROVIDERS


def test_registry_has_a_constructible_model_for_every_provider():
    by_provider = {entry.provider: entry.model for entry in load_models()}
    assert set(by_provider) == set(PROVIDERS)
    for provider, model in by_provider.items():
        llm = make_llm(provider, model, credential="test-key-not-real")
        assert llm.provider == provider
        assert llm.model == model
        assert llm.identity == f"{provider}:{model}"


def test_selection_rejects_cross_provider_model():
    with pytest.raises(ValueError, match="not registered"):
        validate_selection("anthropic", "gpt-5.6")


def test_ollama_accepts_a_dynamically_discovered_model():
    assert validate_selection("ollama", "qwen3:14b") == ("ollama", "qwen3:14b")


def test_missing_credential_names_provider_setting(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OpenAI credential is missing.*OPENAI_API_KEY"):
        make_llm("openai", "gpt-5.6")


@pytest.mark.parametrize("content, expected", [
    ('{"signal":"neutral"}', '{"signal":"neutral"}'),
    ([{"type": "thinking", "thinking": "secret"},
      {"type": "text", "text": '{"signal":"bullish"}'}],
     '{"signal":"bullish"}'),
    ([SimpleNamespace(type="reasoning", text="ignore"),
      SimpleNamespace(type="output_text", text=SimpleNamespace(value="answer"))],
     "answer"),
    (["a", "b"], "a\nb"),
    ({"type": "text", "text": "single"}, "single"),
    ({"type": "reasoning", "text": "hidden"}, ""),
])
def test_response_normalization_drops_non_answer_blocks(content, expected):
    assert normalize_response_content(content) == expected


def test_chat_wrapper_rejects_reasoning_only_response():
    from v2.llm.providers import ChatLLM

    chat = SimpleNamespace(invoke=lambda messages: SimpleNamespace(
        content=[{"type": "thinking", "thinking": "hidden"}]
    ))
    with pytest.raises(ValueError, match="empty text response"):
        ChatLLM("anthropic", "claude-fable-5", chat).complete("s", "u")
