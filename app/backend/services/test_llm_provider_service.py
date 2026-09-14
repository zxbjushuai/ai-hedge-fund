from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.connection import Base
from app.backend.database.models import ApiKey, LlmProviderConnection, LlmProviderModel
from app.backend.services import llm_provider_service as service
from v2.llm import protocols as protocol_module


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_base_url_policy():
    assert service.normalize_base_url("https://proxy.example/v1/", "openai") == "https://proxy.example/v1"
    assert service.normalize_base_url("http://localhost:8000/v1", "openai")
    assert service.normalize_base_url("http://192.168.1.8:8000", "anthropic")
    with pytest.raises(ValueError, match="HTTPS"):
        service.normalize_base_url("http://api.example/v1", "openai")
    with pytest.raises(ValueError, match="credentials"):
        service.normalize_base_url("https://user:pass@example.com/v1", "openai")
    with pytest.raises(ValueError, match="query"):
        service.normalize_base_url("https://example.com/v1?key=secret", "openai")
    assert service.normalize_base_url("", "opencode_go") == service.DEFAULT_BASE_URLS["opencode_go"]
    assert service.normalize_base_url("", "opencode_go_responses") == service.DEFAULT_BASE_URLS["opencode_go_responses"]
    assert service.normalize_base_url("https://proxy.example/v1", "opencode_go") == "https://proxy.example/v1"
    assert service.normalize_base_url("https://proxy.example/v1", "opencode_go_responses") == "https://proxy.example/v1"


def test_legacy_key_migration_is_idempotent_and_does_not_remove_key(db):
    db.add(ApiKey(provider="OPENAI_API_KEY", key_value="sk-legacy", is_active=True))
    db.commit()
    service.migrate_legacy_connections(db)
    service.migrate_legacy_connections(db)
    connections = db.query(LlmProviderConnection).all()
    assert len(connections) == 1
    assert connections[0].name == "OpenAI Default"
    assert connections[0].api_key == "sk-legacy"
    assert db.query(ApiKey).filter_by(provider="OPENAI_API_KEY").one().key_value == "sk-legacy"


def test_runtime_backfill_does_not_infer_vendor_from_base_url(db):
    row = LlmProviderConnection(
        name="Existing Go", provider_type="openai",
        base_url="https://opencode.ai/zen/go/v1/", api_key="secret",
    )
    db.add(row)
    db.flush()
    db.add(LlmProviderModel(
        connection_id=row.id, model_id="gpt-5.6-luna", display_name="GPT",
        source="remote", enabled=True, available=True,
    ))
    db.commit()

    service.migrate_connection_kinds(db)
    service.migrate_connection_kinds(db)

    db.refresh(row)
    assert row.provider_type == "openai"
    assert row.vendor == "openai"
    assert row.protocol == "openai_chat_completions"
    assert row.api_key == "secret"
    cached = db.query(LlmProviderModel).filter_by(
        connection_id=row.id, model_id="gpt-5.6-luna",
    ).one()
    assert cached.enabled is True
    assert cached.available is True


def test_database_migration_reclassifies_only_legacy_official_go_url(db, monkeypatch):
    from importlib import import_module

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    official = LlmProviderConnection(
        name="Legacy Official Go",
        provider_type="openai",
        vendor="openai",
        protocol="openai_chat_completions",
        base_url="https://opencode.ai/zen/go/v1/",
        api_key="official-secret",
    )
    proxy = LlmProviderConnection(
        name="OpenAI-compatible Proxy",
        provider_type="openai",
        vendor="openai",
        protocol="openai_chat_completions",
        base_url="https://proxy.example/v1",
        api_key="proxy-secret",
    )
    db.add_all([official, proxy])
    db.commit()

    migration = import_module(
        "app.backend.alembic.versions."
        "b7d9e2a4c631_migrate_legacy_opencode_go_connections"
    )
    operations = Operations(MigrationContext.configure(db.connection()))
    monkeypatch.setattr(migration, "op", operations)
    migration.upgrade()
    db.expire_all()

    assert official.provider_type == "opencode_go"
    assert official.vendor == "opencode_go"
    assert official.protocol == "openai_chat_completions"
    assert official.api_key == "official-secret"
    assert proxy.provider_type == "openai"
    assert proxy.vendor == "openai"
    assert proxy.api_key == "proxy-secret"


