from __future__ import annotations

from pathlib import Path
import sqlite3
import time

import pandas as pd
import pytest

from hedge_fund.data.cache_service import fetch_security_data, persist_prices, plan_price_fetch, sync_us_catalog
from hedge_fund.data.cache_jobs import CacheJobManager
from hedge_fund.data.market import CatalogSecurity, parse_nasdaq_catalog, yahoo_symbol
from hedge_fund.data.models import Price
from hedge_fund.data.yfinance_client import YFinanceClient
from hedge_fund.persistence.database import get_session
from hedge_fund.persistence.models import PriceCache, Security


NASDAQ = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust|G|N|N|100|Y|N
ZTEST|Nasdaq Test Stock|Q|Y|N|100|N|N
File Creation Time: 20260916||||||||
"""
OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY
ABC.W|ABC Warrants|N|ABC.W|N|100|N|ABC.W
File Creation Time: 20260916||||||||
"""


def test_catalog_parser_classifies_and_maps_symbols():
    rows = {item.symbol: item for item in parse_nasdaq_catalog(NASDAQ, OTHER)}
    assert rows["AAPL"].asset_type == "equity"
    assert rows["QQQ"].asset_type == "etf"
    assert rows["SPY"].exchange == "NYSE Arca"
    assert rows["ABC.W"].selectable is False
    assert rows["ZTEST"].is_test is True
    assert yahoo_symbol("BRK.B") == "BRK-B"


def test_catalog_sync_is_idempotent_and_deactivates_missing(tmp_path: Path):
    class Adapter:
        def __init__(self):
            self.rows = [CatalogSecurity("US", "AAA", "AAA", "AAA Inc", "NASDAQ", "equity")]

        def sync_catalog(self):
            return self.rows

    adapter = Adapter()
    db = str(tmp_path / "catalog.db")
    first = sync_us_catalog(db, adapter)  # type: ignore[arg-type]
    second = sync_us_catalog(db, adapter)  # type: ignore[arg-type]
    assert first["created"] == 1
    assert second["created"] == 0
    adapter.rows = [CatalogSecurity("US", "BBB", "BBB", "BBB Inc", "NYSE", "equity")]
    third = sync_us_catalog(db, adapter)  # type: ignore[arg-type]
    assert third["deactivated"] == 1
    with get_session(db) as session:
        assert session.query(Security).filter_by(symbol="AAA").one().active is False


def test_yahoo_prices_explicitly_request_raw_actions(monkeypatch):
    called = {}
    frame = pd.DataFrame(
        [{"Open": 10, "High": 11, "Low": 9, "Close": 10.5, "Adj Close": 10.25, "Volume": 100, "Dividends": 0.2, "Stock Splits": 2.0}],
        index=[pd.Timestamp("2024-01-02", tz="America/New_York")],
    )

    class Ticker:
        def history(self, **kwargs):
            called.update(kwargs)
            return frame

    monkeypatch.setattr("hedge_fund.data.yfinance_client.yf.Ticker", lambda ticker: Ticker())
    rows = YFinanceClient().get_prices("AAA", "2024-01-01", "2024-01-02")
    assert called["auto_adjust"] is False
    assert called["back_adjust"] is False
    assert called["actions"] is True
    assert rows[0].adjusted_close == 10.25
    assert rows[0].dividend == 0.2
    assert rows[0].split_ratio == 2.0


def test_persisted_price_has_raw_provenance_and_coverage(tmp_path: Path):
    db = str(tmp_path / "prices.db")
    result = persist_prices(db, "AAA", [Price(
        open=10, high=11, low=9, close=10.5, adjusted_close=10.25,
        volume=100, dividend=0.2, split_ratio=2, source="yahoo",
        price_mode="raw", time="2024-01-02T00:00:00-05:00",
    )], "2024-01-02", "2024-01-02")
    assert result["status"] == "complete"
    with get_session(db) as session:
        row = session.query(PriceCache).one()
        assert row.price_mode == "raw"
        assert row.adjusted_close == 10.25


def _price(day: str, *, dividend: float = 0.0, split_ratio: float = 0.0) -> Price:
    return Price(
        open=10, high=11, low=9, close=10.5, adjusted_close=10.25,
        volume=100, dividend=dividend, split_ratio=split_ratio,
        source="yahoo", price_mode="raw", time=day,
    )


def test_second_price_request_fetches_only_new_sessions(tmp_path: Path):
    calls: list[tuple[str, str]] = []

    class Adapter:
        def get_prices(self, ticker: str, start_date: str, end_date: str):
            calls.append((start_date, end_date))
            return [_price(day) for day in ("2024-01-02", "2024-01-03") if start_date <= day <= end_date]

    db = str(tmp_path / "incremental.db")
    adapter = Adapter()
    first = fetch_security_data(db, "AAA", "2024-01-02", "2024-01-02", adapter=adapter)  # type: ignore[arg-type]
    second = fetch_security_data(db, "AAA", "2024-01-02", "2024-01-03", adapter=adapter)  # type: ignore[arg-type]

    assert first["prices"]["status"] == "complete"
    assert second["prices"]["status"] == "complete"
    assert second["prices"]["incremental"] is True
    assert second["prices"]["fetch_start"] == "2024-01-03"
    assert calls == [("2024-01-02", "2024-01-02"), ("2024-01-03", "2024-01-03")]


