"""Create or update a managed LLM provider connection through the Web API.

The command is safe to rerun and never accepts a secret as a command-line
argument. It verifies that `/dashboard/llm/options` exposes the connection and
model before reporting success.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import requests

API = os.environ.get("AIHF_API", "http://127.0.0.1:8000")
DEFAULT_NAME = "opencode go"
DEFAULT_VENDOR = "opencode_go"
DEFAULT_PROTOCOL = "openai_chat_completions"
DEFAULT_MODEL = os.environ.get("AIHF_MODEL", "deepseek-v4.1-flash")
DEFAULT_KEY_ENV = "OPENCODE_API_KEY"
TIMEOUT_SECONDS = 30.0


class ProviderBootstrapError(RuntimeError):
    """The requested provider could not be configured or verified."""


class HttpSession(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        json: dict | None = None,
        timeout: float | None = None,
    ) -> Any:
        ...


@dataclass(frozen=True)
class ProviderBootstrapConfig:
    name: str
    vendor: str
    protocol: str
    model: str
    api_key: str = field(repr=False)
    base_url: str = ""
    enabled: bool = True


def load_api_key(env_name: str, key_file: str | Path | None = None) -> str:
    """Load a secret from the environment or a KEY=value env file."""
    if key_file is not None:
        path = Path(key_file).expanduser()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ProviderBootstrapError(f"cannot read API key file {path}") from exc
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == env_name:
                secret = value.strip().strip("\"'")
                if secret:
                    return secret
        raise ProviderBootstrapError(f"{env_name} was not found in API key file {path}")

    secret = os.environ.get(env_name, "").strip()
    if not secret:
        raise ProviderBootstrapError(f"{env_name} is not set; use --api-key-file or export the variable")
    return secret


def validate_config(config: ProviderBootstrapConfig) -> None:
    from hedge_fund.llm.adapter_registry import validate_vendor_protocol

    for label, value in (
        ("name", config.name),
        ("vendor", config.vendor),
        ("protocol", config.protocol),
        ("model", config.model),
        ("api_key", config.api_key),
    ):
        if not value or not value.strip():
            raise ProviderBootstrapError(f"{label} cannot be empty")
    try:
        validate_vendor_protocol(config.vendor, config.protocol)
    except ValueError as exc:
        raise ProviderBootstrapError(str(exc)) from exc


def _request(
    session: HttpSession,
    api_base: str,
    method: str,
    path: str,
    payload: dict | None = None,
    redact: str | None = None,
) -> Any:
    url = f"{api_base.rstrip('/')}{path}"
    try:
        response = session.request(method, url, json=payload, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise ProviderBootstrapError(f"{method} {path} failed: {type(exc).__name__}") from exc
    if response.status_code >= 400:
        text = getattr(response, "text", "") or ""
        if redact:
            text = text.replace(redact, "[REDACTED]")
        detail = text.strip()[:500]
        suffix = f": {detail}" if detail else ""
        raise ProviderBootstrapError(f"{method} {path} -> {response.status_code}{suffix}")
    return response.json()


def _matching_connection(providers: list[dict], name: str) -> dict | None:
    return next((provider for provider in providers if provider.get("name") == name), None)


def _matching_model(models: list[dict], model_id: str) -> dict | None:
    return next((model for model in models if model.get("model_id") == model_id), None)


def bootstrap_provider(
    session: HttpSession,
    config: ProviderBootstrapConfig,
    *,
    api_base: str = API,
) -> dict:
    """Create/update one connection and model, then verify the API options."""
    config = ProviderBootstrapConfig(
        name=config.name.strip(),
        vendor=config.vendor.strip().lower(),
        protocol=config.protocol.strip(),
        model=config.model.strip(),
        api_key=config.api_key.strip(),
        base_url=config.base_url.strip(),
        enabled=config.enabled,
    )
    validate_config(config)
    providers = _request(session, api_base, "GET", "/dashboard/llm/providers").get("providers", [])
    connection = _matching_connection(providers, config.name)
    created_connection = connection is None

    if connection is None:
        connection = _request(
            session,
            api_base,
            "POST",
            "/dashboard/llm/providers",
            {
                "name": config.name,
                "vendor": config.vendor,
                "protocol": config.protocol,
                "base_url": config.base_url,
                "api_key": config.api_key,
                "enabled": config.enabled,
            },
            redact=config.api_key,
        )
    else:
        kind = (connection.get("vendor"), connection.get("protocol"))
        if kind != (config.vendor, config.protocol):
            raise ProviderBootstrapError(f"connection {config.name!r} already exists with a different vendor/protocol " f"({kind[0] or 'unknown'} / {kind[1] or 'unknown'}); choose another --name")
        connection = _request(
            session,
            api_base,
            "PATCH",
            f"/dashboard/llm/providers/{connection['id']}",
            {
                "base_url": config.base_url,
                "api_key": config.api_key,
                "enabled": config.enabled,
            },
            redact=config.api_key,
        )

    connection_id = connection["id"]
    models = _request(
        session,
        api_base,
        "GET",
        f"/dashboard/llm/providers/{connection_id}/models",
    ).get("models", [])
    model = _matching_model(models, config.model)
    created_model = model is None
    if model is None:
        _request(
            session,
            api_base,
            "POST",
            f"/dashboard/llm/providers/{connection_id}/models",
            {
                "model_id": config.model,
                "display_name": config.model,
                "enabled": True,
            },
        )
    else:
        _request(
            session,
            api_base,
            "PATCH",
            f"/dashboard/llm/providers/{connection_id}/models/{quote(config.model, safe='')}",
            {"display_name": config.model, "enabled": True},
        )

    if any(item.get("source") == "remote" and item.get("available") is False for item in models):
        _request(
            session,
            api_base,
            "POST",
            f"/dashboard/llm/providers/{connection_id}/models/sync",
        )

    options = _request(session, api_base, "GET", "/dashboard/llm/options").get("providers", [])
    enabled = next(
        (provider for provider in options if provider.get("id") == connection_id),
        None,
    )
    model_ids = {item.get("model_id") for item in (enabled or {}).get("models", [])}
    if config.model not in model_ids:
        raise ProviderBootstrapError(f"connection {config.name!r} is not usable: {config.model!r} " "is missing from /dashboard/llm/options")

    return {
        "connection_id": connection_id,
        "connection_name": config.name,
        "created_connection": created_connection,
        "created_model": created_model,
        "model": config.model,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or update a managed LLM provider and model via the AIHF API.")
    parser.add_argument("--api", default=API, help="AIHF backend base URL")
    parser.add_argument("--name", default=DEFAULT_NAME, help="connection name")
    parser.add_argument("--vendor", default=DEFAULT_VENDOR, help="LLM vendor adapter")
    parser.add_argument("--protocol", default=DEFAULT_PROTOCOL, help="wire protocol adapter")
    parser.add_argument("--base-url", default="", help="connection base URL")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="enabled model id")
    parser.add_argument(
        "--api-key-env",
        default=DEFAULT_KEY_ENV,
        help="environment variable containing the key",
    )
    parser.add_argument(
        "--api-key-file",
        type=Path,
        help="env file containing the key variable (for example agent.env)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = ProviderBootstrapConfig(
            name=args.name.strip(),
            vendor=args.vendor.strip().lower(),
            protocol=args.protocol.strip(),
            model=args.model.strip(),
            api_key=load_api_key(args.api_key_env, args.api_key_file),
            base_url=args.base_url.strip(),
        )
        result = bootstrap_provider(requests.Session(), config, api_base=args.api)
    except ProviderBootstrapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