def test_go_responses_legacy_connection_is_backfilled_without_cloning(db):
    source = LlmProviderConnection(
        name="Existing Go Responses", provider_type="opencode_go_responses",
        base_url=service.DEFAULT_BASE_URLS["opencode_go_responses"], api_key="secret",
        enabled=True,
    )
    db.add(source)
    db.flush()
    db.add(LlmProviderModel(
        connection_id=source.id, model_id="gpt-5.6-luna", display_name="GPT",
        source="remote", enabled=False, available=False,
    ))
    db.commit()

    service.migrate_connection_kinds(db)
    service.migrate_connection_kinds(db)

    targets = db.query(LlmProviderConnection).filter_by(
        vendor="opencode_go", protocol="openai_responses",
    ).all()
    assert len(targets) == 1
    assert db.query(LlmProviderConnection).count() == 1
    assert targets[0].api_key == "secret"
    model = db.query(LlmProviderModel).filter_by(
        connection_id=targets[0].id, model_id="gpt-5.6-luna",
    ).one()
    assert model.enabled is False
    assert model.available is False


def test_connection_response_never_exposes_secret(db):
    row = LlmProviderConnection(
        name="Private", provider_type="openai",
        base_url="https://example.com/v1", api_key="top-secret-1234",
    )
    db.add(row)
    db.commit()
    result = service.connection_dict(row)
    assert "api_key" not in result
    assert result["api_key_masked"] == "••••1234"
    assert "top-secret" not in str(result)


def test_resolve_requires_enabled_available_model(db):
    connection = LlmProviderConnection(
        name="OpenAI", provider_type="openai",
        base_url="https://api.openai.com/v1", api_key="secret", enabled=True,
    )
    db.add(connection)
    db.flush()
    model = LlmProviderModel(
        connection_id=connection.id, model_id="gpt-custom", display_name="Custom",
        source="manual", enabled=True, available=True,
    )
    db.add(model)
    db.commit()
    snapshot = service.resolve_connection(db, connection.id, "gpt-custom")
    assert snapshot.name == "OpenAI"
    assert snapshot.api_key == "secret"
    model.enabled = False
    db.commit()
    with pytest.raises(ValueError, match="not enabled"):
        service.resolve_connection(db, connection.id, "gpt-custom")


def test_sync_preserves_manual_models_and_marks_missing_remote_unavailable(db, monkeypatch):
    connection = LlmProviderConnection(
        name="Anthropic", provider_type="anthropic",
        base_url="https://api.anthropic.com", api_key="secret", enabled=True,
    )
    db.add(connection)
    db.flush()
    db.add_all([
        LlmProviderModel(connection_id=connection.id, model_id="old", display_name="Old", source="remote", enabled=True, available=True),
        LlmProviderModel(connection_id=connection.id, model_id="manual", display_name="Manual", source="manual", enabled=True, available=True),
    ])
    db.commit()

    async def fake_discover(_connection):
        return [
            {"model_id": "claude-sonnet-5", "display_name": "Claude Sonnet 5"},
            {"model_id": "manual", "display_name": "Remote collision"},
        ]

    monkeypatch.setattr(service, "discover_models", fake_discover)
    rows = asyncio.run(service.sync_models(db, connection))
    by_id = {row.model_id: row for row in rows}
    assert by_id["old"].available is False
    assert by_id["manual"].source == "manual"
    assert by_id["manual"].display_name == "Manual"
    assert by_id["claude-sonnet-5"].enabled is True


def test_failed_sync_keeps_cached_models_and_records_safe_error(db, monkeypatch):
    connection = LlmProviderConnection(
        name="Broken", provider_type="openai",
        base_url="https://api.example/v1", api_key="do-not-leak", enabled=True,
    )
    db.add(connection)
    db.flush()
    db.add(LlmProviderModel(
        connection_id=connection.id, model_id="cached", display_name="Cached",
        source="remote", enabled=True, available=True,
    ))
    db.commit()

    async def fail(_connection):
        raise ValueError("model endpoint returned HTTP 401")

    monkeypatch.setattr(service, "discover_models", fail)
    with pytest.raises(ValueError, match="401"):
        asyncio.run(service.sync_models(db, connection))
    assert db.query(LlmProviderModel).filter_by(model_id="cached").one().available is True
    db.refresh(connection)
    assert connection.last_test_status == "failed"
    assert "do-not-leak" not in (connection.last_error or "")


