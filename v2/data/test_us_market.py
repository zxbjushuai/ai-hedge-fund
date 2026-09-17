from __future__ import annotations

from pathlib import Path
import sqlite3
import time

import pandas as pd
import pytest

from v2.data.cache_service import persist_prices, sync_us_catalog
from v2.data.cache_jobs import CacheJobManager
from v2.data.market import CatalogSecurity, parse_nasdaq_catalog, yahoo_symbol
from v2.data.models import Price
from v2.data.yfinance_client import YFinanceClient
from v2.persistence.database import get_session
from v2.persistence.models import PriceCache, Security


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

    monkeypatch.setattr("v2.data.yfinance_client.yf.Ticker", lambda ticker: Ticker())
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
    monkeypatch.setattr("v2.data.cache_jobs.USMarketDataAdapter.get_prices_batch", lambda self, tickers, start, end: {"AAA": [price]})
    monkeypatch.setattr("v2.data.cache_jobs.fetch_security_data", lambda db, ticker, start, end, kinds, force=False: {
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


@pytest.mark.live
def test_live_us_catalog_and_yahoo_contract():
    from v2.data.market import USMarketDataAdapter
    adapter = USMarketDataAdapter()
    catalog = adapter.sync_catalog()
    assert any(item.symbol == "SPY" and item.asset_type == "etf" for item in catalog)
    prices = adapter.get_prices("AAPL", "2026-09-01", "2026-09-05")
    assert prices and all(item.price_mode == "raw" and item.adjusted_close for item in prices)
    batch = adapter.get_prices_batch(["AAPL", "MSFT"], "2026-09-01", "2026-09-05")
    assert batch["AAPL"] and batch["MSFT"]
    assert all(item.adjusted_close is not None for values in batch.values() for item in values)
