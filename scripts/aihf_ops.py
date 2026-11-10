"""On-demand data, simulation, backtest and analysis operations.

The autonomous agent uses this instead of a pre-scheduled simulation pipeline.
All commands talk to the locally running research_app backend.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
MATRIX_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
MATRIX_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9.\-]{1,10}$")
MATRIX_TOP_LEVEL_KEYS = {"name", "defaults", "runs"}
MATRIX_DEFAULT_KEYS = {"connection", "model", "capital", "concurrency", "benchmark"}
MATRIX_RUN_KEYS = {"name", "tickers", "start", "end"} | MATRIX_DEFAULT_KEYS


class SimulationMonitoringError(RuntimeError):
    """A started simulation could not be monitored to a reliable terminal state."""

    def __init__(self, sim_id: int, message: str):
        super().__init__(message)
        self.sim_id = sim_id


class SimulationSubmissionError(RuntimeError):
    """The backend may have accepted a simulation whose run ID is unknown."""


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


def _matrix_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _matrix_name(value: object, label: str) -> str:
    name = _matrix_string(value, label)
    if not MATRIX_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"{label} must be filename-safe: 1-40 letters, digits, dots, underscores, or hyphens")
    return name


def _matrix_tickers(value: object, run_name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"run {run_name!r}: tickers must be a non-empty list")
    if len(value) > 50:
        raise ValueError(f"run {run_name!r}: more than 50 tickers are not supported")
    tickers: list[str] = []
    for raw in value:
        ticker = _matrix_string(raw, f"run {run_name!r} ticker").upper()
        if not MATRIX_SYMBOL_PATTERN.fullmatch(ticker):
            raise ValueError(f"run {run_name!r}: invalid ticker {ticker!r}")
        tickers.append(ticker)
    return list(dict.fromkeys(tickers))


def _matrix_benchmark(value: object, label: str) -> str:
    benchmark = _matrix_string(value, label).upper()
    if not MATRIX_SYMBOL_PATTERN.fullmatch(benchmark):
        raise ValueError(f"{label}: invalid benchmark {benchmark!r}")
    return benchmark


def _matrix_date(value: object, label: str) -> date:
    raw = _matrix_string(value, label)
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date (YYYY-MM-DD): {raw!r}") from exc


def _matrix_capital(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{label} must be a positive number")
    return float(value)


def _matrix_concurrency(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 8:
        raise ValueError(f"{label} must be an integer from 1 to 8")
    return value


def load_matrix_spec(path: str | Path) -> dict:
    """Load one fully validated, reproducible backtest matrix."""
    spec_path = Path(path)
    try:
        raw = spec_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read matrix spec {spec_path}: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid matrix JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("matrix spec must be a JSON object")
    unknown = set(payload) - MATRIX_TOP_LEVEL_KEYS
    if unknown:
        raise ValueError(f"unknown matrix key(s): {', '.join(sorted(unknown))}")

    matrix_name = _matrix_name(payload.get("name"), "matrix name")
    defaults = payload.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ValueError("defaults must be a JSON object")
    unknown = set(defaults) - MATRIX_DEFAULT_KEYS
    if unknown:
        raise ValueError(f"unknown default key(s): {', '.join(sorted(unknown))}")

    shared = {
        "connection": _matrix_string(defaults.get("connection", DEFAULT_CONNECTION), "defaults.connection"),
        "model": _matrix_string(defaults.get("model", DEFAULT_MODEL), "defaults.model"),
        "capital": _matrix_capital(defaults.get("capital", 100000), "defaults.capital"),
        "concurrency": _matrix_concurrency(defaults.get("concurrency", 4), "defaults.concurrency"),
        "benchmark": _matrix_benchmark(defaults.get("benchmark", BENCHMARK), "defaults.benchmark"),
    }

    raw_runs = payload.get("runs")
    if not isinstance(raw_runs, list) or not raw_runs:
        raise ValueError("runs must be a non-empty list")
    runs: list[dict] = []
    seen_names: set[str] = set()
    for index, raw_run in enumerate(raw_runs, start=1):
        if not isinstance(raw_run, dict):
            raise ValueError(f"run #{index} must be a JSON object")
        unknown = set(raw_run) - MATRIX_RUN_KEYS
        if unknown:
            raise ValueError(f"run #{index}: unknown run key(s): {', '.join(sorted(unknown))}")
        run_name = _matrix_name(raw_run.get("name"), f"run #{index} name")
        if run_name in seen_names:
            raise ValueError(f"duplicate run name: {run_name!r}")
        seen_names.add(run_name)

        start = _matrix_date(raw_run.get("start"), f"run {run_name!r} start")
        end = _matrix_date(raw_run.get("end"), f"run {run_name!r} end")
        if start > end:
            raise ValueError(f"run {run_name!r}: start must be on or before end")
        if (end - start).days > 3650:
            raise ValueError(f"run {run_name!r}: date range cannot exceed 10 years")
        runs.append(
            {
                "name": run_name,
                "tickers": _matrix_tickers(raw_run.get("tickers"), run_name),
                "start": start,
                "end": end,
                "connection": _matrix_string(raw_run.get("connection", shared["connection"]), f"run {run_name!r} connection"),
                "model": _matrix_string(raw_run.get("model", shared["model"]), f"run {run_name!r} model"),
                "capital": _matrix_capital(raw_run.get("capital", shared["capital"]), f"run {run_name!r} capital"),
                "concurrency": _matrix_concurrency(raw_run.get("concurrency", shared["concurrency"]), f"run {run_name!r} concurrency"),
                "benchmark": _matrix_benchmark(raw_run.get("benchmark", shared["benchmark"]), f"run {run_name!r} benchmark"),
            }
        )
    return {
        "name": matrix_name,
        "spec_path": str(spec_path.resolve()),
        "spec_sha256": hashlib.sha256(raw).hexdigest(),
        "runs": runs,
    }


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
    benchmark: str | None = None,
    carried_from_run_id: int | None = None,
) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    connection_id = resolve_connection(connection)
    payload = {
        "tickers": tickers,
        "benchmark": benchmark or BENCHMARK,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "initial_capital": capital,
        "name": name,
        "llm_connection_id": connection_id,
        "model": model,
        "llm_concurrency": concurrency,
        "confirm_cost": True,
    }
    if carried_from_run_id is not None:
        payload["carried_from_run_id"] = carried_from_run_id
    preflight = api("POST", "/dashboard/sim/preflight", payload)
    print("preflight:", json.dumps(preflight, ensure_ascii=False)[:1200], flush=True)
    try:
        run = api("POST", "/dashboard/sim/run", payload)
    except Exception as exc:
        raise SimulationSubmissionError(f"simulation submission outcome unknown: {exc}") from exc
    sim_id = run.get("sim_id")
    if isinstance(sim_id, bool) or not isinstance(sim_id, int) or sim_id <= 0:
        raise SimulationSubmissionError(f"simulation submission returned no usable run id: {run}")
    try:
        status = wait_sim(sim_id)
    except Exception as exc:
        raise SimulationMonitoringError(sim_id, f"lost monitoring of sim {sim_id}: {exc}") from exc
    try:
        result = api("GET", f"/dashboard/sim/result/{sim_id}")
    except Exception as exc:
        raise SimulationMonitoringError(sim_id, f"sim {sim_id} result unavailable: {exc}") from exc
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


def _matrix_parameters(run: dict, sim_name: str) -> dict:
    return {
        "sim_name": sim_name,
        "tickers": run["tickers"],
        "start": run["start"].isoformat(),
        "end": run["end"].isoformat(),
        "connection": run["connection"],
        "model": run["model"],
        "capital": run["capital"],
        "concurrency": run["concurrency"],
        "benchmark": run["benchmark"],
    }


def _matrix_metrics(record: dict) -> dict:
    result = record.get("result") or {}
    return {
        "sim_id": record.get("sim_id"),
        "final_nav": result.get("final_nav"),
        "total_return_pct": result.get("total_return_pct"),
        "benchmark_return_pct": result.get("benchmark_return_pct"),
        "excess_return_pct": result.get("excess_return_pct"),
        "max_drawdown_pct": result.get("max_drawdown_pct"),
        "sharpe_ratio": result.get("sharpe_ratio"),
    }


def _matrix_markdown(payload: dict) -> str:
    completed = [run for run in payload["runs"] if run["status"] == "completed"]
    ranked = sorted(
        [run for run in completed if run["metrics"]["excess_return_pct"] is not None],
        key=lambda run: -run["metrics"]["excess_return_pct"],
    )
    rank_by_name = {run["name"]: rank for rank, run in enumerate(ranked, start=1)}

    def cell(value: object) -> str:
        return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ")

    lines = [
        f"# Backtest matrix: {payload['name']}",
        "",
        f"- generated: {payload['created_at']}",
        f"- spec: `{payload['spec_path']}`",
        f"- sha256: `{payload['spec_sha256']}`",
        f"- completed: {len(completed)}/{len(payload['runs'])}",
    ]
    if payload.get("stopped_after"):
        stopped = next(run for run in payload["runs"] if run["name"] == payload["stopped_after"])
        lines.append(f"- stopped after `{payload['stopped_after']}`: {stopped['error']}")
    lines.extend(
        [
            "",
            "| Rank | Run | Status | Sim | Range | Tickers | Total | Excess | MaxDD | Sharpe | Error |",
            "| ---: | --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    unranked = [run for run in payload["runs"] if run["name"] not in rank_by_name]
    for run in [*ranked, *unranked]:
        params = run["parameters"]
        metrics = run["metrics"]
        lines.append(
            "| "
            + " | ".join(
                [
                    cell(rank_by_name.get(run["name"], "—")),
                    cell(run["name"]),
                    cell(run["status"]),
                    cell(metrics["sim_id"]),
                    cell(f"{params['start']}..{params['end']}"),
                    cell(",".join(params["tickers"])),
                    cell(f"{metrics['total_return_pct']}%" if metrics["total_return_pct"] is not None else None),
                    cell(f"{metrics['excess_return_pct']}%" if metrics["excess_return_pct"] is not None else None),
                    cell(f"{metrics['max_drawdown_pct']}%" if metrics["max_drawdown_pct"] is not None else None),
                    cell(metrics["sharpe_ratio"]),
                    cell(run.get("error")),
                ]
            )
            + " |"
        )

    lines.extend(["", "## Ranking", ""])
    if ranked:
        best = ranked[0]["metrics"]
        lines.append(f"- best excess return: `{ranked[0]['name']}` {best['excess_return_pct']:+.2f}%")
    else:
        lines.append("- no completed runs with excess return")
    drawdown_runs = [run for run in completed if run["metrics"]["max_drawdown_pct"] is not None]
    if drawdown_runs:
        lowest = min(drawdown_runs, key=lambda run: run["metrics"]["max_drawdown_pct"])
        lines.append(f"- lowest max drawdown: `{lowest['name']}` {lowest['metrics']['max_drawdown_pct']:.2f}%")
    return "\n".join(lines) + "\n"


def cmd_matrix(args: argparse.Namespace) -> int:
    matrix = load_matrix_spec(args.spec)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    results: list[dict] = []
    stopped_after: str | None = None
    for run in matrix["runs"]:
        sim_name = f"{matrix['name']}-{run['name']}"
        parameters = _matrix_parameters(run, sim_name)
        print(f"matrix run {run['name']}: {parameters['start']}..{parameters['end']}", flush=True)
        try:
            record = run_simulation(
                tickers=run["tickers"],
                start=run["start"],
                end=run["end"],
                name=sim_name,
                connection=run["connection"],
                model=run["model"],
                capital=run["capital"],
                concurrency=run["concurrency"],
                benchmark=run["benchmark"],
            )
            status = (record.get("status") or {}).get("status", "unknown")
            results.append(
                {
                    "name": run["name"],
                    "parameters": parameters,
                    "status": status,
                    "metrics": _matrix_metrics(record),
                    "record": record,
                    "error": (record.get("status") or {}).get("error_message"),
                }
            )
        except SimulationSubmissionError as exc:
            message = str(exc)
            print(f"matrix run {run['name']} submission failed: {message}", file=sys.stderr, flush=True)
            results.append(
                {
                    "name": run["name"],
                    "parameters": parameters,
                    "status": "submission_error",
                    "metrics": _matrix_metrics({}),
                    "record": None,
                    "error": message,
                }
            )
            stopped_after = run["name"]
            break
        except SimulationMonitoringError as exc:
            message = str(exc)
            print(f"matrix run {run['name']} monitoring failed: {message}", file=sys.stderr, flush=True)
            results.append(
                {
                    "name": run["name"],
                    "parameters": parameters,
                    "status": "monitoring_error",
                    "metrics": _matrix_metrics({"sim_id": exc.sim_id}),
                    "record": None,
                    "error": message,
                }
            )
            stopped_after = run["name"]
            break
        except Exception as exc:
            message = str(exc)
            print(f"matrix run {run['name']} failed: {message}", file=sys.stderr, flush=True)
            results.append(
                {
                    "name": run["name"],
                    "parameters": parameters,
                    "status": "error",
                    "metrics": _matrix_metrics({}),
                    "record": None,
                    "error": message,
                }
            )

    payload = {
        "created_at": created_at,
        "name": matrix["name"],
        "spec_path": matrix["spec_path"],
        "spec_sha256": matrix["spec_sha256"],
        "stopped_after": stopped_after,
        "runs": results,
    }
    json_path = OUT_DIR / f"matrix-{stamp}-{matrix['name']}.json"
    markdown_path = OUT_DIR / f"matrix-{stamp}-{matrix['name']}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_matrix_markdown(payload), encoding="utf-8")
    print("matrix saved", json_path, markdown_path)
    return 0 if all(run["status"] == "completed" for run in results) else 1


def cmd_continue(args: argparse.Namespace) -> int:
    runs = api("GET", "/dashboard/sim/runs").get("runs", [])
    if args.from_run is not None:
        parent = next((run for run in runs if run.get("id") == args.from_run), None)
        if parent is None:
            raise ValueError(f"simulation run {args.from_run} not found")
        if parent.get("status") != "completed":
            raise ValueError(f"simulation run {args.from_run} is not completed")
    else:
        parent = next((run for run in runs if run.get("status") == "completed"), None)
        if parent is None:
            raise ValueError("no completed simulation run is available to continue")
    result = api("GET", f"/dashboard/sim/result/{parent['id']}")
    valuation_date = result.get("valuation_date")
    if not valuation_date:
        raise ValueError(f"simulation run {parent['id']} has no valuation date")
    start = date.fromisoformat(valuation_date)
    end = date.fromisoformat(args.end) if args.end else date.today()
    if end <= start:
        raise ValueError(f"continue end date must be after parent valuation date {start}")
    record = run_simulation(
        tickers=parent["tickers"],
        start=start,
        end=end,
        name=args.name or f"continue-{parent['id']}-{end.isoformat()}",
        connection=args.connection or parent.get("llm_connection_name") or DEFAULT_CONNECTION,
        model=args.model or parent.get("model") or DEFAULT_MODEL,
        capital=parent.get("initial_capital") or 100000,
        concurrency=args.concurrency,
        benchmark=parent.get("benchmark") or BENCHMARK,
        carried_from_run_id=parent["id"],
    )
    return 0 if record["status"].get("status") == "completed" else 1


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

    matrix = sub.add_parser("matrix", help="run a reproducible backtest matrix from JSON")
    matrix.add_argument("--spec", required=True, help="path to the matrix JSON document")
    matrix.set_defaults(func=cmd_matrix)

    cont = sub.add_parser("continue")
    cont.add_argument("--from-run", type=int)
    cont.add_argument("--end")
    cont.add_argument("--connection")
    cont.add_argument("--model")
    cont.add_argument("--concurrency", type=int, default=4)
    cont.add_argument("--name")
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
