"""Forced-overlap test proving simulation LLM configuration is run-scoped."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import select

from v2.data.models import FinancialMetrics
from v2.llm import PromptCache
from v2.persistence.database import get_session
from v2.persistence.models import MetricsCache, PriceCache, SimRun
from v2.simulation.runner import SimRunner


class BarrierLLM:
    def __init__(self, provider: str, model: str, barrier: threading.Barrier) -> None:
        self.provider = provider
        self.model = model
        self.barrier = barrier
        self.calls: list[str] = []

    @property
    def identity(self) -> str:
        return f"{self.provider}:{self.model}"

    def complete(self, system: str, user: str) -> str:
        self.barrier.wait(timeout=10)
        self.calls.append(self.identity)
        return '{"signal":"neutral","confidence":50,"reasoning":"test"}'


def test_runner_rejects_metadata_that_disagrees_with_client(tmp_path: Path):
    llm = BarrierLLM("openai", "gpt-test", threading.Barrier(1))
    with pytest.raises(ValueError, match="provider does not match"):
        SimRunner.create(
            tickers=["AAA"], start_date="2025-01-02", end_date="2025-01-03",
            initial_capital=1000, db_path=str(tmp_path / "mismatch.db"),
            fund_spec_path=str(tmp_path / "fund.yaml"), llm=llm,
            llm_provider="anthropic", llm_model="gpt-test",
        )


def _prepare_run(db: Path, spec_path: Path, llm: BarrierLLM) -> tuple[int, SimRunner]:
    with get_session(str(db)) as session:
        for day in ("2025-01-02", "2025-01-03"):
            session.add(PriceCache(ticker="AAA", date=day, open=10, high=11, low=9, close=10, volume=1))
            session.add(PriceCache(ticker="SPY", date=day, open=100, high=101, low=99, close=100, volume=1))
        for index, report_period in enumerate(("2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31")):
            metric = FinancialMetrics(ticker="AAA", report_period=report_period, period="ttm")
            session.add(MetricsCache(
                ticker="AAA", report_period=report_period,
                filing_date=f"2024-0{index + 1}-15", filing_date_source="test",
                data=metric.model_dump_json(exclude={"ticker"}),
            ))
        session.commit()
    sim_id = SimRunner.create(
        tickers=["AAA"], benchmark="SPY", start_date="2025-01-02", end_date="2025-01-03",
        initial_capital=1000, db_path=str(db), fund_spec_path=str(spec_path), llm=llm,
    )
    runner = SimRunner._get(sim_id)
    assert runner is not None
    return sim_id, runner


def test_concurrent_runs_keep_provider_and_model_isolated(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("V2_LLM_PROVIDER", "must-not-be-used")
    monkeypatch.setenv("V2_LLM_MODEL", "must-not-be-used")
    spec_path = tmp_path / "fund.yaml"
    spec_path.write_text(
        """
name: concurrent-llm-test
universe: [AAA]
strategies:
  - name: value
    models:
      - name: buffett
risk:
  max_position_pct: 1.0
  max_gross_exposure: 1.0
capital: 1000
""".strip(), encoding="utf-8",
    )
    import v2.signals.llm_agent as agent_module
    monkeypatch.setattr(agent_module, "PromptCache", lambda: PromptCache(tmp_path / "llm-cache"))

    barrier = threading.Barrier(2)
    openai = BarrierLLM("openai", "gpt-test", barrier)
    anthropic = BarrierLLM("anthropic", "claude-test", barrier)
    first_id, first = _prepare_run(tmp_path / "first.db", spec_path, openai)
    second_id, second = _prepare_run(tmp_path / "second.db", spec_path, anthropic)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(first._run), pool.submit(second._run)]
        for future in futures:
            future.result(timeout=20)

    assert openai.calls == ["openai:gpt-test"]
    assert anthropic.calls == ["anthropic:claude-test"]
    assert __import__("os").environ["V2_LLM_PROVIDER"] == "must-not-be-used"
    assert __import__("os").environ["V2_LLM_MODEL"] == "must-not-be-used"
    with get_session(str(tmp_path / "first.db")) as session:
        run = session.execute(select(SimRun).where(SimRun.id == first_id)).scalar_one()
        assert (run.status, run.llm_provider, run.llm_model) == ("completed", "openai", "gpt-test")
    with get_session(str(tmp_path / "second.db")) as session:
        run = session.execute(select(SimRun).where(SimRun.id == second_id)).scalar_one()
        assert (run.status, run.llm_provider, run.llm_model) == ("completed", "anthropic", "claude-test")
