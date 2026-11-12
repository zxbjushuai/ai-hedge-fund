"""Tests for the idempotent managed-provider bootstrap CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.bootstrap_llm_provider as bootstrap


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict | None]] = []

    def request(self, method: str, url: str, json: dict | None = None, timeout: float | None = None) -> FakeResponse:
        self.calls.append((method, url, json))
        if not self.responses:
            raise AssertionError(f"unexpected request: {method} {url}")
        return self.responses.pop(0)


def _config(api_key: str = "fresh-secret") -> bootstrap.ProviderBootstrapConfig:
    return bootstrap.ProviderBootstrapConfig(
        name="opencode go",
        vendor="opencode_go",
        protocol="openai_chat_completions",
        model="deepseek-v4.1-flash",
        api_key=api_key,
    )


def test_bootstrap_creates_connection_and_enables_model():
    session = FakeSession(
        [
            FakeResponse(200, {"providers": []}),
            FakeResponse(
                201,
                {
                    "id": 7,
                    "name": "opencode go",
                    "vendor": "opencode_go",
                    "protocol": "openai_chat_completions",
                    "enabled": True,
                },
            ),
            FakeResponse(200, {"models": []}),
            FakeResponse(
                201,
                {
                    "id": 9,
                    "connection_id": 7,
                    "model_id": "deepseek-v4.1-flash",
                    "enabled": True,
                },
            ),
            FakeResponse(
                200,
                {
                    "providers": [
                        {
                            "id": 7,
                            "name": "opencode go",
                            "models": [{"model_id": "deepseek-v4.1-flash"}],
                        }
                    ]
                },
            ),
        ]
    )

    result = bootstrap.bootstrap_provider(session, _config(), api_base="http://api.test")

    assert result == {
        "connection_id": 7,
        "connection_name": "opencode go",
        "created_connection": True,
        "created_model": True,
        "model": "deepseek-v4.1-flash",
    }
    assert [call[0] for call in session.calls] == ["GET", "POST", "GET", "POST", "GET"]
    assert session.calls[1][2] == {
        "name": "opencode go",
        "vendor": "opencode_go",
        "protocol": "openai_chat_completions",
        "base_url": "",
        "api_key": "fresh-secret",
        "enabled": True,
    }
    assert session.calls[3][2] == {
        "model_id": "deepseek-v4.1-flash",
        "display_name": "deepseek-v4.1-flash",
        "enabled": True,
    }
    assert "fresh-secret" not in json.dumps(result)


def test_bootstrap_updates_existing_connection_and_disabled_model():
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "providers": [
                        {
                            "id": 7,
                            "name": "opencode go",
                            "vendor": "opencode_go",
                            "protocol": "openai_chat_completions",
                            "enabled": False,
                        }
                    ]
                },
            ),
            FakeResponse(200, {"id": 7, "enabled": True}),
            FakeResponse(
                200,
                {
                    "models": [
                        {
                            "model_id": "deepseek-v4.1-flash",
                            "display_name": "old label",
                            "enabled": False,
                        }
                    ]
                },
            ),
            FakeResponse(200, {"model_id": "deepseek-v4.1-flash", "enabled": True}),
            FakeResponse(
                200,
                {
                    "providers": [
                        {
                            "id": 7,
                            "name": "opencode go",
                            "models": [{"model_id": "deepseek-v4.1-flash"}],
                        }
                    ]
                },
            ),
        ]
    )

    result = bootstrap.bootstrap_provider(session, _config("rotated-secret"), api_base="http://api.test/")

    assert result["created_connection"] is False
    assert result["created_model"] is False
    assert session.calls[1] == (
        "PATCH",
        "http://api.test/dashboard/llm/providers/7",
        {"base_url": "", "api_key": "rotated-secret", "enabled": True},
    )
    assert session.calls[3] == (
        "PATCH",
        "http://api.test/dashboard/llm/providers/7/models/deepseek-v4.1-flash",
        {"display_name": "deepseek-v4.1-flash", "enabled": True},
    )


def test_bootstrap_rejects_same_name_with_different_connection_kind():
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "providers": [
                        {
                            "id": 7,
                            "name": "opencode go",
                            "vendor": "openai",
                            "protocol": "openai_responses",
                        }
                    ]
                },
            )
        ]
    )

    with pytest.raises(bootstrap.ProviderBootstrapError, match="different vendor/protocol"):
        bootstrap.bootstrap_provider(session, _config(), api_base="http://api.test")

    assert len(session.calls) == 1


def test_bootstrap_redacts_secret_from_api_error():
    session = FakeSession(
        [
            FakeResponse(200, {"providers": []}),
            FakeResponse(422, {"detail": "x" * 483 + "fresh-secret"}),
        ]
    )

    with pytest.raises(bootstrap.ProviderBootstrapError) as caught:
        bootstrap.bootstrap_provider(session, _config(), api_base="http://api.test")

    assert "fresh" not in str(caught.value)
    assert "[REDA" in str(caught.value)


def test_bootstrap_resyncs_remote_model_after_key_rotation():
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "providers": [
                        {
                            "id": 7,
                            "name": "opencode go",
                            "vendor": "opencode_go",
                            "protocol": "openai_chat_completions",
                            "enabled": True,
                        }
                    ]
                },
            ),
            FakeResponse(200, {"id": 7, "enabled": True}),
            FakeResponse(
                200,
                {
                    "models": [
                        {
                            "model_id": "deepseek-v4.1-flash",
                            "display_name": "DeepSeek V4.1 Flash",
                            "source": "remote",
                            "enabled": True,
                            "available": False,
                        }
                    ]
                },
            ),
            FakeResponse(200, {"model_id": "deepseek-v4.1-flash", "enabled": True}),
            FakeResponse(200, {"models": []}),
            FakeResponse(
                200,
                {
                    "providers": [
                        {
                            "id": 7,
                            "name": "opencode go",
                            "models": [{"model_id": "deepseek-v4.1-flash"}],
                        }
                    ]
                },
            ),
        ]
    )

    result = bootstrap.bootstrap_provider(session, _config("rotated-secret"), api_base="http://api.test")

    assert result["created_model"] is False
    assert session.calls[4] == (
        "POST",
        "http://api.test/dashboard/llm/providers/7/models/sync",
        None,
    )


def test_bootstrap_resyncs_other_remote_models_when_selected_model_is_manual():
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "providers": [
                        {
                            "id": 7,
                            "name": "opencode go",
                            "vendor": "opencode_go",
                            "protocol": "openai_chat_completions",
                            "enabled": True,
                        }
                    ]
                },
            ),
            FakeResponse(200, {"id": 7, "enabled": True}),
            FakeResponse(
                200,
                {
                    "models": [
                        {
                            "model_id": "deepseek-v4.1-flash",
                            "display_name": "deepseek-v4.1-flash",
                            "source": "manual",
                            "enabled": True,
                            "available": True,
                        },
                        {
                            "model_id": "other-model",
                            "display_name": "Other Model",
                            "source": "remote",
                            "enabled": True,
                            "available": False,
                        },
                    ]
                },
            ),
            FakeResponse(200, {"model_id": "deepseek-v4.1-flash", "enabled": True}),
            FakeResponse(200, {"models": []}),
            FakeResponse(
                200,
                {
                    "providers": [
                        {
                            "id": 7,
                            "name": "opencode go",
                            "models": [{"model_id": "deepseek-v4.1-flash"}],
                        }
                    ]
                },
            ),
        ]
    )

    result = bootstrap.bootstrap_provider(session, _config("rotated-secret"), api_base="http://api.test")

    assert result["created_model"] is False
    assert session.calls[4] == (
        "POST",
        "http://api.test/dashboard/llm/providers/7/models/sync",
        None,
    )


def test_api_key_loader_supports_environment_and_env_file(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENCODE_API_KEY", "env-secret")
    assert bootstrap.load_api_key("OPENCODE_API_KEY") == "env-secret"

    key_file = tmp_path / "agent.env"
    key_file.write_text(
        "# keep comments and unrelated values\nOPENAI_API_KEY=nope\nexport OPENCODE_API_KEY='file-secret'\n",
        encoding="utf-8",
    )
    assert bootstrap.load_api_key("OPENCODE_API_KEY", key_file) == "file-secret"

    monkeypatch.delenv("OPENCODE_API_KEY")
    with pytest.raises(bootstrap.ProviderBootstrapError, match="OPENCODE_API_KEY"):
        bootstrap.load_api_key("OPENCODE_API_KEY")


def test_main_invokes_bootstrap_with_environment_key(monkeypatch, capsys):
    monkeypatch.setenv("OPENCODE_API_KEY", "env-secret")
    monkeypatch.setattr(
        bootstrap,
        "bootstrap_provider",
        lambda session, config, api_base: {
            "connection_id": 7,
            "connection_name": config.name,
            "created_connection": True,
            "created_model": True,
            "model": config.model,
            "api": api_base,
        },
    )

    assert bootstrap.main(["--api", "http://api.test"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["connection_id"] == 7
    assert output["api"] == "http://api.test"
    assert "env-secret" not in json.dumps(output)


def test_bootstrap_works_on_fresh_isolated_provider_database(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    env = dict(
        os.environ,
        PYTHONPATH=str(root),
        FUND_DB_PATH=str(tmp_path / "fund.db"),
        LLM_DB_PATH=str(tmp_path / "providers.db"),
        PROMPT_CACHE_DIR=str(tmp_path / "prompts"),
    )
    script = r"""
