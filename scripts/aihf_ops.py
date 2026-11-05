"""On-demand data, simulation, backtest and analysis operations.

The autonomous agent uses this instead of a pre-scheduled simulation pipeline.
All commands talk to the locally running research_app backend.
"""

from __future__ import annotations

import argparse
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
OUT_DIR = REPO / "logs" / "ops"
BENCHMARK = os.environ.get("AIHF_BENCHMARK", "SPY")
DEFAULT_CONNECTION = os.environ.get("AIHF_CONNECTION_NAME", "sub2api opencode go")
DEFAULT_MODEL = os.environ.get("AIHF_MODEL", "deepseek-v4.1-flash")
FALLBACK_CONNECTION_ID = int(os.environ.get("AIHF_CONNECTION_ID", "1"))
CACHE_TIMEOUT = 60 * 60
SIM_TIMEOUT = 6 * 60 * 60


def api(method: str, path: str, payload: dict | None = None) -> dict:
    response = requests.request(method, API + path, json=payload, timeout=60)
    if response.status_code >= 400:
        raise RuntimeError(
            f"{method} {path} -> {response.status_code}: {response.text[:1000]}"
        )
    return response.json()


def load_tickers(raw: str | None) -> list[str]:
    if raw:
        tickers = [item.strip().upper() for item in raw.split(",") if item.strip()]
    else:
        tickers = [
            line.strip().upper()
            for line in UNIVERSE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
    unique = list(dict.fromkeys(tickers))
    if not unique:
        raise SystemExit("no tickers")
    if len(unique) > 50:
        print(
            f"warning: {len(unique)} tickers; the simulation cap is 50, truncating",
            file=sys.stderr,
        )
        unique = unique[:50]
    return unique


def resolve_connection(name: str) -> int:
    providers = api("GET", "/dashboard/llm/providers").get("providers", [])
    for provider in providers:
        if provider.get("name") == name:
            return int(provider["id"])
    print(
        f"warning: connection {name!r} not found; falling back to id {FALLBACK_CONNECTION_ID}",
        file=sys.stderr,
    )
    return FALLBACK_CONNECTION_ID


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


def run_simulation(
    tickers: list[str],
    start: date,
    end: date,
    name: str,
    connection: str,
    model: str,
    capital: float,
    concurrency: int,
) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    connection_id = resolve_connection(connection)
    payload = {
        "tickers": tickers,
        "benchmark": BENCHMARK,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "initial_capital": capital,
        "name": name,
        "llm_connection_id": connection_id,
        "model": model,
        "llm_concurrency": concurrency,
        "confirm_cost": True,
    }
    preflight = api("POST", "/dashboard/sim/preflight", payload)
    print("preflight:", json.dumps(preflight, ensure_ascii=False)[:1200], flush=True)
    run = api("POST", "/dashboard/sim/run", payload)
    sim_id = run["sim_id"]
    status = wait_sim(sim_id)
    result = api("GET", f"/dashboard/sim/result/{sim_id}")
    record = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sim_id": sim_id,
        "payload": payload,
        "preflight": preflight,
        "status": status,
        "result": result,
    }
    out = OUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", out, flush=True)
    if status.get("status") == "completed":
        print(
            f"sim {sim_id} completed: final_nav={result.get('final_nav')} "
            f"total={result.get('total_return_pct')}% "
            f"excess={result.get('excess_return_pct')}% "
            f"maxdd={result.get('max_drawdown_pct')}%"
        )
    else:
        print(
            f"sim {sim_id} {status.get('status')}: {status.get('error_message')}",
            file=sys.stderr,
        )
    return record


def cmd_status(args: argparse.Namespace) -> int:
    print("health:", api("GET", "/health"))
    providers = api("GET", "/dashboard/llm/providers").get("providers", [])
    for provider in providers:
        print(
            f"provider {provider['id']}: {provider['name']} "
            f"vendor={provider.get('vendor')} protocol={provider.get('protocol')} "
            f"enabled={provider.get('enabled')} url={provider.get('base_url')}"
        )
    runs = api("GET", "/dashboard/sim/runs").get("runs", [])
    for run in runs[:8]:
        print(
            f"run {run.get('id')}: {run.get('status')} "
            f"{run.get('start_date')}..{run.get('end_date')} "
            f"connection={run.get('llm_connection_name')}"
        )
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    tickers = load_tickers(args.tickers)
    start = (
        date.fromisoformat(args.start)
        if args.start
        else date.today() - timedelta(days=args.days)
    )
    end = date.fromisoformat(args.end) if args.end else date.today()
    data_types = [item.strip() for item in args.types.split(",") if item.strip()]
    job = api(
        "POST",
        "/dashboard/cache/jobs",
        {
            "selection": {"tickers": tickers},
            "benchmark": args.benchmark,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "data_types": data_types,
            "force": args.force,
        },
    )
    final = wait_cache(job["id"])
    print("cache final:", final.get("status"), final.get("progress"))
    return 0 if final.get("status") in {"completed", "partial"} else 1


