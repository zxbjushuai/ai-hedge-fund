"""Provider registry/factory tests. No test makes a network request."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from v2.llm import (
    LlmProtocol,
    LlmRuntimeConfig,
    load_models,
    make_connection_llm,
    make_llm,
    normalize_response_content,
    validate_selection,
)
from v2.llm.base import AnthropicMessagesLLM
from v2.llm.adapter_registry import validate_vendor_protocol
from v2.llm.registry import PROVIDERS


def test_registry_has_a_constructible_model_for_every_provider():
    by_provider = {entry.provider: entry.model for entry in load_models()}
    assert set(by_provider) == set(PROVIDERS)
    for provider, model in by_provider.items():
        llm = make_llm(provider, model, credential="test-key-not-real")
        expected_provider = "opencode_go" if provider == "opencode_go_responses" else provider
        assert llm.provider == expected_provider
        assert llm.model == model
        assert llm.identity == f"{expected_provider}:{llm.protocol}:{model}"


def test_selection_rejects_cross_provider_model():
    with pytest.raises(ValueError, match="not registered"):
        validate_selection("anthropic", "gpt-5.6")


def test_ollama_accepts_a_dynamically_discovered_model():
    assert validate_selection("ollama", "qwen3:14b") == ("ollama", "qwen3:14b")


def test_missing_credential_names_provider_setting(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OpenAI credential is missing.*OPENAI_API_KEY"):
        make_llm("openai", "gpt-5.6")


def test_opencode_go_uses_stable_header_per_client_and_new_session_per_client(monkeypatch):
    import langchain_openai

    calls = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def invoke(self, _messages):
            return SimpleNamespace(content="ok")

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", FakeChatOpenAI)
    first = make_llm(
        "opencode_go", "deepseek-v4-flash", credential="test-key",
    )
    second = make_llm(
        "opencode_go", "deepseek-v4-flash", credential="test-key",
    )

    assert first.session_id == calls[0]["default_headers"]["x-opencode-session"]
    assert second.session_id == calls[1]["default_headers"]["x-opencode-session"]
    assert first.session_id != second.session_id
    assert calls[0]["default_headers"]["User-Agent"] == "ai-hedge-fund/2.0"
    assert str(UUID(first.session_id)) == first.session_id


def test_opencode_go_responses_uses_responses_api_and_low_reasoning(monkeypatch):
    import openai

    clients = []
    requests = []

    class FakeResponses:
        def create(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(output_text='{"signal":"neutral"}', status="completed")

    class FakeOpenAI:
        def __init__(self, **kwargs):
            clients.append(kwargs)
            self.responses = FakeResponses()

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    llm = make_llm(
        "opencode_go_responses", "gpt-5.6-luna", credential="test-key",
    )

    assert llm.complete("system", "user") == '{"signal":"neutral"}'
    assert llm.session_id == clients[0]["default_headers"]["x-opencode-session"]
    assert clients[0]["default_headers"]["User-Agent"] == "ai-hedge-fund/2.0"
    assert requests == [{
        "model": "gpt-5.6-luna",
        "instructions": "system",
        "input": "user",
        "max_output_tokens": 4096,
        "reasoning": {"effort": "low"},
    }]


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
        ChatLLM(
            "anthropic", "anthropic_messages", "claude-fable-5", chat,
        ).complete("s", "u")


@pytest.mark.parametrize(("vendor", "protocol"), [
    ("openai", LlmProtocol.OPENAI_CHAT),
    ("openai", LlmProtocol.OPENAI_RESPONSES),
    ("anthropic", LlmProtocol.ANTHROPIC_MESSAGES),
    ("modelscope", LlmProtocol.OPENAI_CHAT),
    ("modelscope", LlmProtocol.ANTHROPIC_MESSAGES),
    ("opencode_go", LlmProtocol.OPENAI_CHAT),
    ("opencode_go", LlmProtocol.OPENAI_RESPONSES),
])
def test_vendor_protocol_matrix_accepts_supported_combinations(vendor, protocol):
    selected_vendor, selected_protocol = validate_vendor_protocol(vendor, protocol)
    assert selected_vendor.id == vendor
    assert selected_protocol.id == protocol


def test_vendor_protocol_matrix_rejects_unsupported_combination():
    with pytest.raises(ValueError, match="does not support anthropic_messages"):
        validate_vendor_protocol("openai", LlmProtocol.ANTHROPIC_MESSAGES)


def test_anthropic_compatible_client_uses_messages_wire_format(monkeypatch):
    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "content": [
                    {"type": "thinking", "thinking": "hidden"},
                    {"type": "text", "text": "OK"},
                ],
                "stop_reason": "end_turn",
            }

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr("v2.llm.base.httpx.post", fake_post)
    client = make_connection_llm(LlmRuntimeConfig(
        vendor="modelscope",
        protocol=LlmProtocol.ANTHROPIC_MESSAGES,
        model="Qwen/Qwen3.5-35B-A3B",
        base_url="https://api-inference.modelscope.cn",
        api_key="test-key-not-real",
        timeout=12.0,
        max_tokens=32,
    ))

    assert isinstance(client, AnthropicMessagesLLM)
    assert client.complete("system", "user") == "OK"
    url, request = calls[0]
    assert url == "https://api-inference.modelscope.cn/v1/messages"
    assert request["headers"]["x-api-key"] == "test-key-not-real"
    assert request["json"] == {
        "model": "Qwen/Qwen3.5-35B-A3B",
        "system": "system",
        "messages": [{"role": "user", "content": "user"}],
        "max_tokens": 32,
    }
    assert request["follow_redirects"] is False
