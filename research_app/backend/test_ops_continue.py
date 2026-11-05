"""The agent ops CLI starts carried runs from the prior valuation date."""

from datetime import date
from types import SimpleNamespace

import scripts.aihf_ops as ops


def test_continue_command_uses_parent_book(monkeypatch):
    parent = {
        "id": 12,
        "status": "completed",
        "tickers": ["AAA", "SPY"],
        "benchmark": "SPY",
        "llm_connection_name": "sub2api opencode go",
        "model": "deepseek-v4.1-flash",
        "initial_capital": 100000.0,
    }

    def fake_api(method, path, payload=None):
        assert method == "GET"
        if path == "/dashboard/sim/runs":
            return {"runs": [parent]}
        if path == "/dashboard/sim/result/12":
            return {"valuation_date": "2024-01-10", "final_nav": 101250.0}
        raise AssertionError(path)

    captured = {}

    def fake_run_simulation(**kwargs):
        captured.update(kwargs)
        return {"status": {"status": "completed"}}

    monkeypatch.setattr(ops, "api", fake_api)
    monkeypatch.setattr(ops, "run_simulation", fake_run_simulation)
    args = SimpleNamespace(
        from_run=12,
        end="2024-01-12",
        connection=None,
        model=None,
        concurrency=2,
        name=None,
    )

    assert ops.cmd_continue(args) == 0
    assert captured == {
        "tickers": ["AAA", "SPY"],
        "start": date(2024, 1, 10),
        "end": date(2024, 1, 12),
        "name": "continue-12-2024-01-12",
        "connection": "sub2api opencode go",
        "model": "deepseek-v4.1-flash",
        "capital": 100000.0,
        "concurrency": 2,
        "benchmark": "SPY",
        "carried_from_run_id": 12,
    }
