"""Credential resolution for explicit v2 simulation LLM selections."""

from __future__ import annotations

import os

from sqlalchemy.orm import Session

from app.backend.repositories.api_key_repository import ApiKeyRepository
from v2.llm.registry import provider_spec


def resolve_credential(provider: str, db: Session) -> str | None:
    """Resolve one secret without exposing it or mutating os.environ."""
    spec = provider_spec(provider)
    if not spec.requires_credential:
        return None

    active = ApiKeyRepository(db).get_all_api_keys(include_inactive=False)
    stored = {row.provider.casefold(): row.key_value for row in active}
    candidates = (*spec.credential_names, spec.id, spec.display_name)
    for candidate in candidates:
        value = stored.get(candidate.casefold())
        if value:
            return value
    return next((os.getenv(name) for name in spec.credential_names if os.getenv(name)), None)


def credential_configured(provider: str, db: Session) -> bool:
    spec = provider_spec(provider)
    return not spec.requires_credential or bool(resolve_credential(provider, db))