def test_provider_crud_and_options_never_return_key(db):
    from app.backend.routes import dashboard

    created = dashboard.create_llm_provider(dashboard.LlmProviderCreateRequest(
        name="Official", provider_type="openai",
        base_url="https://api.openai.com/v1", api_key="secret-value", enabled=True,
    ), db)
    assert "api_key" not in created
    assert "secret-value" not in str(created)
    updated = dashboard.update_llm_provider(created["id"], dashboard.LlmProviderUpdateRequest(
        name="Official Renamed", api_key="",
    ), db)
    assert updated["name"] == "Official Renamed"
    assert db.get(LlmProviderConnection, created["id"]).api_key == "secret-value"

    dashboard.create_llm_provider_model(created["id"], dashboard.LlmModelCreateRequest(
        model_id="gpt-private",
    ), db)
    db.add(LlmProviderModel(
        connection_id=created["id"], model_id="gpt-old", display_name="Old",
        source="remote", enabled=True, available=True,
    ))
    db.commit()
    dashboard.update_llm_provider(created["id"], dashboard.LlmProviderUpdateRequest(
        base_url="https://new.example/v1",
    ), db)
    assert db.query(LlmProviderModel).filter_by(model_id="gpt-old").one().available is False
    assert db.query(LlmProviderModel).filter_by(model_id="gpt-private").one().available is True
    options = dashboard.llm_options(db)
    assert options == {"providers": [{
        "id": created["id"], "name": "Official Renamed", "provider_type": "openai",
        "vendor": "openai", "protocol": "openai_chat_completions",
        "models": [{"model_id": "gpt-private", "display_name": "gpt-private"}],
    }]}


def test_managed_resolution_passes_immutable_connection_values(db, monkeypatch):
    from types import SimpleNamespace
    from app.backend.routes import dashboard
    import app.backend.database.connection as connection_module
    import v2.llm

    connection = LlmProviderConnection(
        name="Proxy", provider_type="openai",
        base_url="https://proxy.example/v1", api_key="connection-secret", enabled=True,
    )
    db.add(connection)
    db.flush()
    db.add(LlmProviderModel(
        connection_id=connection.id, model_id="private/model", display_name="Private",
        source="manual", enabled=True, available=True,
    ))
    db.commit()
    monkeypatch.setattr(connection_module, "SessionLocal", lambda: db)
    captured = []

    def fake_make(config):
        captured.append(config)
        return SimpleNamespace(provider=config.vendor, protocol=config.protocol.value, model=config.model)

    monkeypatch.setattr(v2.llm, "make_connection_llm", fake_make)
    request = dashboard.SimRunRequest(
        tickers=["AAPL"], start_date="2025-01-01", end_date="2025-01-02",
        initial_capital=1000, llm_connection_id=connection.id, model="private/model",
    )
    resolved = dashboard._resolve_simulation_llm(request, required=True)
    assert (resolved.connection_id, resolved.connection_name, resolved.base_url) == (
        connection.id, "Proxy", "https://proxy.example/v1",
    )
    assert len(captured) == 1
    assert captured[0].vendor == "openai"
    assert captured[0].protocol.value == "openai_chat_completions"
    assert captured[0].model == "private/model"
    assert captured[0].api_key == "connection-secret"
    assert captured[0].base_url == "https://proxy.example/v1"


