"""Stable data paths, independent of the process working directory."""
from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=False)


def resolve_path(name: str, default: str) -> Path:
    path = Path(os.environ.get(name) or default).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


@dataclass(frozen=True)
class Settings:
    fund_db: Path
    llm_db: Path
    fund_spec: Path
    prompt_cache: Path


def load_settings() -> Settings:
    return Settings(
        resolve_path("FUND_DB_PATH", "fund.db"),
        resolve_path("LLM_DB_PATH", "app/backend/hedge_fund.db"),
        resolve_path("FUND_SPEC_PATH", "v2/funds/example.yaml"),
        resolve_path("PROMPT_CACHE_DIR", ".v2_cache/llm"),
    )


settings = load_settings()
# Core clients also read this variable when launched directly with uvicorn.
os.environ["PROMPT_CACHE_DIR"] = str(settings.prompt_cache)
