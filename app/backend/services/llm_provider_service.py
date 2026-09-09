"""Persistence, validation, and model discovery for managed LLM connections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.backend.database.connection import Base, engine
from app.backend.database.models import ApiKey, LlmProviderConnection, LlmProviderModel
from v2.llm.registry import models_for


SUPPORTED_PROVIDER_TYPES = {"openai", "anthropic"}
DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}
LEGACY_KEYS = {
    "openai": ("OPENAI_API_KEY", "OpenAI Default"),
    "anthropic": ("ANTHROPIC_API_KEY", "Anthropic Default"),
}


@dataclass(frozen=True)
class ProviderConnectionSnapshot:
    id: int
    name: str
    provider_type: str
    base_url: str
    api_key: str


def ensure_provider_tables(db: Session | None = None) -> None:
    Base.metadata.create_all(bind=db.get_bind() if db is not None else engine)
    if db is not None:
        migrate_legacy_connections(db)


def normalize_base_url(value: str, provider_type: str) -> str:
    provider = provider_type.strip().lower()
    if provider not in SUPPORTED_PROVIDER_TYPES:
        raise ValueError("provider_type must be openai or anthropic")
    raw = value.strip() or DEFAULT_BASE_URLS[provider]
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base_url must be an absolute HTTP or HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base_url cannot contain credentials, query, or fragment")
    if parsed.scheme == "http" and not _is_local_http_host(parsed.hostname):
        raise ValueError("public LLM endpoints must use HTTPS")
    return raw.rstrip("/")


def _is_local_http_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


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
                provider_type=provider,
                base_url=DEFAULT_BASE_URLS[provider],
                api_key=legacy.key_value,
                enabled=True,
            ))
    db.commit()


def mask_key(value: str) -> str:
    suffix = value[-4:] if value else ""
    return f"••••{suffix}" if suffix else ""


def connection_dict(connection: LlmProviderConnection) -> dict:
    return {
        "id": connection.id,
        "name": connection.name,
        "provider_type": connection.provider_type,
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
    return ProviderConnectionSnapshot(
        id=connection.id,
        name=connection.name,
        provider_type=connection.provider_type,
        base_url=connection.base_url,
        api_key=connection.api_key,
    )


async def discover_models(connection: LlmProviderConnection) -> list[dict[str, str]]:
    headers = {"accept": "application/json"}
    if connection.provider_type == "openai":
        headers["authorization"] = f"Bearer {connection.api_key}"
        url = f"{connection.base_url.rstrip('/')}/models"
    else:
        headers["x-api-key"] = connection.api_key
        headers["anthropic-version"] = "2023-06-01"
        root = connection.base_url.rstrip("/")
        url = f"{root}/models" if root.endswith("/v1") else f"{root}/v1/models"

    discovered: dict[str, str] = {}
    params: dict[str, str | int] = (
        {"limit": 100} if connection.provider_type == "anthropic" else {}
    )
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        for _ in range(10):
            response = await client.get(url, headers=headers, params=params)
            if 300 <= response.status_code < 400:
                raise ValueError("model endpoint redirect refused to protect the API key")
            if response.status_code >= 400:
                raise ValueError(f"model endpoint returned HTTP {response.status_code}")
            try:
                payload = response.json()
                rows = payload["data"]
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError("model endpoint returned an invalid response") from exc
            if not isinstance(rows, list):
                raise ValueError("model endpoint returned an invalid model list")
            for row in rows:
                if not isinstance(row, dict):
                    continue
                model_id = str(row.get("id", "")).strip()
                if model_id:
                    discovered[model_id] = str(row.get("display_name") or model_id)
            if connection.provider_type != "anthropic" or not payload.get("has_more"):
                break
            last_id = payload.get("last_id")
            if not last_id:
                break
            params["after_id"] = str(last_id)
            if len(discovered) >= 1000:
                break
    return [
        {"model_id": model_id, "display_name": display_name}
        for model_id, display_name in sorted(discovered.items())
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
    known = {item.model for item in models_for(connection.provider_type)}
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
