from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from v2.brokers import SimBroker
from v2.brokers.models import Order
from v2.persistence.database import get_session, init_db
from v2.data.models import EarningsData, EarningsRecord, FinancialMetrics, Price
from v2.data.mock_client import MockDataClient
from v2.models import Signal
from v2.persistence.models import (
    EarningsCache,
    MetricsCache,
    PriceCache,
    SimNavSnapshot,
    SimRun,
    SimTradeLog,
    TradeLog,
)
from v2.signals.base import AlphaModel
from v2.simulation.runner import SimRunner, _trading_days


def test_sessions_are_isolated_by_normalized_database_path(tmp_path: Path):
    first, second = tmp_path / "first.db", tmp_path / "second.db"
    init_db(str(first)); init_db(str(second))
    with get_session(str(first)) as session:
        session.add(PriceCache(ticker="AAA", date="2024-01-02", open=1, high=1, low=1, close=1, volume=1))
        session.commit()
    with get_session(str(second)) as session:
        assert session.execute(select(PriceCache)).scalars().all() == []


def test_trading_calendar_requires_bars_for_whole_universe_and_records_cycle_date(tmp_path: Path):
    db = tmp_path / "main.db"
    with get_session(str(db)) as session:
        for ticker, day in [
            ("AAA", "2024-01-05"),
            ("BBB", "2024-01-08"),
            ("AAA", "2024-01-08"),
        ]:
            session.add(PriceCache(ticker=ticker, date=day, open=10, high=12, low=9, close=11, volume=1))
        session.commit()
    assert _trading_days(str(db), ["AAA", "BBB"], "2024-01-01", "2024-01-10") == ["2024-01-08"]
    broker = SimBroker(1000)
    broker.place_order(Order(ticker="AAA", side="buy", quantity=1, price=10), cycle_date="2024-01-08")
    assert broker._last_trades[0]["cycle_date"] == "2024-01-08"


def test_earnings_cache_schema(tmp_path: Path):
    db = tmp_path / "schema.db"
    init_db(str(db))
    with get_session(str(db)) as session:
        session.add(EarningsCache(ticker="AAA", report_period="2024-01-01", announcement_date="2024-01-20", actual_eps=2, estimated_eps=1, surprise_pct=100))
        session.commit()
        assert session.execute(select(EarningsCache)).scalar_one().surprise_pct == 100


def test_mock_client_hides_metrics_until_estimated_filing_date(tmp_path: Path):
    db = tmp_path / "point-in-time.db"
    metric = FinancialMetrics(
        ticker="AAA", report_period="2024-03-31", period="ttm",
        filing_date="2024-05-15", return_on_equity=0.2,
        shares_outstanding=100, earnings_per_share=2,
        book_value_per_share=5,
    )
    with get_session(str(db)) as session:
        session.add(PriceCache(
            ticker="AAA", date="2024-05-15", open=10, high=10,
            low=10, close=10, volume=1,
        ))
        session.add(MetricsCache(
            ticker="AAA", report_period="2024-03-31",
            filing_date="2024-05-15", filing_date_source="estimated_45d",
            data=metric.model_dump_json(exclude={"ticker"}),
        ))
        session.commit()
    client = MockDataClient(str(db))
    assert client.get_financial_metrics("AAA", "2024-05-14") == []
    visible = client.get_financial_metrics("AAA", "2024-05-15")
    assert len(visible) == 1
    assert visible[0].filing_date == "2024-05-15"
    assert visible[0].market_cap == 1000
    assert visible[0].price_to_book_ratio == 2
    assert visible[0].price_to_earnings_ratio == 5


class _BullishModel(AlphaModel):
    @property
    def name(self) -> str:
        return "fake_ai"

    def predict(self, ticker, date, data_client):
        return Signal(model_name=self.name, ticker=ticker, date=date, value=1.0)


