"""Backtest-matrix validation and artifact tests for the ops CLI."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

import scripts.aihf_ops as ops


def _write_spec(path: Path, runs: list[dict], name: str = "matrix-run") -> None:
    path.write_text(
        json.dumps(
            {
                "name": name,
                "defaults": {
                    "connection": "sub2api opencode go",
                    "model": "deepseek-v4.1-flash",
                    "capital": 250000,
                    "concurrency": 2,
                    "benchmark": "SPY",
                },
                "runs": runs,
            }
        ),
        encoding="utf-8",
    )


def _record(
    sim_id: int,
    *,
    total: float,
    excess: float,
    drawdown: float,
    sharpe: float,
    status: str = "completed",
) -> dict:
    return {
        "sim_id": sim_id,
        "status": {"status": status},
        "result": {
            "id": sim_id,
            "final_nav": 100000 * (1 + total / 100),
            "total_return_pct": total,
            "benchmark_return_pct": total - excess,
            "excess_return_pct": excess,
            "max_drawdown_pct": drawdown,
            "sharpe_ratio": sharpe,
        },
    }


def test_load_matrix_spec_merges_defaults_and_applies_run_overrides(tmp_path: Path):
    spec_path = tmp_path / "matrix.json"
    _write_spec(
        spec_path,
        [
            {
                "name": "h1",
                "tickers": ["aapl", "MSFT", "AAPL"],
                "start": "2024-01-02",
                "end": "2024-06-28",
            },
            {
                "name": "h2-small",
                "tickers": ["NVDA"],
                "start": "2024-07-01",
                "end": "2024-12-31",
                "capital": 50000,
                "concurrency": 1,
                "benchmark": "QQQ",
            },
        ],
    )

    matrix = ops.load_matrix_spec(spec_path)

    assert matrix["name"] == "matrix-run"
    assert matrix["spec_path"] == str(spec_path.resolve())
    assert len(matrix["spec_sha256"]) == 64
    assert matrix["runs"][0] == {
        "name": "h1",
        "tickers": ["AAPL", "MSFT"],
        "start": date(2024, 1, 2),
        "end": date(2024, 6, 28),
        "connection": "sub2api opencode go",
        "model": "deepseek-v4.1-flash",
        "capital": 250000.0,
        "concurrency": 2,
        "benchmark": "SPY",
    }
    assert matrix["runs"][1]["capital"] == 50000.0
    assert matrix["runs"][1]["concurrency"] == 1
    assert matrix["runs"][1]["benchmark"] == "QQQ"


@pytest.mark.parametrize(
    ("runs", "message"),
    [
        (
            [
                {"name": "same", "tickers": ["AAPL"], "start": "2024-01-02", "end": "2024-01-31"},
                {"name": "same", "tickers": ["MSFT"], "start": "2024-02-01", "end": "2024-02-29"},
            ],
            "duplicate run name",
        ),
        (
            [{"name": "../escape", "tickers": ["AAPL"], "start": "2024-01-02", "end": "2024-01-31"}],
            "filename-safe",
        ),
        (
            [{"name": "bad-date", "tickers": ["AAPL"], "start": "2024-02-01", "end": "2024-01-31"}],
            "start must be on or before",
        ),
        (
            [{"name": "too-many", "tickers": [f"T{i}" for i in range(51)], "start": "2024-01-02", "end": "2024-01-31"}],
            "more than 50 tickers",
        ),
        (
            [{"name": "typo", "tickers": ["AAPL"], "start": "2024-01-02", "end": "2024-01-31", "captial": 1}],
            "unknown run key",
        ),
        (
            [{"name": "slash", "tickers": ["AAPL/US"], "start": "2024-01-02", "end": "2024-01-31"}],
            "invalid ticker",
        ),
        (
            [{"name": "bad-bench", "tickers": ["AAPL"], "benchmark": "SPY/US", "start": "2024-01-02", "end": "2024-01-31"}],
            "invalid benchmark",
        ),
        (
            [{"name": "too-long", "tickers": ["AAPL"], "start": "2010-01-01", "end": "2024-01-31"}],
            "cannot exceed 10 years",
        ),
    ],
)
def test_load_matrix_spec_rejects_invalid_runs(tmp_path: Path, runs: list[dict], message: str):
    spec_path = tmp_path / "matrix.json"
    _write_spec(spec_path, runs)

    with pytest.raises(ValueError, match=message):
        ops.load_matrix_spec(spec_path)


def test_cmd_matrix_runs_in_order_and_writes_ranked_artifacts(tmp_path: Path, monkeypatch):
    spec_path = tmp_path / "matrix.json"
    _write_spec(
        spec_path,
        [
            {"name": "first", "tickers": ["AAPL"], "start": "2024-01-02", "end": "2024-01-31"},
            {"name": "second", "tickers": ["MSFT"], "start": "2024-02-01", "end": "2024-02-29"},
        ],
    )
    monkeypatch.setattr(ops, "OUT_DIR", tmp_path)
    calls: list[dict] = []

    def fake_run_simulation(**kwargs):
        calls.append(kwargs)
        if kwargs["name"].endswith("first"):
            return _record(21, total=1.5, excess=0.5, drawdown=2.0, sharpe=1.2)
        return _record(22, total=4.0, excess=2.25, drawdown=1.0, sharpe=1.8)

    monkeypatch.setattr(ops, "run_simulation", fake_run_simulation)

    assert ops.cmd_matrix(SimpleNamespace(spec=str(spec_path))) == 0

    assert [call["name"] for call in calls] == ["matrix-run-first", "matrix-run-second"]
    assert calls[0]["start"] == date(2024, 1, 2)
    assert calls[0]["benchmark"] == "SPY"
    assert calls[0]["capital"] == 250000.0

    json_path = next(tmp_path.glob("matrix-*-matrix-run.json"))
    markdown_path = next(tmp_path.glob("matrix-*-matrix-run.md"))
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert [run["name"] for run in payload["runs"]] == ["first", "second"]
    assert payload["spec_sha256"] == ops.load_matrix_spec(spec_path)["spec_sha256"]
    assert payload["runs"][1]["metrics"]["excess_return_pct"] == 2.25

    report = markdown_path.read_text(encoding="utf-8")
    assert "| Rank | Run | Status | Sim |" in report
    assert report.index("1 | second") < report.index("2 | first")
    assert "best excess return: `second` +2.25%" in report


def test_cmd_matrix_persists_failure_and_continues(tmp_path: Path, monkeypatch):
    spec_path = tmp_path / "matrix.json"
    _write_spec(
        spec_path,
        [
            {"name": "broken", "tickers": ["AAPL"], "start": "2024-01-02", "end": "2024-01-31"},
            {"name": "healthy", "tickers": ["MSFT"], "start": "2024-02-01", "end": "2024-02-29"},
        ],
    )
    monkeypatch.setattr(ops, "OUT_DIR", tmp_path)

    def fake_run_simulation(**kwargs):
        if kwargs["name"].endswith("broken"):
            raise RuntimeError("preflight rejected the range")
        return _record(31, total=2.0, excess=1.0, drawdown=0.5, sharpe=0.9)

    monkeypatch.setattr(ops, "run_simulation", fake_run_simulation)

    assert ops.cmd_matrix(SimpleNamespace(spec=str(spec_path))) == 1

    payload = json.loads(next(tmp_path.glob("matrix-*.json")).read_text(encoding="utf-8"))
    assert payload["runs"][0]["status"] == "error"
    assert payload["runs"][0]["error"] == "preflight rejected the range"
    assert payload["runs"][1]["status"] == "completed"
    report = next(tmp_path.glob("matrix-*.md")).read_text(encoding="utf-8")
    assert "preflight rejected the range" in report


def test_cmd_matrix_handles_completed_run_without_excess_return(tmp_path: Path, monkeypatch):
    spec_path = tmp_path / "matrix.json"
    _write_spec(
        spec_path,
        [{"name": "no-benchmark", "tickers": ["AAPL"], "start": "2024-01-02", "end": "2024-01-31"}],
    )
    monkeypatch.setattr(ops, "OUT_DIR", tmp_path)
    monkeypatch.setattr(
        ops,
        "run_simulation",
        lambda **kwargs: {
            "sim_id": 41,
            "status": {"status": "completed"},
            "result": {"final_nav": 101000.0, "total_return_pct": 1.0, "excess_return_pct": None},
        },
    )

    assert ops.cmd_matrix(SimpleNamespace(spec=str(spec_path))) == 0

    report = next(tmp_path.glob("matrix-*.md")).read_text(encoding="utf-8")
    assert "no completed runs with excess return" in report
    assert "| — | no-benchmark | completed | 41 |" in report


def test_run_simulation_marks_monitoring_failure_with_started_run_id(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ops, "OUT_DIR", tmp_path)
    monkeypatch.setattr(ops, "resolve_connection", lambda name: 4)

    def fake_api(method, path, payload=None):
        if path == "/dashboard/sim/preflight":
            return {"trading_days": 2}
        if path == "/dashboard/sim/run":
            return {"sim_id": 77}
        raise AssertionError(f"unexpected API call after lost monitoring: {method} {path}")

    def lost_monitoring(sim_id):
        raise TimeoutError("simulation timed out")

    monkeypatch.setattr(ops, "api", fake_api)
    monkeypatch.setattr(ops, "wait_sim", lost_monitoring)

    with pytest.raises(ops.SimulationMonitoringError) as caught:
        ops.run_simulation(
            ["AAPL"],
            date(2024, 1, 2),
            date(2024, 1, 31),
            "lost-monitoring",
            "sub2api opencode go",
            "deepseek-v4.1-flash",
            100000,
            1,
        )

    assert caught.value.sim_id == 77
    assert "lost monitoring" in str(caught.value)


def test_run_simulation_marks_ambiguous_submission_failure(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ops, "OUT_DIR", tmp_path)
    monkeypatch.setattr(ops, "resolve_connection", lambda name: 4)

    def fake_api(method, path, payload=None):
        if path == "/dashboard/sim/preflight":
            return {"trading_days": 2}
        if path == "/dashboard/sim/run":
            raise requests.Timeout("response lost")
        raise AssertionError(f"unexpected API call: {method} {path}")

    monkeypatch.setattr(ops, "api", fake_api)
    monkeypatch.setattr(ops, "wait_sim", lambda sim_id: pytest.fail("must not monitor without a run ID"))

    with pytest.raises(ops.SimulationSubmissionError, match="outcome unknown"):
        ops.run_simulation(
            ["AAPL"],
            date(2024, 1, 2),
            date(2024, 1, 31),
            "ambiguous-submit",
            "sub2api opencode go",
            "deepseek-v4.1-flash",
            100000,
            1,
        )


def test_cmd_matrix_stops_launching_runs_after_monitoring_failure(tmp_path: Path, monkeypatch):
    spec_path = tmp_path / "matrix.json"
    _write_spec(
        spec_path,
        [
            {"name": "lost", "tickers": ["AAPL"], "start": "2024-01-02", "end": "2024-01-31"},
            {"name": "must-not-start", "tickers": ["MSFT"], "start": "2024-02-01", "end": "2024-02-29"},
        ],
    )
    monkeypatch.setattr(ops, "OUT_DIR", tmp_path)
    calls: list[str] = []

    def fake_run_simulation(**kwargs):
        calls.append(kwargs["name"])
        raise ops.SimulationMonitoringError(77, "lost monitoring of sim 77")

    monkeypatch.setattr(ops, "run_simulation", fake_run_simulation)

    assert ops.cmd_matrix(SimpleNamespace(spec=str(spec_path))) == 1

    assert calls == ["matrix-run-lost"]
    payload = json.loads(next(tmp_path.glob("matrix-*.json")).read_text(encoding="utf-8"))
    assert payload["runs"][0]["status"] == "monitoring_error"
    assert payload["runs"][0]["metrics"]["sim_id"] == 77
    assert payload["stopped_after"] == "lost"
    report = next(tmp_path.glob("matrix-*.md")).read_text(encoding="utf-8")
    assert "stopped after `lost`: lost monitoring of sim 77" in report


def test_cmd_matrix_stops_launching_runs_after_submission_failure(tmp_path: Path, monkeypatch):
    spec_path = tmp_path / "matrix.json"
    _write_spec(
        spec_path,
        [
            {"name": "ambiguous", "tickers": ["AAPL"], "start": "2024-01-02", "end": "2024-01-31"},
            {"name": "must-not-start", "tickers": ["MSFT"], "start": "2024-02-01", "end": "2024-02-29"},
        ],
    )
    monkeypatch.setattr(ops, "OUT_DIR", tmp_path)
    calls: list[str] = []

    def fake_run_simulation(**kwargs):
        calls.append(kwargs["name"])
        raise ops.SimulationSubmissionError("simulation submission outcome unknown")

    monkeypatch.setattr(ops, "run_simulation", fake_run_simulation)

    assert ops.cmd_matrix(SimpleNamespace(spec=str(spec_path))) == 1

    assert calls == ["matrix-run-ambiguous"]
    payload = json.loads(next(tmp_path.glob("matrix-*.json")).read_text(encoding="utf-8"))
    assert payload["runs"][0]["status"] == "submission_error"
    assert payload["stopped_after"] == "ambiguous"
    report = next(tmp_path.glob("matrix-*.md")).read_text(encoding="utf-8")
    assert "stopped after `ambiguous`: simulation submission outcome unknown" in report


def test_parser_exposes_matrix_spec_option():
    args = ops.build_parser().parse_args(["matrix", "--spec", "matrix.json"])
    assert args.command == "matrix"
    assert args.spec == "matrix.json"


def test_checked_in_example_matrix_is_valid():
    repo = Path(__file__).resolve().parents[2]
    matrix = ops.load_matrix_spec(repo / "docs" / "agent" / "backtest-matrix.example.json")

    assert matrix["name"] == "momentum-windows"
    assert len(matrix["runs"]) == 2
    assert matrix["runs"][0]["benchmark"] == "SPY"