def cmd_simulate(args: argparse.Namespace) -> int:
    record = run_simulation(
        load_tickers(args.tickers),
        date.fromisoformat(args.start),
        date.fromisoformat(args.end),
        args.name or f"simulate-{args.end}",
        args.connection,
        args.model,
        args.capital,
        args.concurrency,
    )
    return 0 if record["status"].get("status") == "completed" else 1


def cmd_backtest(args: argparse.Namespace) -> int:
    end = date.fromisoformat(args.end) if args.end else date.today()
    start = end - timedelta(days=args.days)
    record = run_simulation(
        load_tickers(args.tickers),
        start,
        end,
        args.name or f"backtest-{args.days}d-{end.isoformat()}",
        args.connection,
        args.model,
        args.capital,
        args.concurrency,
    )
    return 0 if record["status"].get("status") == "completed" else 1


def cmd_cumulative(args: argparse.Namespace) -> int:
    end = date.fromisoformat(args.end) if args.end else date.today()
    record = run_simulation(
        load_tickers(args.tickers),
        date.fromisoformat(args.since),
        end,
        args.name or f"cumulative-{args.since}-{end.isoformat()}",
        args.connection,
        args.model,
        args.capital,
        args.concurrency,
    )
    return 0 if record["status"].get("status") == "completed" else 1


def cmd_analyze(args: argparse.Namespace) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    runs = api("GET", "/dashboard/sim/runs").get("runs", [])[: args.last]
    lines = [
        "# Simulation analysis",
        "",
        "generated: " + time.strftime("%Y-%m-%d %H:%M:%S"),
        "",
    ]
    for run in runs:
        sim_id = run.get("id")
        try:
            result = api("GET", f"/dashboard/sim/result/{sim_id}")
        except Exception as exc:
            lines.append(f"- run {sim_id}: result unavailable ({exc})")
            continue
        lines.append(
            f"- run {sim_id} {run.get('status')} "
            f"{run.get('start_date')}..{run.get('end_date')} "
            f"model={result.get('model')} conn={result.get('llm_connection_name')} "
            f"final_nav={result.get('final_nav')} "
            f"total={result.get('total_return_pct')}% "
            f"excess={result.get('excess_return_pct')}% "
            f"maxdd={result.get('max_drawdown_pct')}%"
        )
        print(lines[-1])
    out = OUT_DIR / f"analyze-{time.strftime('%Y%m%d-%H%M%S')}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("saved", out)
    return 0


def cmd_continue(args: argparse.Namespace) -> int:
    print("carried-book continuous mode is not implemented yet (backlog AIHF-016).")
    print(
        "Use `python scripts/aihf_ops.py cumulative --since YYYY-MM-DD` for an interim "
        "continuous window, or implement AIHF-016 to carry cash/positions between runs."
    )
    return 2


def add_sim_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tickers", help="comma-separated; default docs/agent/universe.txt")
    parser.add_argument("--connection", default=DEFAULT_CONNECTION)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--capital", type=float, default=100000)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--name")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)

    fetch = sub.add_parser("fetch")
    fetch.add_argument("--tickers")
    fetch.add_argument("--start")
    fetch.add_argument("--end")
    fetch.add_argument("--days", type=int, default=35)
    fetch.add_argument("--types", default="prices")
    fetch.add_argument("--benchmark", default=BENCHMARK)
    fetch.add_argument("--force", action="store_true")
    fetch.set_defaults(func=cmd_fetch)

    simulate = sub.add_parser("simulate")
    add_sim_args(simulate)
    simulate.add_argument("--start", required=True)
    simulate.add_argument("--end", required=True)
    simulate.set_defaults(func=cmd_simulate)

    backtest = sub.add_parser("backtest")
    add_sim_args(backtest)
    backtest.add_argument("--days", type=int, default=365)
    backtest.add_argument("--end")
    backtest.set_defaults(func=cmd_backtest)

    cumulative = sub.add_parser("cumulative")
    add_sim_args(cumulative)
    cumulative.add_argument("--since", required=True)
    cumulative.add_argument("--end")
    cumulative.set_defaults(func=cmd_cumulative)

    analyze = sub.add_parser("analyze")
    analyze.add_argument("--last", type=int, default=5)
    analyze.set_defaults(func=cmd_analyze)

    cont = sub.add_parser("continue")
    cont.set_defaults(func=cmd_continue)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        sys.exit(args.func(args) or 0)
    except Exception as exc:
        print("aihf_ops failed:", type(exc).__name__, str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
