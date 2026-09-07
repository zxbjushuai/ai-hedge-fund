import json
import sqlite3
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
from v2.simulation.runner import SimRunner, _trading_days, get_sim_result


def test_sessions_are_isolated_by_normalized_database_path(tmp_path: Path):
    first, second = tmp_path / "first.db", tmp_path / "second.db"
    init_db(str(first)); init_db(str(second))
    with get_session(str(first)) as session:
        session.add(PriceCache(ticker="AAA", date="2024-01-02", open=1, high=1, low=1, close=1, volume=1))
        session.commit()
    with get_session(str(second)) as session:
        assert session.execute(select(PriceCache)).scalars().all() == []


def test_trading_calendar_uses_benchmark_only_and_records_cycle_date(tmp_path: Path):
    db = tmp_path / "main.db"
    with get_session(str(db)) as session:
        for ticker, day in [
            ("AAA", "2024-01-05"),
            ("BBB", "2024-01-08"),
            ("AAA", "2024-01-08"),
            ("SPY", "2024-01-05"),
            ("SPY", "2024-01-08"),
        ]:
            session.add(PriceCache(ticker=ticker, date=day, open=10, high=12, low=9, close=11, volume=1))
        session.commit()
    assert _trading_days(str(db), "SPY", "2024-01-01", "2024-01-10") == [
        "2024-01-05", "2024-01-08",
    ]
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