@pytest.mark.parametrize(("provider_type", "model_id"), [
    ("opencode_go", "deepseek-v4-flash"),
    ("opencode_go_responses", "gpt-5.6-luna"),
])
def test_opencode_go_resolution_creates_a_new_session_for_each_simulation(
    db, monkeypatch, provider_type, model_id,
):
    from types import SimpleNamespace
    from app.backend.routes import dashboard
    import app.backend.database.connection as connection_module
    import v2.llm

    connection = LlmProviderConnection(
        name=f"Go {provider_type}", provider_type=provider_type,
        base_url=service.DEFAULT_BASE_URLS[provider_type],
        api_key="connection-secret", enabled=True,
    )
    db.add(connection)
    db.flush()
    db.add(LlmProviderModel(
        connection_id=connection.id, model_id=model_id,
        display_name=model_id, source="remote",
        enabled=True, available=True,
    ))
    db.commit()
    monkeypatch.setattr(connection_module, "SessionLocal", lambda: db)
    captured = []

    def fake_make(config):
        captured.append(config)
        return SimpleNamespace(provider=config.vendor, protocol=config.protocol.value, model=config.model)

    monkeypatch.setattr(v2.llm, "make_connection_llm", fake_make)
    request = dashboard.SimRunRequest(
        tickers=["AAPL"], start_date="2025-01-01", end_date="2025-01-02",
        initial_capital=1000, llm_connection_id=connection.id,
        model=model_id,
    )
    first = dashboard._resolve_simulation_llm(request, required=True)
    second = dashboard._resolve_simulation_llm(request, required=True)

    assert first.session_id != second.session_id
    assert captured[0].session_id == first.session_id
    assert captured[1].session_id == second.session_id
    assert str(UUID(first.session_id)) == first.session_id


