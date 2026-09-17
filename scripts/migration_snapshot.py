"""Create an offline migration checkpoint without exposing stored credentials."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"baseline": "5fca1b4", "upstream": "fc1bf25", "databases": {}}
    for label, path in {
        "fund": os.environ.get("FUND_DB_PATH", str(ROOT / "fund.db")),
        "providers": os.environ.get("LLM_DB_PATH", str(ROOT / "app/backend/hedge_fund.db")),
    }.items():
        source = Path(path).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = output / f"{label}.db"
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src:
            with sqlite3.connect(destination) as dst:
                src.backup(dst)
                integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
                assert integrity == "ok", integrity
                counts = {}
                for (name,) in dst.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
                    quoted = '"' + name.replace('"', '""') + '"'
                    counts[name] = dst.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0]
        report["databases"][label] = {
            "source": str(source), "backup": str(destination),
            "integrity": integrity, "counts": counts,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        }
    report["fund_yaml"] = os.environ.get("FUND_SPEC_PATH", str(ROOT / "hedge_fund/fund/example.yaml"))
    report["prompt_cache"] = os.environ.get("PROMPT_CACHE_DIR", str(ROOT / ".v2_cache/llm"))
    (output / "manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
