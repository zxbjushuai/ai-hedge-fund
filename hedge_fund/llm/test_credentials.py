from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from research_app.backend.database.models import ApiKey, Base
from research_app.backend.services.v2_llm_service import credential_configured, resolve_credential


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_database_credential_wins_over_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    session = _session()
    try:
        session.add(ApiKey(provider="OPENAI_API_KEY", key_value="database-secret", is_active=True))
        session.commit()
        assert resolve_credential("openai", session) == "database-secret"
        assert credential_configured("openai", session) is True
    finally:
        session.close()


def test_inactive_database_credential_falls_back_to_environment(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-secret")
    session = _session()
    try:
        session.add(ApiKey(provider="DEEPSEEK_API_KEY", key_value="inactive", is_active=False))
        session.commit()
        assert resolve_credential("deepseek", session) == "environment-secret"
    finally:
        session.close()


def test_ollama_needs_no_secret():
    session = _session()
    try:
        assert resolve_credential("ollama", session) is None
        assert credential_configured("ollama", session) is True
    finally:
        session.close()
