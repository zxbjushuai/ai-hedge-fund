"""API behavior for cancelling a simulation."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from hedge_fund.persistence.database import get_session
from hedge_fund.persistence.models import SimRun
from research_app.backend.routes import simulations


def _run(status: str) -> SimRun:
    return SimRun(
        name="cancel-api",
        tickers='["AAA"]',
        benchmark="SPY",
        start_date="2024-01-09",
        end_date="2024-01-12",
        initial_capital=1000.0,
        status=status,
        total_days=4,
    )


def test_cancel_route_marks_pending_row_cancelled_without_worker(tmp_path: Path, monkeypatch):
    db_path = str(tmp_path / "cancel-api.db")
    monkeypatch.setattr(simulations, "_DB_PATH", db_path)
    with get_session(db_path) as session:
        row = _run("pending")
        session.add(row)
        session.commit()
        sim_id = row.id

    response = simulations.sim_cancel(sim_id)

    assert response["id"] == sim_id
    assert response["status"] == "cancelled"
    with get_session(db_path) as session:
        row = session.get(SimRun, sim_id)
        assert row.status == "cancelled"
        assert row.completed_at


def test_cancel_route_rejects_terminal_and_missing_runs(tmp_path: Path, monkeypatch):
    db_path = str(tmp_path / "terminal.db")
    monkeypatch.setattr(simulations, "_DB_PATH", db_path)
    with get_session(db_path) as session:
        row = _run("completed")
        session.add(row)
        session.commit()
        sim_id = row.id

    with pytest.raises(HTTPException) as terminal:
        simulations.sim_cancel(sim_id)
    assert terminal.value.status_code == 409
    with pytest.raises(HTTPException) as missing:
        simulations.sim_cancel(sim_id + 1)
    assert missing.value.status_code == 404
