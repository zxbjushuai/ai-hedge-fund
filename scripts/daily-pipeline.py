"""Daily US market data pull + simulation runner.

Runs against the locally running research_app backend. Kept dependency-light so
it can be invoked by a systemd timer.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

API = os.environ.get("AIHF_API", "http://127.0.0.1:8000")
REPO = Path(__file__).resolve().parents[1]
UNIVERSE = Path(
    os.environ.get("AIHF_UNIVERSE_FILE", str(REPO / "docs" / "agent" / "universe.txt"))
)
OUT_DIR = REPO / "logs" / "daily"
BENCHMARK = os.environ.get("AIHF_BENCHMARK", "SPY")
CONNECTION_ID = int(os.environ.get("AIHF_CONNECTION_ID", "1"))
MODEL = os.environ.get("AIHF_MODEL", "deepseek-v4.1-flash")
CONCURRENCY = int(os.environ.get("AIHF_CONCURRENCY", "4"))
CACHE_DAYS = int(os.environ.get("AIHF_CACHE_DAYS", "35"))
SIM_DAYS = int(os.environ.get("AIHF_SIM_DAYS", "14"))
CACHE_TIMEOUT = 60 * 60
SIM_TIMEOUT = 3 * 60 * 60


def today() -> date:
    return date.today()


def load_universe() -> list[str]:
    override = os.environ.get("AIHF_TICKERS", "").strip()
    if override:
        return list(dict.fromkeys(t.strip().upper() for t in override.split(",") if t.strip()))
    tickers = [
        line.strip().upper()
        for line in UNIVERSE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    unique = list(dict.fromkeys(tickers))
    if not unique:
        raise SystemExit("universe is empty: " + str(UNIVERSE))
    return unique[:50]


def api(method: str, path: str, payload: dict | None = None) -> dict:
    response = requests.request(method, API + path, json=payload, timeout=60)
    if response.status_code >= 400:
        raise RuntimeError(
            f"{method} {path} -> {response.status_code}: {response.text[:800]}"
        )
    return response.json()


def wait_cache(job_id: str) -> dict:
    deadline = time.time() + CACHE_TIMEOUT
    while time.time() < deadline:
        job = api("GET", f"/dashboard/cache/jobs/{job_id}")
        status = job.get("status")
        progress = job.get("progress", {})
        print(
            f"cache {job_id}: {status} "
            f"{progress.get('completed', 0)}/{progress.get('total', 0)} "
            f"failed={progress.get('failed', 0)}",
            flush=True,
        )
        if status in {"completed", "partial", "failed", "cancelled"}:
            return job
        time.sleep(15)
    raise TimeoutError("cache job timed out")


def wait_sim(sim_id: int) -> dict:
    deadline = time.time() + SIM_TIMEOUT
    while time.time() < deadline:
        status = api("GET", f"/dashboard/sim/status/{sim_id}")
        print(
            f"sim {sim_id}: {status.get('status')} "
            f"day {status.get('current_day')}/{status.get('total_days')}",
            flush=True,
        )
        if status.get("status") in {"completed", "failed"}:
            return status
        time.sleep(20)
    raise TimeoutError("simulation timed out")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    end = today()
    cache_start = end - timedelta(days=CACHE_DAYS)
    sim_start = end - timedelta(days=SIM_DAYS)
    tickers = load_universe()

    api("GET", "/health")

    data_types = ["prices"]
    if end.weekday() == 0:
        data_types = ["prices", "metrics", "earnings"]

    cache = api(
        "POST",
        "/dashboard/cache/jobs",
        {
            "selection": {"tickers": tickers},
            "benchmark": BENCHMARK,
            "start_date": cache_start.isoformat(),
            "end_date": end.isoformat(),
            "data_types": data_types,
            "force": False,
        },
    )
    job_id = cache["id"]
    job = wait_cache(job_id)
    print("cache final:", job.get("status"), job.get("progress"), flush=True)

    sim_payload = {
        "tickers": tickers,
        "benchmark": BENCHMARK,
        "start_date": sim_start.isoformat(),
        "end_date": end.isoformat(),
        "initial_capital": 100000,
        "name": "daily-" + end.isoformat(),
        "llm_connection_id": CONNECTION_ID,
        "model": MODEL,
        "llm_concurrency": CONCURRENCY,
        "confirm_cost": True,
    }
    preflight = api("POST", "/dashboard/sim/preflight", sim_payload)
    print("preflight:", json.dumps(preflight, ensure_ascii=False)[:1200], flush=True)

    run = api("POST", "/dashboard/sim/run", sim_payload)
    sim_id = run["sim_id"]
    status = wait_sim(sim_id)
    result = api("GET", f"/dashboard/sim/result/{sim_id}")

    record = {
        "date": end.isoformat(),
        "cache": {
            "job_id": job_id,
            "status": job.get("status"),
            "progress": job.get("progress"),
        },
        "preflight": preflight,
        "sim": status,
        "result": result,
    }
    out = OUT_DIR / (end.isoformat() + ".json")
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = OUT_DIR / (end.isoformat() + ".md")
    lines = [
        "# " + end.isoformat() + " 每日模拟",
        "",
        f"- 缓存任务: {job_id} ({job.get('status')})",
        f"- 模拟: #{sim_id} ({status.get('status')})",
        f"- 区间: {sim_start.isoformat()} ~ {end.isoformat()}",
        f"- 标的数: {len(tickers)}",
        f"- 模型: {MODEL}",
    ]
    if status.get("status") == "completed":
        lines.append(f"- 期末净值: {status.get('final_nav')}")
        lines.append(f"- 总收益: {result.get('total_return_pct')}%")
        lines.append(f"- 超额收益: {result.get('excess_return_pct')}%")
        lines.append(f"- 最大回撤: {result.get('max_drawdown_pct')}%")
    else:
        lines.append(f"- 错误: {status.get('error_message')}")
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", out, "and", summary, flush=True)

    if status.get("status") != "completed":
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("daily pipeline failed:", type(exc).__name__, str(exc), flush=True)
        sys.exit(1)
