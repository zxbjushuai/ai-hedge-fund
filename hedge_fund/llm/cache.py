"""Prompt cache — one JSON file per LLM decision.

This is deliberately three things at once (a locked design decision):
1. a cache: a backtest re-running an agent over an unchanged snapshot costs $0;
2. the persistence record: the EXACT prompt + response behind every Signal,
   for replay and audit;
3. the debug trail: failed parses keep the raw response on disk.

Files live under ~/.hedge-fund/cache/llm/, keyed by a hash of
(agent, model, prompt).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from hedge_fund.paths import CACHE_DIR

DEFAULT_CACHE_DIR = CACHE_DIR / "llm"


def prompt_key(agent: str, model_identity: str, system: str, user: str) -> str:
    """Cache key for one (agent, vendor:protocol:model, prompt) combination."""
    payload = f"{agent}|{model_identity}|{system}|{user}"
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


class PromptCache:
    def __init__(self, cache_dir: Path | str | None = None) -> None:
        self._dir = Path(cache_dir if cache_dir is not None else os.environ.get("PROMPT_CACHE_DIR", DEFAULT_CACHE_DIR))

    def get(self, key: str) -> dict | None:
        path = self._dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None  # corrupt cache entry -> treat as miss, will be rewritten

    def put(self, key: str, record: dict) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        record = {**record, "created_at": datetime.now(timezone.utc).isoformat()}
        path = self._dir / f"{key}.json"
        path.write_text(json.dumps(record, indent=2))