def test_price_plan_supports_dates_before_default_calendar_bounds(tmp_path: Path):
    plan = plan_price_fetch(str(tmp_path / "historical.db"), "AAA", "1990-01-02", "1990-01-03")
    assert plan["status"] == "fetch"
    assert plan["fetch_start"] == "1990-01-02"


def test_incremental_request_refreshes_a_pre_close_session(tmp_path: Path, monkeypatch):
    calls: list[tuple[str, str]] = []

    class Adapter:
        def get_prices(self, ticker: str, start_date: str, end_date: str):
            calls.append((start_date, end_date))
            return [_price(day) for day in ("2024-01-02", "2024-01-03") if start_date <= day <= end_date]

    db = str(tmp_path / "provisional.db")
    adapter = Adapter()
    monkeypatch.setattr("hedge_fund.data.cache_service._now", lambda: "2024-01-02T20:00:00+00:00")
    fetch_security_data(db, "AAA", "2024-01-02", "2024-01-02", adapter=adapter)  # type: ignore[arg-type]
    monkeypatch.setattr("hedge_fund.data.cache_service._now", lambda: "2024-01-03T22:00:00+00:00")
    fetch_security_data(db, "AAA", "2024-01-02", "2024-01-03", adapter=adapter)  # type: ignore[arg-type]

    assert calls == [("2024-01-02", "2024-01-02"), ("2024-01-02", "2024-01-03")]


def test_extended_price_range_without_sessions_is_skipped(tmp_path: Path):
    calls: list[tuple[str, str]] = []

    class Adapter:
        def get_prices(self, ticker: str, start_date: str, end_date: str):
            calls.append((start_date, end_date))
            return [_price("2024-01-05")]

    db = str(tmp_path / "weekend.db")
    adapter = Adapter()
    fetch_security_data(db, "AAA", "2024-01-05", "2024-01-05", adapter=adapter)  # type: ignore[arg-type]
    result = fetch_security_data(db, "AAA", "2024-01-05", "2024-01-07", adapter=adapter)  # type: ignore[arg-type]

    assert result["prices"]["status"] == "skipped"
    assert result["prices"]["reason"] == "no missing US trading sessions"
    assert calls == [("2024-01-05", "2024-01-05")]


def test_incremental_price_with_corporate_action_refreshes_full_range(tmp_path: Path):
    calls: list[tuple[str, str]] = []

    class Adapter:
        def get_prices(self, ticker: str, start_date: str, end_date: str):
            calls.append((start_date, end_date))
            rows = [_price("2024-01-02"), _price("2024-01-03", split_ratio=2.0)]
            return [row for row in rows if start_date <= row.time <= end_date]

    db = str(tmp_path / "action.db")
    adapter = Adapter()
    fetch_security_data(db, "AAA", "2024-01-02", "2024-01-02", adapter=adapter)  # type: ignore[arg-type]
    result = fetch_security_data(db, "AAA", "2024-01-02", "2024-01-03", adapter=adapter)  # type: ignore[arg-type]

    assert result["prices"]["requested_start"] == "2024-01-02"
    assert result["prices"]["incremental"] is False
    assert result["prices"]["refreshed_for_corporate_action"] is True
    assert calls == [
        ("2024-01-02", "2024-01-02"),
        ("2024-01-03", "2024-01-03"),
        ("2024-01-02", "2024-01-03"),
    ]
    with get_session(db) as session:
        assert [row.date for row in session.query(PriceCache).order_by(PriceCache.date).all()] == ["2024-01-02", "2024-01-03"]


def test_forced_price_fetch_refreshes_full_range(tmp_path: Path):
    calls: list[tuple[str, str]] = []

    class Adapter:
        def get_prices(self, ticker: str, start_date: str, end_date: str):
            calls.append((start_date, end_date))
            return [_price(day) for day in ("2024-01-02", "2024-01-03") if start_date <= day <= end_date]

    db = str(tmp_path / "forced.db")
    adapter = Adapter()
    fetch_security_data(db, "AAA", "2024-01-02", "2024-01-03", adapter=adapter)  # type: ignore[arg-type]
    fetch_security_data(db, "AAA", "2024-01-02", "2024-01-03", force=True, adapter=adapter)  # type: ignore[arg-type]

    assert calls == [("2024-01-02", "2024-01-03"), ("2024-01-02", "2024-01-03")]


