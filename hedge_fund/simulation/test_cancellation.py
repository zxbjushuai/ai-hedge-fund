"""Cooperative cancellation for an active simulation worker."""

from __future__ import annotations

import threading
from pathlib import Path

from sqlalchemy import select

from hedge_fund.data.models import FinancialMetrics
from hedge_fund.llm import PromptCache
from hedge_fund.persistence.database import get_session
from hedge_fund.persistence.models import (
    MetricsCache,
    PriceCache,
    SimCycleRecord,
    SimTradeLog,
)
from hedge_fund.simulation.runner import (
    _RUNNERS,
    get_sim_result,
    get_sim_status,
    SimRunner,
)


class BlockingLLM:
    provider = "openai"
    protocol = "openai_chat_completions"
    model = "cancel-test"

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    @property
    def identity(self) -> str:
        return f"{self.provider}:{self.protocol}:{self.model}"

    def complete(self, system: str, user: str) -> str:
        self.started.set()
        assert self.release.wait(timeout=10)
        self.calls += 1
        return '{"signal":"neutral","confidence":50,"reasoning":"test"}'


def _write_spec(path: Path) -> None:
    path.write_text(
        """
name: cancellation-test
universe: [AAA]
strategies:
  - name: value
    models:
      - name: buffett
risk:
  max_position_pct: 1.0
  max_gross_exposure: 1.0
capital: 1000
""".strip(),
        encoding="utf-8",
    )


def _seed_market(db_path: str) -> None:
    with get_session(db_path) as session:
        for day in ("2024-01-09", "2024-01-10", "2024-01-11", "2024-01-12"):
            session.add(
                PriceCache(
                    ticker="AAA",
                    date=day,
                    open=10,
                    high=10,
                    low=10,
                    close=10,
                    adjusted_close=10,
                    volume=100,
                )
            )
            session.add(
                PriceCache(
                    ticker="SPY",
                    date=day,
                    open=100,
                    high=100,
                    low=100,
                    close=100,
                    adjusted_close=100,
                    volume=100,
                )
            )
        for index, report_period in enumerate(("2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31")):
            metric = FinancialMetrics(ticker="AAA", report_period=report_period, period="ttm")
            session.add(
                MetricsCache(
                    ticker="AAA",
                    report_period=report_period,
                    filing_date=f"2023-{index + 3:02d}-15",
                    filing_date_source="test",
                    data=metric.model_dump_json(exclude={"ticker"}),
                )
            )
        session.commit()


def test_cancel_during_signal_work_stops_before_cycle_commit(tmp_path: Path, monkeypatch):
    db_path = str(tmp_path / "cancel.db")
    spec_path = tmp_path / "fund.yaml"
    _write_spec(spec_path)
    _seed_market(db_path)

    import hedge_fund.signals.llm_agent as agent_module

    monkeypatch.setattr(agent_module, "PromptCache", lambda: PromptCache(tmp_path / "prompt-cache"))

    llm = BlockingLLM()
    sim_id = SimRunner.create(
        tickers=["AAA"],
        start_date="2024-01-09",
        end_date="2024-01-12",
        initial_capital=1000.0,
        benchmark="SPY",
        db_path=db_path,
        fund_spec_path=str(spec_path),
        llm=llm,
    )
    runner = SimRunner._get(sim_id)
    assert runner is not None
    worker = threading.Thread(target=runner._run)
    worker.start()
    assert llm.started.wait(timeout=10)

    accepted = SimRunner.cancel(sim_id, db_path)
    assert accepted is not None
    assert accepted["status"] == "cancelling"
    repeated = SimRunner.cancel(sim_id, db_path)
    assert repeated is not None
    assert repeated["status"] == "cancelling"

    llm.release.set()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert SimRunner._get(sim_id) is None

    status = get_sim_status(sim_id, db_path)
    assert status is not None
    assert status["status"] == "cancelled"
    assert status["current_day"] == 1
    assert status["final_nav"] == 1000.0
    result = get_sim_result(sim_id, db_path)
    assert result is not None
    assert result["status"] == "cancelled"
    assert result["trade_count"] == 0
    with get_session(db_path) as session:
        assert session.execute(select(SimCycleRecord).where(SimCycleRecord.sim_run_id == sim_id)).scalars().all() == []
        assert session.execute(select(SimTradeLog).where(SimTradeLog.sim_run_id == sim_id)).scalars().all() == []


def test_cancel_pending_run_without_worker_is_terminal(tmp_path: Path):
    db_path = str(tmp_path / "pending.db")
    spec_path = tmp_path / "fund.yaml"
    _write_spec(spec_path)
    _seed_market(db_path)
    sim_id = SimRunner.create(
        tickers=["AAA"],
        start_date="2024-01-09",
        end_date="2024-01-12",
        initial_capital=1000.0,
        benchmark="SPY",
        db_path=db_path,
        fund_spec_path=str(spec_path),
    )
    SimRunner._get(sim_id).request_cancel()
    _RUNNERS.pop(sim_id, None)

    status = SimRunner.cancel(sim_id, db_path)

    assert status is not None
    assert status["status"] == "cancelled"
    assert status["completed_at"]


def test_cancel_before_worker_promotes_to_running_skips_validation(tmp_path: Path):
    db_path = str(tmp_path / "pre-start.db")
    spec_path = tmp_path / "fund.yaml"
    _write_spec(spec_path)
    _seed_market(db_path)
    sim_id = SimRunner.create(
        tickers=["AAA"],
        start_date="2024-01-09",
        end_date="2024-01-12",
        initial_capital=1000.0,
        benchmark="SPY",
        db_path=db_path,
        fund_spec_path=str(spec_path),
    )
    runner = SimRunner._get(sim_id)
    assert runner is not None

    accepted = SimRunner.cancel(sim_id, db_path)
    assert accepted is not None
    assert accepted["status"] == "cancelling"

    runner._run()

    status = get_sim_status(sim_id, db_path)
    assert status is not None
    assert status["status"] == "cancelled"
    assert SimRunner._get(sim_id) is None
