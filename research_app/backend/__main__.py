"""Run the API with the existing logging and shutdown infrastructure."""
import argparse
import os
from dotenv import load_dotenv
from research_app.backend.config import ROOT


def main():
    load_dotenv(ROOT / ".env", override=False)
    from research_app.backend.config import load_settings
    paths = load_settings()
    for key, value in {
        "FUND_DB_PATH": paths.fund_db, "LLM_DB_PATH": paths.llm_db,
        "FUND_SPEC_PATH": paths.fund_spec, "PROMPT_CACHE_DIR": paths.prompt_cache,
    }.items():
        os.environ[key] = str(value)
    # Reload before routes import their immutable configuration snapshot.
    from research_app.backend import config
    config.settings = paths
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    from v2.logging_config import configure_logging
    configure_logging(ROOT / "logs")
    import uvicorn
    uvicorn.run("research_app.backend.main:app", host=args.host, port=args.port, log_config=None)


if __name__ == "__main__":
    main()
