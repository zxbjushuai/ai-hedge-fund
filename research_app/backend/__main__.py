"""Run the API with the existing logging and shutdown infrastructure."""
import argparse
import ipaddress
import os

from dotenv import load_dotenv

from research_app.backend.config import ROOT


def validate_bind_host(host: str) -> str:
    """Refuse direct remote binds; remote access must proxy to loopback."""
    normalized = host.strip()
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1]
    try:
        address = ipaddress.ip_address(normalized)
        if address.is_loopback:
            return str(address)
    except ValueError:
        hostname = normalized.rstrip(".").lower()
        if hostname == "localhost":
            return hostname
    raise ValueError(f"Refusing non-loopback bind {host!r}; keep --host on loopback and use Tailscale Serve for remote access")


def main():
    load_dotenv(ROOT / ".env", override=False)
    from research_app.backend.config import load_settings

    paths = load_settings()
    for key, value in {
        "FUND_DB_PATH": paths.fund_db,
        "LLM_DB_PATH": paths.llm_db,
        "FUND_SPEC_PATH": paths.fund_spec,
        "PROMPT_CACHE_DIR": paths.prompt_cache,
    }.items():
        os.environ[key] = str(value)
    # Reload before routes import their immutable configuration snapshot.
    from research_app.backend import config

    config.settings = paths
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1", help="Loopback bind address; use Tailscale Serve for remote access")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        bind_host = validate_bind_host(args.host)
    except ValueError as exc:
        parser.error(str(exc))
    from hedge_fund.logging_config import configure_logging

    configure_logging(ROOT / "logs")
    import uvicorn

    uvicorn.run("research_app.backend.main:app", host=bind_host, port=args.port, log_config=None)


if __name__ == "__main__":
    main()
