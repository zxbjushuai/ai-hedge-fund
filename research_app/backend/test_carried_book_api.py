"""API contract for starting a carried-book simulation."""

from datetime import date

import pytest
from fastapi import HTTPException

from hedge_fund.persistence.database import get_session
from hedge_fund.persistence.models import SimRun
from hedge_fund.simulation.runner import SimRunner, get_sim_result
from hedge_fund.simulation.test_carried_book import _run_parent
from research_app.backend.routes import simulations
from research_app.backend.routes.schemas import SimRunRequest


def test_sim_run_route_creates_carried_child_run(tmp_path, monkeypatch):
    db_path, spec_path, parent_id = _run_parent(tmp_path)
    parent = get_sim_result(parent_id, db_path)
    assert parent is not None
    monkeypatch.setattr(simulations, "_DB_PATH", db_path)
    monkeypatch.setattr(simulations, "_fund_path", lambda: spec_path)
    monkeypatch.setattr(SimRunner, "start", lambda self: None)

    request = SimRunRequest(
        tickers=["AAA"],
        benchmark="SPY",
        start_date=date.fromisoformat(parent["valuation_date"]),
        end_date=date(2024, 1, 12),
        initial_capital=1.0,
        carried_from_run_id=parent_id,
        confirm_cost=True,
    )
    preflight = simulations.sim_preflight(request)
    assert preflight["initial_capital"] == pytest.approx(parent["final_nav"])
    assert preflight["carried_book"]["run_id"] == parent_id
    assert preflight["carried_book"]["positions"] == {"AAA": 80}

    response = simulations.sim_run(request)
    with get_session(db_path) as session:
        child = session.get(SimRun, response["sim_id"])
    assert child.carried_from_run_id == parent_id
    assert child.initial_capital == pytest.approx(parent["final_nav"])


def test_sim_preflight_rejects_non_boundary_start(tmp_path, monkeypatch):
    db_path, spec_path, parent_id = _run_parent(tmp_path)
    monkeypatch.setattr(simulations, "_DB_PATH", db_path)
    monkeypatch.setattr(simulations, "_fund_path", lambda: spec_path)
    request = SimRunRequest(
        tickers=["AAA"],
        benchmark="SPY",
        start_date=date(2024, 1, 9),
        end_date=date(2024, 1, 12),
        initial_capital=1000.0,
        carried_from_run_id=parent_id,
        confirm_cost=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        simulations.sim_preflight(request)
    assert exc_info.value.status_code == 422
    assert "final valuation date" in str(exc_info.value.detail)
