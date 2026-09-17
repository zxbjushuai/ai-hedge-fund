"""Vendor policies composed with wire-protocol adapters."""

from __future__ import annotations

from abc import ABC
import ipaddress
from urllib.parse import urlparse
from uuid import uuid4

from hedge_fund.llm.types import LlmProtocol


class VendorAdapter(ABC):
    id: str
    display_name: str
    supported_protocols: frozenset[LlmProtocol]
    default_base_urls: dict[LlmProtocol, str]
    fixed_base_url = False
    requires_session_id = False

    def default_base_url(self, protocol: LlmProtocol) -> str:
        try:
            return self.default_base_urls[protocol]
        except KeyError as exc:
            raise ValueError(
                f"{self.display_name} does not support {protocol.value}"
            ) from exc

    def normalize_base_url(self, value: str, protocol: LlmProtocol) -> str:
        if protocol not in self.supported_protocols:
            raise ValueError(f"{self.display_name} does not support {protocol.value}")
        raw = value.strip() or self.default_base_url(protocol)
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url must be an absolute HTTP or HTTPS URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("base_url cannot contain credentials, query, or fragment")
        if parsed.scheme == "http" and not _is_local_http_host(parsed.hostname):
            raise ValueError("public LLM endpoints must use HTTPS")
        normalized = raw.rstrip("/")
        if self.fixed_base_url and normalized != self.default_base_url(protocol).rstrip("/"):
            raise ValueError(
                f"{self.display_name} base_url must be {self.default_base_url(protocol)}"
            )
        return normalized

    def new_session_id(self) -> str | None:
        return str(uuid4()) if self.requires_session_id else None

    def extra_headers(
        self, session_id: str | None = None, *, catalog: bool = False,
    ) -> dict[str, str]:
        return {}

    def chat_options(self) -> dict:
        return {}


class OpenAIVendor(VendorAdapter):
    id = "openai"
    display_name = "OpenAI"
    supported_protocols = frozenset({
        LlmProtocol.OPENAI_CHAT, LlmProtocol.OPENAI_RESPONSES,
    })
    default_base_urls = {
        LlmProtocol.OPENAI_CHAT: "https://api.openai.com/v1",
        LlmProtocol.OPENAI_RESPONSES: "https://api.openai.com/v1",
    }


class AnthropicVendor(VendorAdapter):
    id = "anthropic"
    display_name = "Anthropic"
    supported_protocols = frozenset({LlmProtocol.ANTHROPIC_MESSAGES})
    default_base_urls = {
        LlmProtocol.ANTHROPIC_MESSAGES: "https://api.anthropic.com",
    }


class OpenCodeGoVendor(VendorAdapter):
    id = "opencode_go"
    display_name = "OpenCode Go"
    supported_protocols = frozenset({
        LlmProtocol.OPENAI_CHAT, LlmProtocol.OPENAI_RESPONSES,
    })
    default_base_urls = {
        LlmProtocol.OPENAI_CHAT: "https://opencode.ai/zen/go/v1",
        LlmProtocol.OPENAI_RESPONSES: "https://opencode.ai/zen/go/v1",
    }
    requires_session_id = True

    def extra_headers(
        self, session_id: str | None = None, *, catalog: bool = False,
    ) -> dict[str, str]:
        headers = {"User-Agent": "ai-hedge-fund/2.0"}
        if not catalog:
            if not session_id:
                raise ValueError("OpenCode Go requires a simulation session ID")
            headers["x-opencode-session"] = session_id
        return headers


class ModelScopeVendor(VendorAdapter):
    id = "modelscope"
    display_name = "ModelScope"
    supported_protocols = frozenset({
        LlmProtocol.OPENAI_CHAT, LlmProtocol.ANTHROPIC_MESSAGES,
    })
    default_base_urls = {
        LlmProtocol.OPENAI_CHAT: "https://api-inference.modelscope.cn/v1",
        LlmProtocol.ANTHROPIC_MESSAGES: "https://api-inference.modelscope.cn",
    }

    def chat_options(self) -> dict:
        return {"extra_body": {"enable_thinking": False}}


class CustomVendor(VendorAdapter):
    id = "custom"
    display_name = "Custom"
    supported_protocols = frozenset(LlmProtocol)
    default_base_urls: dict[LlmProtocol, str] = {}

    def default_base_url(self, protocol: LlmProtocol) -> str:
        raise ValueError("custom connections require base_url")


def _is_local_http_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private