def test_legacy_price_migration_does_not_claim_raw_provenance(tmp_path: Path):
    db = tmp_path / "legacy.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE price_cache (id INTEGER PRIMARY KEY, ticker VARCHAR(10), date VARCHAR(10), open FLOAT, high FLOAT, low FLOAT, close FLOAT, volume INTEGER, created_at VARCHAR(26))")
    connection.execute("INSERT INTO price_cache VALUES (1, 'AAA', '2024-01-02', 10, 11, 9, 10, 100, '')")
    connection.commit()
    connection.close()
    with get_session(str(db)) as session:
        row = session.query(PriceCache).one()
        assert row.price_mode == "legacy_unknown"
        assert row.adjusted_close is None


def test_cache_job_keeps_partial_success_and_exposes_retryable_item(tmp_path: Path, monkeypatch):
    price = Price(open=10, high=11, low=9, close=10, adjusted_close=10, volume=100, time="2024-01-02", source="yahoo", price_mode="raw")
    monkeypatch.setattr("hedge_fund.data.cache_jobs.USMarketDataAdapter.get_prices_batch", lambda self, tickers, start, end: {"AAA": [price]})
    monkeypatch.setattr("hedge_fund.data.cache_jobs.fetch_security_data", lambda db, ticker, start, end, kinds, force=False: {
        "ticker": ticker, "warnings": [], "prices": {"status": "failed", "error_category": "timeout", "error": "timed out"},
    })
    manager = CacheJobManager(str(tmp_path / "jobs.db"))
    job = manager.create(["AAA", "BBB"], "AAA", "2024-01-02", "2024-01-02", ["prices"])
    for _ in range(200):
        job = manager.get(job["id"])
        if job and job["status"] not in {"pending", "running", "cancelling"}:
            break
        time.sleep(0.01)
    assert job["status"] == "partial"
    assert job["items"]["AAA"]["prices"]["status"] == "complete"
    assert job["items"]["BBB"]["prices"]["error_category"] == "timeout"
    retried = manager.retry(job["id"])
    assert retried and retried["tickers"] == ["BBB"]
    for _ in range(200):
        retried = manager.get(retried["id"])
        if retried and retried["status"] not in {"pending", "running", "cancelling"}:
            break
        time.sleep(0.01)
    assert retried and retried["status"] == "partial"
    assert retried["items"]["BBB"]["prices"]["error_category"] == "timeout"


def test_cache_job_batches_only_new_sessions(tmp_path: Path, monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_batch(self, tickers, start_date, end_date):
        calls.append((start_date, end_date))
        day = start_date
        return {ticker: [_price(day)] for ticker in tickers}

    monkeypatch.setattr("hedge_fund.data.cache_jobs.USMarketDataAdapter.get_prices_batch", fake_batch)
    manager = CacheJobManager(str(tmp_path / "incremental-jobs.db"))

    def finish(job):
        for _ in range(200):
            job = manager.get(job["id"])
            if job and job["status"] not in {"pending", "running", "cancelling"}:
                return job
            time.sleep(0.01)
        raise AssertionError("cache job did not finish")

    first = finish(manager.create(["AAA"], "AAA", "2024-01-02", "2024-01-02", ["prices"]))
    second = finish(manager.create(["AAA"], "AAA", "2024-01-02", "2024-01-03", ["prices"]))

    assert first["status"] == "completed"
    assert second["status"] == "completed"
    assert calls == [("2024-01-02", "2024-01-02"), ("2024-01-03", "2024-01-03")]


def test_cache_job_finalizes_when_planning_fails(tmp_path: Path, monkeypatch):
    def fail_plan(*args, **kwargs):
        raise ValueError("calendar unavailable")

    monkeypatch.setattr("hedge_fund.data.cache_jobs.plan_price_fetch", fail_plan)
    manager = CacheJobManager(str(tmp_path / "plan-failure.db"))
    job = manager.create(["AAA"], "AAA", "2024-01-02", "2024-01-02", ["prices"])
    for _ in range(200):
        job = manager.get(job["id"])
        if job and job["status"] not in {"pending", "running", "cancelling"}:
            break
        time.sleep(0.01)

    assert job["status"] == "failed"
    assert job["items"]["AAA"]["prices"]["error_category"] == "internal"


@pytest.mark.live
def test_live_us_catalog_and_yahoo_contract():
    from hedge_fund.data.market import USMarketDataAdapter
    adapter = USMarketDataAdapter()
    catalog = adapter.sync_catalog()
    assert any(item.symbol == "SPY" and item.asset_type == "etf" for item in catalog)
    prices = adapter.get_prices("AAPL", "2026-09-01", "2026-09-05")
    assert prices and all(item.price_mode == "raw" and item.adjusted_close for item in prices)
    batch = adapter.get_prices_batch(["AAPL", "MSFT"], "2026-09-01", "2026-09-05")
    assert batch["AAPL"] and batch["MSFT"]
    assert all(item.adjusted_close is not None for values in batch.values() for item in values)
