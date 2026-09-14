"""Persistence, validation, and model discovery for managed LLM connections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.backend.database.connection import Base, engine
from app.backend.database.models import ApiKey, LlmProviderConnection, LlmProviderModel
from v2.llm.adapter_registry import validate_vendor_protocol
from v2.llm.registry import (
    connection_kind_for_legacy,
    legacy_provider_type,
    models_for_connection,
)
from v2.llm.types import LlmProtocol, LlmRuntimeConfig


SUPPORTED_PROVIDER_TYPES = {
    "openai", "openai_responses", "anthropic", "opencode_go",
    "opencode_go_responses", "modelscope", "modelscope_anthropic",
}
DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "opencode_go": "https://opencode.ai/zen/go/v1",
    "opencode_go_responses": "https://opencode.ai/zen/go/v1",
    "modelscope": "https://api-inference.modelscope.cn/v1",
    "modelscope_anthropic": "https://api-inference.modelscope.cn",
}
LEGACY_KEYS = {
    "openai": ("OPENAI_API_KEY", "OpenAI Default"),
    "anthropic": ("ANTHROPIC_API_KEY", "Anthropic Default"),
}

@dataclass(frozen=True)
class ProviderConnectionSnapshot:
    id: int
    name: str
    vendor: str
    protocol: str
    base_url: str
    api_key: str

    @property
    def provider_type(self) -> str:
        """Legacy discriminator retained for old API callers."""
        return legacy_provider_type(self.vendor, self.protocol)


def ensure_provider_tables(db: Session | None = None) -> None:
    Base.metadata.create_all(bind=db.get_bind() if db is not None else engine)
    if db is not None:
        _ensure_connection_columns(db)
        migrate_legacy_connections(db)
        migrate_connection_kinds(db)


def _ensure_connection_columns(db: Session) -> None:
    """Add the two new columns for installs that do not invoke Alembic."""
    columns = {
        column["name"]
        for column in inspect(db.get_bind()).get_columns("llm_provider_connections")
    }
    changed = False
    if "vendor" not in columns:
        db.execute(text(
            "ALTER TABLE llm_provider_connections ADD COLUMN vendor VARCHAR(32)"
        ))
        changed = True
    if "protocol" not in columns:
        db.execute(text(
            "ALTER TABLE llm_provider_connections ADD COLUMN protocol VARCHAR(40)"
        ))
        changed = True
    if changed:
        db.commit()


def normalize_connection_base_url(
    value: str, vendor: str, protocol: str,
) -> str:
    vendor_adapter, _ = validate_vendor_protocol(vendor, protocol)
    return vendor_adapter.normalize_base_url(value, LlmProtocol(protocol))


def normalize_base_url(value: str, provider_type: str) -> str:
    """Compatibility wrapper for old provider_type callers."""
    vendor, protocol = connection_kind_for_legacy(provider_type)
    return normalize_connection_base_url(value, vendor, protocol)


def migrate_legacy_connections(db: Session) -> None:
    """Copy active legacy OpenAI/Anthropic keys once without deleting them."""
    for provider, (key_name, connection_name) in LEGACY_KEYS.items():
        exists = db.query(LlmProviderConnection).filter(
            LlmProviderConnection.name == connection_name
        ).first()
        if exists:
            continue
        legacy = db.query(ApiKey).filter(
            ApiKey.provider == key_name,
            ApiKey.is_active.is_(True),
        ).first()
        if legacy and legacy.key_value:
            db.add(LlmProviderConnection(
                name=connection_name,
                vendor=provider,
                protocol=connection_kind_for_legacy(provider)[1],
                provider_type=provider,
                base_url=DEFAULT_BASE_URLS[provider],
                api_key=legacy.key_value,
                enabled=True,
            ))
    db.commit()


def migrate_connection_kinds(db: Session) -> None:
    """Idempotently backfill vendor/protocol for pre-split connection rows."""
    rows = db.query(LlmProviderConnection).all()
    changed = False
    for row in rows:
        try:
            vendor, protocol = connection_kind_for_legacy(row.provider_type)
        except ValueError:
            vendor, protocol = row.provider_type, LlmProtocol.OPENAI_CHAT.value
        if not row.vendor:
            row.vendor = vendor
            changed = True
        if not row.protocol:
            row.protocol = protocol
            changed = True
    if changed:
        db.commit()


def connection_kind(connection: LlmProviderConnection) -> tuple[str, str]:
    if connection.vendor and connection.protocol:
        return connection.vendor, connection.protocol
    return connection_kind_for_legacy(connection.provider_type)


def mask_key(value: str) -> str:
    suffix = value[-4:] if value else ""
    return f"••••{suffix}" if suffix else ""


def connection_dict(connection: LlmProviderConnection) -> dict:
    vendor, protocol = connection_kind(connection)
    return {
        "id": connection.id,
        "name": connection.name,
        "provider_type": connection.provider_type,
        "vendor": vendor,
        "protocol": protocol,
        "base_url": connection.base_url,
        "enabled": connection.enabled,
        "has_api_key": bool(connection.api_key),
        "api_key_masked": mask_key(connection.api_key),
        "last_tested_at": connection.last_tested_at,
        "last_test_status": connection.last_test_status,
        "last_error": connection.last_error,
        "last_synced_at": connection.last_synced_at,
        "created_at": connection.created_at,
        "updated_at": connection.updated_at,
    }


def model_dict(model: LlmProviderModel) -> dict:
    return {
        "id": model.id,
        "connection_id": model.connection_id,
        "model_id": model.model_id,
        "display_name": model.display_name,
        "source": model.source,
        "enabled": model.enabled,
        "available": model.available,
        "last_seen_at": model.last_seen_at,
    }


def get_connection(db: Session, connection_id: int) -> LlmProviderConnection:
    ensure_provider_tables(db)
    connection = db.get(LlmProviderConnection, connection_id)
    if connection is None:
        raise LookupError("LLM provider connection not found")
    return connection


def resolve_connection(
    db: Session, connection_id: int, model_id: str
) -> ProviderConnectionSnapshot:
    connection = get_connection(db, connection_id)
    if not connection.enabled:
        raise ValueError("LLM provider connection is disabled")
    if not connection.api_key:
        raise ValueError("LLM provider connection has no API key")
    model = db.query(LlmProviderModel).filter(
        LlmProviderModel.connection_id == connection.id,
        LlmProviderModel.model_id == model_id,
        LlmProviderModel.enabled.is_(True),
    ).first()
    if model is None or (model.source == "remote" and not model.available):
        raise ValueError("model is not enabled and available for this connection")
    vendor, protocol = connection_kind(connection)
    validate_vendor_protocol(vendor, protocol)
    return ProviderConnectionSnapshot(
        id=connection.id,
        name=connection.name,
        vendor=vendor,
        protocol=protocol,
        base_url=connection.base_url,
        api_key=connection.api_key,
    )


async def discover_models(connection: LlmProviderConnection) -> list[dict[str, str]]:
    vendor_id, protocol_id = connection_kind(connection)
    vendor, protocol = validate_vendor_protocol(vendor_id, protocol_id)
    config = LlmRuntimeConfig(
        vendor=vendor.id,
        protocol=protocol.id,
        model="",
        base_url=connection.base_url,
        api_key=connection.api_key,
        timeout=15.0,
    )
    discovered = await protocol.discover_models(config, vendor)
    return [
        {"model_id": model.model_id, "display_name": model.display_name}
        for model in discovered
    ]


async def test_connection(db: Session, connection: LlmProviderConnection) -> list[dict[str, str]]:
    try:
        models = await discover_models(connection)
    except Exception as exc:
        connection.last_tested_at = datetime.now(timezone.utc)
        connection.last_test_status = "failed"
        connection.last_error = str(exc)
        db.commit()
        raise
    connection.last_tested_at = datetime.now(timezone.utc)
    connection.last_test_status = "success"
    connection.last_error = None
    db.commit()
    return models


async def sync_models(db: Session, connection: LlmProviderConnection) -> list[LlmProviderModel]:
    discovered = await test_connection(db, connection)
    now = datetime.now(timezone.utc)
    all_rows = db.query(LlmProviderModel).filter(
        LlmProviderModel.connection_id == connection.id,
    ).all()
    remote_rows = [row for row in all_rows if row.source == "remote"]
    by_id = {row.model_id: row for row in all_rows}
    discovered_ids = {item["model_id"] for item in discovered}
    vendor, protocol = connection_kind(connection)
    known = {item.model for item in models_for_connection(vendor, protocol)}
    for row in remote_rows:
        row.available = row.model_id in discovered_ids
    for item in discovered:
        row = by_id.get(item["model_id"])
        if row is not None and row.source == "manual":
            continue
        if row is None:
            row = LlmProviderModel(
                connection_id=connection.id,
                model_id=item["model_id"],
                display_name=item["display_name"],
                source="remote",
                enabled=item["model_id"] in known,
            )
            db.add(row)
        else:
            row.display_name = item["display_name"]
        row.available = True
        row.last_seen_at = now
    connection.last_synced_at = now
    db.commit()
    return db.query(LlmProviderModel).filter(
        LlmProviderModel.connection_id == connection.id
    ).order_by(LlmProviderModel.display_name).all()
