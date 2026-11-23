"""API contract for bounded simulation lineage lookup."""

import json

import pytest
from fastapi import HTTPException

from hedge_fund.persistence.database import get_session
from hedge_fund.persistence.models import SimRun
from research_app.backend.routes import simulations


def _add_run(session, name: str, created_at: str, carried: int | None = None) -> SimRun:
    run = SimRun(
        name=name,
        tickers=json.dumps(["AAA"]),
        benchmark="SPY",
        start_date="2024-01-01",
        end_date="2024-01-02",
        initial_capital=1000,
        status="completed",
        total_days=1,
        final_nav=1000,
        carried_from_run_id=carried,
        created_at=created_at,
    )
    session.add(run)
    session.flush()
    return run


def test_lineage_route_resolves_parent_and_children_outside_history(tmp_path, monkeypatch):
    db_path = tmp_path / "lineage.db"
    with get_session(str(db_path)) as session:
        parent = _add_run(session, "parent", "2026-01-01T00:00:00+00:00")
        for index in range(55):
            _add_run(
                session,
                f"filler-{index}",
                f"2026-02-01T00:{index:02d}:00+00:00",
            )
        child = _add_run(
            session,
            "child",
            "2026-03-01T00:00:00+00:00",
            carried=parent.id,
        )
        session.commit()
        parent_id, child_id = parent.id, child.id

    monkeypatch.setattr(simulations, "_DB_PATH", str(db_path))

    child_lineage = simulations.sim_lineage(child_id)
    assert child_lineage["run_id"] == child_id
    assert child_lineage["parent"]["id"] == parent_id

    parent_lineage = simulations.sim_lineage(parent_id)
    assert [run["id"] for run in parent_lineage["children"]] == [child_id]
    assert parent_lineage["children_truncated"] is False


def test_lineage_route_returns_404_for_unknown_run(tmp_path, monkeypatch):
    db_path = tmp_path / "missing.db"
    with get_session(str(db_path)) as session:
        session.add(
            SimRun(
                name="only",
                tickers=json.dumps(["AAA"]),
                benchmark="SPY",
                start_date="2024-01-01",
                end_date="2024-01-02",
                initial_capital=1000,
                status="completed",
                total_days=1,
            )
        )
        session.commit()
    monkeypatch.setattr(simulations, "_DB_PATH", str(db_path))

    with pytest.raises(HTTPException) as exc_info:
        simulations.sim_lineage(999)
    assert exc_info.value.status_code == 404