import os
import sqlite3
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from research_app.backend.main import app
from scripts.bootstrap_llm_provider import ProviderBootstrapConfig, bootstrap_provider


class ClientSession:
    def __init__(self, client):
        self.client = client

    def request(self, method, url, json=None, timeout=None):
        parts = urlsplit(url)
        assert parts.netloc == "api.test", url
        path = parts.path + (("?" + parts.query) if parts.query else "")
        return self.client.request(method, path, json=json)


def config(key):
    return ProviderBootstrapConfig(
        name="opencode go",
        vendor="opencode_go",
        protocol="openai_chat_completions",
        model="deepseek-v4.1-flash",
        api_key=key,
    )


with TestClient(app) as client:
    session = ClientSession(client)
    first = bootstrap_provider(session, config("first-secret"), api_base="http://api.test")
    second = bootstrap_provider(session, config("rotated-secret"), api_base="http://api.test")

    assert first["created_connection"] is True
    assert first["created_model"] is True
    assert second["created_connection"] is False
    assert second["created_model"] is False
    assert first["connection_id"] == second["connection_id"]

    providers = client.get("/dashboard/llm/providers").json()["providers"]
    assert len(providers) == 1
    provider = providers[0]
    assert provider["name"] == "opencode go"
    assert provider["vendor"] == "opencode_go"
    assert provider["protocol"] == "openai_chat_completions"
    assert provider["base_url"] == "https://opencode.ai/zen/go/v1"
    assert provider["enabled"] is True
    assert provider["has_api_key"] is True

    models = client.get(
        f"/dashboard/llm/providers/{first['connection_id']}/models"
    ).json()["models"]
    assert len(models) == 1
    assert models[0]["model_id"] == "deepseek-v4.1-flash"
    assert models[0]["enabled"] is True

    options = client.get("/dashboard/llm/options").json()["providers"]
    assert len(options) == 1
    assert options[0]["id"] == first["connection_id"]
    assert [model["model_id"] for model in options[0]["models"]] == ["deepseek-v4.1-flash"]

with sqlite3.connect(os.environ["LLM_DB_PATH"]) as connection:
    key = connection.execute("select api_key from llm_provider_connections").fetchone()[0]
    assert key == "rotated-secret"
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