def test_concurrent_managed_clients_do_not_mix_base_urls_or_keys(monkeypatch):
    import langchain_openai
    from v2.llm.providers import make_llm

    barrier = threading.Barrier(2)
    calls = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            barrier.wait(timeout=3)
            calls.append(kwargs)

        def invoke(self, _messages):
            return type("Response", (), {"content": "ok"})()

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", FakeChatOpenAI)

    def build(model, key, base_url):
        return make_llm(
            "openai", model, credential=key, base_url=base_url,
            allow_unregistered_model=True,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        clients = list(pool.map(
            lambda args: build(*args),
            [
                ("model-a", "key-a", "https://a.example/v1"),
                ("model-b", "key-b", "https://b.example/v1"),
            ],
        ))
    assert {client.identity for client in clients} == {
        "openai:openai_chat_completions:model-a",
        "openai:openai_chat_completions:model-b",
    }
    assert {(call["model"], call["api_key"], call["base_url"]) for call in calls} == {
        ("model-a", "key-a", "https://a.example/v1"),
        ("model-b", "key-b", "https://b.example/v1"),
    }


def test_openai_model_discovery_uses_configured_api_root(monkeypatch):
    requests = []

    class Response:
        status_code = 200
        def json(self):
            return {"data": [{"id": "gpt-a"}, {"id": "gpt-b"}]}

    class Client:
        def __init__(self, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def get(self, url, headers, params):
            requests.append((url, headers, params))
            return Response()

    monkeypatch.setattr(protocol_module.httpx, "AsyncClient", Client)
    connection = LlmProviderConnection(
        name="OpenAI", provider_type="openai",
        base_url="https://proxy.example/v1", api_key="secret",
    )
    result = asyncio.run(service.discover_models(connection))
    assert [item["model_id"] for item in result] == ["gpt-a", "gpt-b"]
    assert requests[0][0] == "https://proxy.example/v1/models"
    assert requests[0][1]["authorization"] == "Bearer secret"


def test_opencode_go_discovery_uses_complete_remote_snapshot(monkeypatch):
    requests = []

    class Response:
        status_code = 200
        def json(self):
            return {"data": [
                {"id": "deepseek-v4-flash"},
                {"id": "deepseek-v4.1-flash"},
                {"id": "gpt-5.6-luna"},
                {"id": "qwen3.8-max"},
            ]}

    class Client:
        def __init__(self, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def get(self, url, headers, params):
            requests.append((url, headers, params))
            return Response()

    monkeypatch.setattr(protocol_module.httpx, "AsyncClient", Client)
    connection = LlmProviderConnection(
        name="Go", provider_type="opencode_go",
        base_url=service.DEFAULT_BASE_URLS["opencode_go"], api_key="secret",
    )
    result = asyncio.run(service.discover_models(connection))

    assert [item["model_id"] for item in result] == [
        "deepseek-v4-flash",
        "deepseek-v4.1-flash",
        "gpt-5.6-luna",
        "qwen3.8-max",
    ]
    assert requests[0][0].endswith("/v1/models")
    assert requests[0][1]["authorization"] == "Bearer secret"
    assert requests[0][1]["User-Agent"] == "ai-hedge-fund/2.0"


def test_opencode_go_responses_discovery_uses_complete_remote_snapshot(monkeypatch):
    class Response:
        status_code = 200
        def json(self):
            return {"data": [
                {"id": "deepseek-v4-flash"},
                {"id": "gpt-5.6-luna"},
                {"id": "grok-4.6"},
            ]}

    class Client:
        def __init__(self, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def get(self, url, headers, params): return Response()

    monkeypatch.setattr(protocol_module.httpx, "AsyncClient", Client)
    connection = LlmProviderConnection(
        name="Go Responses", provider_type="opencode_go_responses",
        base_url=service.DEFAULT_BASE_URLS["opencode_go_responses"],
        api_key="secret",
    )
    result = asyncio.run(service.discover_models(connection))

    assert [item["model_id"] for item in result] == [
        "deepseek-v4-flash", "gpt-5.6-luna", "grok-4.6",
    ]


def test_opencode_go_sync_uses_latest_successful_snapshot(db, monkeypatch):
    connection = LlmProviderConnection(
        name="Go", provider_type="opencode_go",
        base_url=service.DEFAULT_BASE_URLS["opencode_go"], api_key="secret",
    )
    db.add(connection)
    db.flush()
    db.add_all([
        LlmProviderModel(
            connection_id=connection.id, model_id="retired-model",
            display_name="Retired", source="remote", enabled=True, available=True,
        ),
        LlmProviderModel(
            connection_id=connection.id, model_id="private-model",
            display_name="Private", source="manual", enabled=True, available=True,
        ),
    ])
    db.commit()

    async def latest_snapshot(_connection):
        return [
            {"model_id": "deepseek-v4.1-flash", "display_name": "DeepSeek V4.1 Flash"},
            {"model_id": "new-unknown", "display_name": "New Unknown"},
        ]

    monkeypatch.setattr(service, "discover_models", latest_snapshot)
    rows = asyncio.run(service.sync_models(db, connection))
    by_id = {row.model_id: row for row in rows}

    assert by_id["deepseek-v4.1-flash"].available is True
    assert by_id["deepseek-v4.1-flash"].enabled is True
    assert by_id["new-unknown"].available is True
    assert by_id["new-unknown"].enabled is False
    assert by_id["retired-model"].available is False
    assert by_id["private-model"].available is True


def test_enabled_remote_model_uses_connection_protocol_without_static_whitelist(db):
    connection = LlmProviderConnection(
        name="Go", provider_type="opencode_go",
        base_url=service.DEFAULT_BASE_URLS["opencode_go"], api_key="secret",
        enabled=True,
    )
    db.add(connection)
    db.flush()
    db.add(LlmProviderModel(
        connection_id=connection.id, model_id="future-chat-model",
        display_name="Future Chat Model", source="remote",
        enabled=True, available=True,
    ))
    db.commit()

    snapshot = service.resolve_connection(db, connection.id, "future-chat-model")

    assert snapshot.provider_type == "opencode_go"


def test_anthropic_model_discovery_follows_cursor_pagination(monkeypatch):
    requests = []
    payloads = [
        {"data": [{"id": "claude-a", "display_name": "Claude A"}], "has_more": True, "last_id": "claude-a"},
        {"data": [{"id": "claude-b", "display_name": "Claude B"}], "has_more": False},
    ]

    class Response:
        status_code = 200
        def __init__(self, payload): self.payload = payload
        def json(self): return self.payload

    class Client:
        def __init__(self, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def get(self, url, headers, params):
            requests.append((url, headers.copy(), params.copy()))
            return Response(payloads[len(requests) - 1])

    monkeypatch.setattr(protocol_module.httpx, "AsyncClient", Client)
    connection = LlmProviderConnection(
        name="Anthropic", provider_type="anthropic",
        base_url="https://api.anthropic.com", api_key="secret",
    )
    result = asyncio.run(service.discover_models(connection))
    assert [item["model_id"] for item in result] == ["claude-a", "claude-b"]
    assert requests[0][0] == "https://api.anthropic.com/v1/models"
    assert requests[0][1]["x-api-key"] == "secret"
    assert requests[0][1]["anthropic-version"] == "2023-06-01"
    assert requests[1][2]["after_id"] == "claude-a"