def test_runner_uses_prior_signal_next_open_and_isolated_sim_tables(tmp_path: Path, monkeypatch):
    db = tmp_path / "simulation.db"
    spec_path = tmp_path / "fund.yaml"
    spec_path.write_text(
        """
name: historical-test
universe: [AAA]
strategies:
  - name: mixed
    models:
      - name: fake_ai
      - name: pead
risk:
  max_position_pct: 1.0
  max_gross_exposure: 1.0
capital: 1000
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setitem(__import__("v2.fund.spec", fromlist=["ALPHA_MODEL_REGISTRY"]).ALPHA_MODEL_REGISTRY, "fake_ai", _BullishModel)

    with get_session(str(db)) as session:
        for day, open_, close in [
            ("2024-01-10", 10, 11),
            ("2024-01-11", 12, 13),
            ("2024-01-12", 13, 14),
        ]:
            session.add(PriceCache(
                ticker="AAA", date=day, open=open_, high=close,
                low=open_, close=close, volume=100,
            ))
        for index, report_period in enumerate(("2022-09-30", "2022-12-31", "2023-03-31", "2023-06-30")):
            metric = FinancialMetrics(
                ticker="AAA", report_period=report_period, period="ttm",
                filing_date=f"2023-0{index + 1}-01",
            )
            session.add(MetricsCache(
                ticker="AAA", report_period=report_period,
                filing_date=f"2023-0{index + 1}-01",
                filing_date_source="test", data=metric.model_dump_json(exclude={"ticker"}),
            ))
        session.add(EarningsCache(
            ticker="AAA", report_period="2024-01-10",
            announcement_date="2024-01-10", actual_eps=2,
            estimated_eps=1, surprise_pct=100,
        ))
        session.commit()

    sim_id = SimRunner.create(
        tickers=["AAA"], start_date="2024-01-10", end_date="2024-01-12",
        initial_capital=1000, db_path=str(db), fund_spec_path=str(spec_path),
    )
    runner = SimRunner._get(sim_id)
    assert runner is not None
    runner._run()

    with get_session(str(db)) as session:
        run = session.get(SimRun, sim_id)
        trades = session.execute(select(SimTradeLog).where(SimTradeLog.sim_run_id == sim_id)).scalars().all()
        navs = session.execute(select(SimNavSnapshot).where(SimNavSnapshot.sim_run_id == sim_id).order_by(SimNavSnapshot.cycle_date)).scalars().all()
        assert run.status == "completed"
        assert run.current_day == 3
        assert trades and trades[0].cycle_date == "2024-01-11"
        assert trades[0].price == 12
        assert navs[-1].cycle_date == "2024-01-12"
        assert navs[-1].nav > 1000
        assert session.execute(select(TradeLog)).scalars().all() == []


def test_sim_api_requires_confirmation_for_cold_cache_upper_bound(tmp_path: Path, monkeypatch):
    import app.backend.routes.dashboard as dashboard
    import v2.llm

    db = tmp_path / "api.db"
    monkeypatch.setattr(dashboard, "_DB_PATH", str(db))
    monkeypatch.setattr(v2.llm, "get_llm", lambda: SimpleNamespace(model="fake-llm"))
    with get_session(str(db)) as session:
        for day in ("2025-01-02", "2025-06-30"):
            session.add(PriceCache(
                ticker="AAA", date=day, open=10, high=11,
                low=9, close=10, volume=100,
            ))
        filing_dates = [
            "2023-01-01", "2023-04-01", "2023-07-01", "2023-10-01",
            "2025-01-15", "2025-02-15", "2025-03-15", "2025-04-15",
            "2025-05-15", "2025-06-01", "2025-06-15",
        ]
        for index, filing_date in enumerate(filing_dates):
            report_period = f"2022-{index + 1:02d}-01"
            metric = FinancialMetrics(ticker="AAA", report_period=report_period, period="ttm")
            session.add(MetricsCache(
                ticker="AAA", report_period=report_period,
                filing_date=filing_date, filing_date_source="test",
                data=metric.model_dump_json(exclude={"ticker"}),
            ))
        session.add(EarningsCache(
            ticker="AAA", report_period="2025-01-01",
            announcement_date="2025-01-02", actual_eps=2,
            estimated_eps=1, surprise_pct=100,
        ))
        session.commit()

    request = dashboard.SimRunRequest(
        tickers=["AAA"], start_date="2025-01-01", end_date="2025-06-30",
        initial_capital=1000,
    )
    with pytest.raises(HTTPException) as exc_info:
        dashboard.sim_run(request)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["estimated_llm_calls"] == 3


def test_preflight_always_exposes_call_estimate(tmp_path: Path, monkeypatch):
    import app.backend.routes.dashboard as dashboard
    import v2.llm

    db = tmp_path / "preflight.db"
    monkeypatch.setattr(dashboard, "_DB_PATH", str(db))
    monkeypatch.setattr(v2.llm, "get_llm", lambda: SimpleNamespace(model="test-model"))
    with get_session(str(db)) as session:
        for day in ("2025-01-02", "2025-01-03"):
            session.add(PriceCache(ticker="AAA", date=day, open=10, high=11, low=9, close=10, volume=1))
        for index, filing_date in enumerate(("2023-01-01", "2023-04-01", "2023-07-01", "2023-10-01")):
            report_period = f"2022-{index + 1:02d}-01"
            metric = FinancialMetrics(ticker="AAA", report_period=report_period, period="ttm")
            session.add(MetricsCache(
                ticker="AAA", report_period=report_period, filing_date=filing_date,
                filing_date_source="test", data=metric.model_dump_json(exclude={"ticker"}),
            ))
        session.commit()
    request = dashboard.SimRunRequest(
        tickers=["AAA"], start_date="2025-01-01", end_date="2025-01-03",
        initial_capital=1000,
    )
    result = dashboard.sim_preflight(request)
    assert result["estimated_llm_calls"] == 3
    assert result["trading_days"] == 2
    assert result["model"] == "test-model"
    assert "PEAD disabled" in " ".join(result["warnings"])


def test_cache_api_upserts_prices_metrics_and_earnings(tmp_path: Path, monkeypatch):
    import app.backend.routes.dashboard as dashboard
    import v2.data.yfinance_client as yahoo_module

    class FakeYahoo:
        def get_prices(self, ticker, start_date, end_date):
            return [Price(open=10, high=12, low=9, close=11, volume=100, time="2025-01-02T00:00:00")]

        def get_financial_metrics(self, ticker, end_date, limit=40):
            return [FinancialMetrics(
                ticker=ticker, report_period="2024-09-30", period="ttm",
                market_cap=999, return_on_equity=0.2,
            )]

        def get_earnings_history(self, ticker, limit=40):
            return [EarningsRecord(
                ticker=ticker, report_period="2024-09-30", source_type="earnings",
                filing_date="2024-11-01",
                quarterly=EarningsData(
                    earnings_per_share=2, estimated_earnings_per_share=1,
                    eps_surprise="BEAT",
                ),
            )]

        def close(self):
            pass

    db = tmp_path / "cache-api.db"
    monkeypatch.setattr(dashboard, "_DB_PATH", str(db))
    monkeypatch.setattr(yahoo_module, "YFinanceClient", FakeYahoo)
    result = dashboard.cache_fetch(dashboard.CacheFetchRequest(
        tickers=["aaa"], start_date="2025-01-01", end_date="2025-01-02",
    ))
    assert result["results"]["AAA"] == {
        "prices": 1, "metrics": 1, "earnings": 1,
        "error": None, "warnings": [],
    }
    listed = dashboard.cache_list()["cached"]["AAA"]
    assert listed["prices"]["count"] == 1
    assert listed["metrics"]["count"] == 1
    assert listed["earnings"]["count"] == 1
    with get_session(str(db)) as session:
        cached_metric = session.execute(select(MetricsCache)).scalar_one()
        assert "market_cap" not in __import__("json").loads(cached_metric.data)
        assert cached_metric.filing_date == "2024-11-14"


def test_modelscope_provider_uses_openai_compatible_configuration(monkeypatch):
    import openai
    from v2.llm.client import ModelScopeLLM

    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"signal":"neutral"}')
            )])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("MODELSCOPE_API_KEY", "test-token")
    monkeypatch.setenv("V2_LLM_BASE_URL", "https://api-inference.modelscope.cn/v1/")
    client = ModelScopeLLM(model="Qwen/Qwen3-4B")
    assert client.complete("system", "user") == '{"signal":"neutral"}'
    assert captured["base_url"] == "https://api-inference.modelscope.cn/v1/"
    assert captured["model"] == "Qwen/Qwen3-4B"


def test_openrouter_provider_uses_free_router(monkeypatch):
    import openai
    from v2.llm.client import OpenRouterLLM

    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"signal":"neutral"}')
            )])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-token")
    monkeypatch.delenv("V2_LLM_MODEL", raising=False)
    monkeypatch.delenv("V2_LLM_BASE_URL", raising=False)
    client = OpenRouterLLM()
    assert client.complete("system", "user") == '{"signal":"neutral"}'
    assert captured["base_url"] == "https://openrouter.ai/api/v1"
    assert captured["model"] == "openrouter/free"
