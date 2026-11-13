from datetime import datetime, timezone

from sqlalchemy import select

from hedge_fund.persistence.database import get_session, init_db
from hedge_fund.persistence.models import SimNavSnapshot, SimRun
from hedge_fund.simulation.runner import _RUNNERS, SimRunner


def _run(sim_id: int, status: str) -> SimRun:
    return SimRun(
        id=sim_id,
        name=f"sim-{sim_id}",
        tickers='["AAPL"]',
        start_date="2024-01-02",
        end_date="2024-01-03",
        initial_capital=1000.0,
        status=status,
        current_day=1,
        total_days=2,
    )


def test_recover_orphaned_simulations_is_idempotent(tmp_path):
    db = str(tmp_path / "fund.db")
    init_db(db)
    with get_session(db) as session:
        session.add_all(
            [
                _run(1, "running"),
                _run(2, "completed"),
                _run(3, "failed"),
            ]
        )
        session.commit()

    recovered_at = datetime(2026, 11, 8, 1, 0, tzinfo=timezone.utc)
    assert SimRunner.recover_orphaned_runs(db, recovered_at=recovered_at) == [1]

    with get_session(db) as session:
        rows = {row.id: row for row in session.scalars(select(SimRun)).all()}
    assert rows[1].status == "failed"
    assert rows[1].completed_at == recovered_at.isoformat()
    assert "backend restart" in rows[1].error_message.lower()
    assert rows[1].current_day == 1
    assert rows[2].status == "completed"
    assert rows[2].completed_at is None
    assert rows[3].status == "failed"

    assert SimRunner.recover_orphaned_runs(db, recovered_at=recovered_at) == []
    with get_session(db) as session:
        assert session.get(SimRun, 1).error_message.count("backend restart") == 1


def test_recovery_removes_process_local_runner(tmp_path):
    db = str(tmp_path / "fund.db")
    init_db(db)
    with get_session(db) as session:
        session.add(_run(7, "running"))
        session.commit()
    _RUNNERS[7] = object()
    try:
        assert SimRunner.recover_orphaned_runs(db) == [7]
        assert 7 not in _RUNNERS
    finally:
        _RUNNERS.pop(7, None)


def test_recovery_marks_stale_cancelling_run_cancelled(tmp_path):
    db = str(tmp_path / "fund.db")
    init_db(db)
    with get_session(db) as session:
        session.add(_run(8, "cancelling"))
        session.add(SimNavSnapshot(
            sim_run_id=8, cycle_date="2024-01-03", nav=1010.0,
            cash=1010.0, equity=0.0, benchmark_nav=100.0,
        ))
        session.commit()

    with get_session(db) as session:
        assert SimRunner.recover_orphaned_runs(db) == [8]
    with get_session(db) as session:
        row = session.get(SimRun, 8)
        assert row.status == "cancelled"
        assert row.final_nav == 1010.0
        assert row.completed_at
        assert "backend restart" in row.error_message.lower()
