"""Carried-book simulation continuity across completed runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from hedge_fund.persistence.database import get_session
from hedge_fund.persistence.models import PriceCache, SimCycleRecord, SimNavSnapshot, SimRun
from hedge_fund.simulation.carried import CarrySourceError
from hedge_fund.simulation.runner import SimRunner, get_sim_result


DAYS = [
    ("2024-01-04", 10.0),
    ("2024-01-05", 10.0),
    ("2024-01-08", 11.0),
    ("2024-01-09", 12.0),
    ("2024-01-10", 13.0),
    ("2024-01-11", 14.0),
    ("2024-01-12", 15.0),
]


def _write_spec(path: Path) -> None:
    path.write_text(
        """
name: carried-book-test
strategies:
  - name: trend
    models:
      - name: price_momentum
        params:
          lookback_days: 2
          full_signal_return: 0.10
risk:
  max_position_pct: 1.0
  max_gross_exposure: 1.0
capital: 1000
rebalance: daily
""".strip(),
        encoding="utf-8",
    )


def _seed_market(db_path: str) -> None:
    with get_session(db_path) as session:
        for day, price in DAYS:
            session.add(
                PriceCache(
                    ticker="AAA",
                    date=day,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    adjusted_close=price,
                    volume=100,
                    dividend=0.5 if day == "2024-01-10" else 0.0,
                )
            )
            session.add(
                PriceCache(
                    ticker="SPY",
                    date=day,
                    open=100.0,
                    high=100.0,
                    low=100.0,
                    close=100.0,
                    adjusted_close=100.0,
                    volume=100,
                )
            )
        session.commit()


def _run_parent(tmp_path: Path) -> tuple[str, str, int]:
    db_path = str(tmp_path / "carried.db")
    spec_path = tmp_path / "fund.yaml"
    _write_spec(spec_path)
    _seed_market(db_path)
    parent_id = SimRunner.create(
        tickers=["AAA"],
        start_date="2024-01-04",
        end_date="2024-01-10",
        initial_capital=1000.0,
        benchmark="SPY",
        db_path=db_path,
        fund_spec_path=str(spec_path),
        fee_rate=0.0,
    )
    SimRunner._get(parent_id)._run()
    return db_path, str(spec_path), parent_id


def test_carried_run_continues_parent_book_and_position_history(tmp_path: Path):
    db_path, spec_path, parent_id = _run_parent(tmp_path)
    parent = get_sim_result(parent_id, db_path)
    assert parent is not None and parent["status"] == "completed"

    with get_session(db_path) as session:
        parent_nav = session.execute(select(SimNavSnapshot).where(SimNavSnapshot.sim_run_id == parent_id).order_by(SimNavSnapshot.cycle_date.desc()).limit(1)).scalar_one()
        parent_cycle = session.execute(select(SimCycleRecord).where(SimCycleRecord.sim_run_id == parent_id).order_by(SimCycleRecord.cycle_number.desc()).limit(1)).scalar_one()
    parent_payload = json.loads(parent_cycle.payload)
    assert parent_payload["positions"] == {"AAA": 80}
    assert parent_payload["corporate_actions"][-1]["action_type"] == "dividend"

    child_id = SimRunner.create(
        tickers=["AAA"],
        start_date=parent["valuation_date"],
        end_date="2024-01-12",
        initial_capital=1.0,
        benchmark="SPY",
        db_path=db_path,
        fund_spec_path=spec_path,
        fee_rate=0.0,
        carried_from_run_id=parent_id,
    )
    SimRunner._get(child_id)._run()
    child = get_sim_result(child_id, db_path)
    assert child is not None and child["status"] == "completed"
    assert child["carried_from_run_id"] == parent_id
    assert child["initial_capital"] == pytest.approx(parent_nav.nav)

    with get_session(db_path) as session:
        child_run = session.get(SimRun, child_id)
        child_navs = session.execute(select(SimNavSnapshot).where(SimNavSnapshot.sim_run_id == child_id).order_by(SimNavSnapshot.cycle_date)).scalars().all()
        child_cycles = session.execute(select(SimCycleRecord).where(SimCycleRecord.sim_run_id == child_id).order_by(SimCycleRecord.cycle_number)).scalars().all()

    assert child_run.carried_from_run_id == parent_id
    assert child_navs[0].cycle_date == parent_nav.cycle_date
    assert child_navs[0].nav == pytest.approx(parent_nav.nav)
    assert child_navs[0].cash == pytest.approx(parent_nav.cash)
    assert child_navs[0].benchmark_nav == pytest.approx(parent_nav.nav)
    assert json.loads(child_navs[0].positions_json) == parent_payload["positions"]
    assert all(json.loads(row.positions_json) for row in child_navs[1:])

    first_cycle = json.loads(child_cycles[0].payload)
    assert child_cycles[0].signal_date == "2024-01-10"
    assert child_cycles[0].execution_date == "2024-01-11"
    assert first_cycle["marks"]["AAA"] == pytest.approx(13.0)
    assert first_cycle["execution_prices"]["AAA"] == pytest.approx(14.0)


def test_carried_run_rejects_changed_universe_or_benchmark(tmp_path: Path):
    db_path, spec_path, parent_id = _run_parent(tmp_path)

    with pytest.raises(CarrySourceError, match="universe must match"):
        SimRunner.create(
            tickers=["AAA", "BBB"],
            start_date="2024-01-10",
            end_date="2024-01-12",
            initial_capital=1000.0,
            benchmark="SPY",
            db_path=db_path,
            fund_spec_path=spec_path,
            carried_from_run_id=parent_id,
        )
    with pytest.raises(CarrySourceError, match="benchmark must match"):
        SimRunner.create(
            tickers=["AAA"],
            start_date="2024-01-10",
            end_date="2024-01-12",
            initial_capital=1000.0,
            benchmark="QQQ",
            db_path=db_path,
            fund_spec_path=spec_path,
            carried_from_run_id=parent_id,
        )


def test_carried_run_rejects_incomplete_parent(tmp_path: Path):
    db_path = str(tmp_path / "incomplete.db")
    spec_path = tmp_path / "fund.yaml"
    _write_spec(spec_path)
    _seed_market(db_path)
    with get_session(db_path) as session:
        parent = SimRun(
            name="incomplete",
            tickers=json.dumps(["AAA"]),
            benchmark="SPY",
            start_date="2024-01-08",
            end_date="2024-01-10",
            initial_capital=1000.0,
            status="failed",
            total_days=3,
        )
        session.add(parent)
        session.commit()
        parent_id = parent.id

    with pytest.raises(CarrySourceError, match="not a completed simulation"):
        SimRunner.create(
            tickers=["AAA"],
            start_date="2024-01-10",
            end_date="2024-01-12",
            initial_capital=1000.0,
            benchmark="SPY",
            db_path=db_path,
            fund_spec_path=str(spec_path),
            carried_from_run_id=parent_id,
        )