def test_additive_migration_adds_nullable_benchmark_columns(tmp_path: Path):
    db = tmp_path / "legacy.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE sim_run (id INTEGER PRIMARY KEY)")
    connection.execute("CREATE TABLE sim_nav_snapshot (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()

    init_db(str(db))

    connection = sqlite3.connect(db)
    try:
        run_columns = {row[1] for row in connection.execute("PRAGMA table_info(sim_run)")}
        nav_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(sim_nav_snapshot)")
        }
    finally:
        connection.close()
    assert "benchmark" in run_columns
    assert "benchmark_nav" in nav_columns


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
        session.add(PriceCache(
            ticker="AAA", date="2024-05-16", open=20, high=20,
            low=20, close=20, volume=1,
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
    # A later market close must not mutate the quarterly LLM snapshot.
    later = client.get_financial_metrics("AAA", "2024-05-16")
    assert later[0].market_cap == 1000
    assert later[0].price_to_book_ratio == 2
    assert later[0].price_to_earnings_ratio == 5


def test_filing_prompt_call_estimate_ignores_daily_prices_and_counts_new_filings(tmp_path: Path):
    from v2.simulation.runner import estimate_filing_prompt_calls

    db = tmp_path / "estimate.db"
    days = ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]
    with get_session(str(db)) as session:
        for index, filing_date in enumerate(("2024-01-01", "2024-04-01", "2024-07-01", "2024-10-01")):
            metric = FinancialMetrics(ticker="AAA", report_period=f"2023-{index + 1:02d}-01", period="ttm")
            session.add(MetricsCache(
                ticker="AAA", report_period=metric.report_period,
                filing_date=filing_date, filing_date_source="test",
                data=metric.model_dump_json(exclude={"ticker"}),
            ))
        session.commit()

    assert estimate_filing_prompt_calls(str(db), ["AAA"], days, {"buffett", "graham"}) == 2

    with get_session(str(db)) as session:
        metric = FinancialMetrics(ticker="AAA", report_period="2024-12-31", period="ttm")
        session.add(MetricsCache(
            ticker="AAA", report_period=metric.report_period,
            filing_date="2025-01-06", filing_date_source="test",
            data=metric.model_dump_json(exclude={"ticker"}),
        ))
        session.commit()

    assert estimate_filing_prompt_calls(str(db), ["AAA"], days, {"buffett", "graham"}) == 4


def test_cache_api_keeps_missing_yahoo_surprise_neutral(tmp_path: Path, monkeypatch):
    import app.backend.routes.dashboard as dashboard
    import v2.data.yfinance_client as yahoo_module

    class FakeYahoo:
        def get_prices(self, ticker, start_date, end_date):
            return [Price(open=10, high=10, low=10, close=10, volume=1, time="2025-01-02")]

        def get_financial_metrics(self, ticker, end_date, limit=40):
            return [FinancialMetrics(ticker=ticker, report_period="2024-09-30", period="ttm")]

        def get_earnings_history(self, ticker, limit=40):
            return [EarningsRecord(
                ticker=ticker, report_period="2024-09-30", source_type="earnings",
                filing_date="2024-11-01",
                quarterly=EarningsData(earnings_per_share=2.0),
            )]

        def close(self):
            pass

    db = tmp_path / "earnings-neutral.db"
    monkeypatch.setattr(dashboard, "_DB_PATH", str(db))
    monkeypatch.setattr(yahoo_module, "YFinanceClient", FakeYahoo)

    result = dashboard.cache_fetch(dashboard.CacheFetchRequest(
        tickers=["AAA"], start_date="2024-01-01", end_date="2025-01-02",
    ))
    assert "PEAD will remain neutral" in " ".join(result["results"]["AAA"]["warnings"])
    with get_session(str(db)) as session:
        event = session.execute(select(EarningsCache)).scalar_one()
        assert event.actual_eps == 2.0
        assert event.estimated_eps is None
        assert event.surprise_pct is None
        assert event.source == "yahoo"


def test_cache_api_fetches_non_tradeable_benchmark_prices_only(tmp_path: Path, monkeypatch):
    import app.backend.routes.dashboard as dashboard
    import v2.data.yfinance_client as yahoo_module

    calls = {"prices": [], "metrics": [], "earnings": []}

    class FakeYahoo:
        def get_prices(self, ticker, start_date, end_date):
            calls["prices"].append(ticker)
            return [Price(open=10, high=10, low=10, close=10, volume=1, time="2025-01-02")]

        def get_financial_metrics(self, ticker, end_date, limit=40):
            calls["metrics"].append(ticker)
            return []

        def get_earnings_history(self, ticker, limit=40):
            calls["earnings"].append(ticker)
            return []

        def close(self):
            pass

    db = tmp_path / "benchmark-cache.db"
    monkeypatch.setattr(dashboard, "_DB_PATH", str(db))
    monkeypatch.setattr(yahoo_module, "YFinanceClient", FakeYahoo)
    result = dashboard.cache_fetch(dashboard.CacheFetchRequest(
        tickers=["AAA"], benchmark="spy",
        start_date="2025-01-01", end_date="2025-01-02",
    ))

    assert calls == {
        "prices": ["AAA", "SPY"], "metrics": ["AAA"], "earnings": ["AAA"],
    }
    assert result["benchmark"] == {"ticker": "SPY", "prices": 1, "error": None}
    with get_session(str(db)) as session:
        assert session.query(PriceCache).filter_by(ticker="SPY").count() == 1
        assert session.query(MetricsCache).filter_by(ticker="SPY").count() == 0
        assert session.query(EarningsCache).filter_by(ticker="SPY").count() == 0


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
            session.add(PriceCache(
                ticker="SPY", date=day, open=100, high=102,
                low=99, close=100 + (int(day[-2:]) - 10), volume=100,
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
        initial_capital=1000, benchmark="SPY",
        db_path=str(db), fund_spec_path=str(spec_path),
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
        assert navs[0].benchmark_nav == 1000
        assert navs[-1].benchmark_nav == pytest.approx(1020)
        assert all(trade.ticker != "SPY" for trade in trades)
        assert session.execute(select(TradeLog)).scalars().all() == []

    result = get_sim_result(sim_id, str(db))
    assert result is not None
    assert result["benchmark"] == "SPY"
    assert result["benchmark_return_pct"] == pytest.approx(2.0)
    assert result["excess_return_pct"] == pytest.approx(
        result["total_return_pct"] - 2.0
    )
    assert result["nav_curve"][-1]["benchmark_nav"] == pytest.approx(1020)


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
            session.add(PriceCache(
                ticker="SPY", date=day, open=100, high=101,
                low=99, close=100, volume=100,
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
            session.add(PriceCache(ticker="SPY", date=day, open=100, high=101, low=99, close=100, volume=1))
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
    assert result["benchmark"] == "SPY"
    assert result["model"] == "test-model"
    assert "PEAD disabled" in " ".join(result["warnings"])


def test_preflight_requires_benchmark_cache(tmp_path: Path, monkeypatch):
    import app.backend.routes.dashboard as dashboard

    db = tmp_path / "missing-benchmark.db"
    monkeypatch.setattr(dashboard, "_DB_PATH", str(db))
    with get_session(str(db)) as session:
        session.add(PriceCache(
            ticker="AAA", date="2025-01-02", open=10, high=11,
            low=9, close=10, volume=1,
        ))
        session.commit()

    request = dashboard.SimRunRequest(
        tickers=["AAA"], benchmark="QQQ",
        start_date="2025-01-01", end_date="2025-01-03",
        initial_capital=1000,
    )
    with pytest.raises(HTTPException) as exc_info:
        dashboard.sim_preflight(request)
    assert exc_info.value.status_code == 422
    assert "fetch benchmark prices" in " ".join(exc_info.value.detail["errors"])


def test_old_simulation_result_keeps_benchmark_fields_null(tmp_path: Path):
    db = tmp_path / "old-result.db"
    with get_session(str(db)) as session:
        run = SimRun(
            name="legacy", tickers=json.dumps(["AAA"]), benchmark=None,
            start_date="2024-01-01", end_date="2024-01-02",
            initial_capital=1000, final_nav=1000, status="completed", total_days=1,
        )
        session.add(run)
        session.flush()
        session.add(SimNavSnapshot(
            sim_run_id=run.id, cycle_date="2024-01-02", nav=1000,
            cash=1000, equity=0, benchmark_nav=None,
        ))
        session.commit()
        sim_id = run.id

    result = get_sim_result(sim_id, str(db))
    assert result is not None
    assert result["benchmark"] is None
    assert result["benchmark_return_pct"] is None
    assert result["excess_return_pct"] is None
    assert result["nav_curve"][0]["benchmark_nav"] is None


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
