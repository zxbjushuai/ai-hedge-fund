"""Registries for independently selected vendor and protocol strategies."""

from __future__ import annotations

from v2.llm.protocols import (
    AnthropicMessagesAdapter,
    OpenAIChatCompletionsAdapter,
    OpenAIResponsesAdapter,
    ProtocolAdapter,
)
from v2.llm.types import LlmProtocol
from v2.llm.vendors import (
    AnthropicVendor,
    CustomVendor,
    ModelScopeVendor,
    OpenAIVendor,
    OpenCodeGoVendor,
    VendorAdapter,
)


VENDORS: dict[str, VendorAdapter] = {
    adapter.id: adapter for adapter in (
        OpenAIVendor(), AnthropicVendor(), OpenCodeGoVendor(),
        ModelScopeVendor(), CustomVendor(),
    )
}
PROTOCOLS: dict[LlmProtocol, ProtocolAdapter] = {
    adapter.id: adapter for adapter in (
        OpenAIChatCompletionsAdapter(), OpenAIResponsesAdapter(),
        AnthropicMessagesAdapter(),
    )
}


def get_vendor(vendor_id: str) -> VendorAdapter:
    key = vendor_id.strip().lower()
    try:
        return VENDORS[key]
    except KeyError as exc:
        raise ValueError(
            f"unsupported LLM vendor {vendor_id!r}; available: {', '.join(VENDORS)}"
        ) from exc


def get_protocol(protocol_id: str | LlmProtocol) -> ProtocolAdapter:
    try:
        key = protocol_id if isinstance(protocol_id, LlmProtocol) else LlmProtocol(protocol_id)
        return PROTOCOLS[key]
    except (KeyError, ValueError) as exc:
        raise ValueError(f"unsupported LLM protocol {protocol_id!r}") from exc


def validate_vendor_protocol(
    vendor_id: str, protocol_id: str | LlmProtocol,
) -> tuple[VendorAdapter, ProtocolAdapter]:
    vendor = get_vendor(vendor_id)
    protocol = get_protocol(protocol_id)
    if protocol.id not in vendor.supported_protocols:
        raise ValueError(f"{vendor.display_name} does not support {protocol.id.value}")
    return vendor, protocol
