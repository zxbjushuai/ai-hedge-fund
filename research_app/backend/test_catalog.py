from pathlib import Path

from research_app.backend.routes import securities, universes, cache, schemas
from hedge_fund.persistence.database import get_session
from hedge_fund.persistence.models import CacheCoverage, EarningsCache, MetricsCache, PriceCache, Security


def _seed(db: str):
    with get_session(db) as session:
        session.add_all([
            Security(market="US", symbol="AAPL", data_symbol="AAPL", name="Apple Inc", exchange="NASDAQ", asset_type="equity", currency="USD", active=True, is_test=False, selectable=True, synced_at="now"),
            Security(market="US", symbol="SPY", data_symbol="SPY", name="SPDR ETF", exchange="NYSE Arca", asset_type="etf", currency="USD", active=True, is_test=False, selectable=True, synced_at="now"),
        ])
        session.commit()


def test_security_search_and_saved_universe_round_trip(tmp_path: Path, monkeypatch):
    db = str(tmp_path / "dashboard.db")
    for module in (securities, universes, cache):
        monkeypatch.setattr(module, "_DB_PATH", db)
    _seed(db)
    search = securities.securities_list(search="apple", exchange=None, asset_type=None, active=True, selectable=True, page=1, page_size=50, sort_by="symbol", sort_dir="asc")
    assert [item["symbol"] for item in search["items"]] == ["AAPL"]
    ids = [item["id"] for item in securities.securities_list(search="", exchange=None, asset_type=None, active=True, selectable=True, page=1, page_size=50, sort_by="symbol", sort_dir="asc")["items"]]
    created = universes.universe_create(schemas.UniverseCreateRequest(name="Core", security_ids=ids))
    assert [item["symbol"] for item in created["securities"]] == ["AAPL", "SPY"]
    assert universes.universes_list()["universes"][0]["name"] == "Core"
    archived = universes.universe_update(created["id"], schemas.UniverseUpdateRequest(archived=True))
    assert archived["archived"] is True
    assert universes.universes_list()["universes"] == []


def test_cache_selection_preserves_explicit_order(tmp_path: Path, monkeypatch):
    db = str(tmp_path / "selection.db")
    for module in (securities, universes, cache):
        monkeypatch.setattr(module, "_DB_PATH", db)
    _seed(db)
    items = securities.securities_list(search="", exchange=None, asset_type=None, active=True, selectable=True, page=1, page_size=50, sort_by="symbol", sort_dir="asc")["items"]
    ids = {item["symbol"]: item["id"] for item in items}
    selection = schemas.CacheSelectionRequest(security_ids=[ids["SPY"], ids["AAPL"]])
    assert cache._resolve_cache_selection(selection) == ["SPY", "AAPL"]


def test_complete_filtered_selection_returns_ids_and_respects_sort(tmp_path: Path, monkeypatch):
    db = str(tmp_path / "selection-all.db")
    for module in (securities, universes, cache):
        monkeypatch.setattr(module, "_DB_PATH", db)
    _seed(db)
    result = securities.securities_selection(
        search="", exchange=None, asset_type=None, sort_by="symbol", sort_dir="desc",
    )
    assert [item["symbol"] for item in result["items"]] == ["SPY", "AAPL"]
    assert all(isinstance(item["id"], int) for item in result["items"])


def test_cached_security_inventory_and_detail(tmp_path: Path, monkeypatch):
    db = str(tmp_path / "cache-detail.db")
    for module in (securities, universes, cache):
        monkeypatch.setattr(module, "_DB_PATH", db)
    _seed(db)
    with get_session(db) as session:
        session.add(PriceCache(
            ticker="AAPL", date="2024-01-02", open=10, high=11, low=9,
            close=10.5, adjusted_close=10.25, volume=123, dividend=0.2,
            split_ratio=0, source="yahoo", price_mode="raw",
        ))
        session.add(MetricsCache(
            ticker="AAPL", report_period="2023-12-31", filing_date="2024-02-14",
            filing_date_source="estimated_45d", data='{"market_cap": 100}',
        ))
        session.add(EarningsCache(
            ticker="AAPL", report_period="2023-12-31", announcement_date="2024-02-01",
            actual_eps=2, estimated_eps=1.8, surprise_pct=11.11, source="yahoo",
        ))
        session.add(CacheCoverage(
            market="US", ticker="AAPL", data_kind="prices",
            requested_start="2024-01-01", requested_end="2024-01-31",
            actual_start="2024-01-02", actual_end="2024-01-02", row_count=1,
            expected_sessions=21, missing_sessions=20, status="partial",
            fetched_at="2024-02-01T00:00:00+00:00",
        ))
        session.commit()
    inventory = cache.cached_securities_list(
        search="apple", status=None, price_mode="raw", page=1, page_size=20,
        sort_by="latest_volume", sort_dir="desc",
    )
    assert inventory["total"] == 1
    assert inventory["items"][0]["latest_volume"] == 123
    detail = cache.cached_security_detail("AAPL")
    assert detail["prices"][0]["adjusted_close"] == 10.25
    assert detail["metrics"][0]["data"]["market_cap"] == 100
    assert detail["earnings"][0]["surprise_pct"] == 11.11


def test_cached_security_inventory_merges_incremental_coverage(tmp_path: Path, monkeypatch):
    db = str(tmp_path / "incremental-coverage.db")
    for module in (securities, universes, cache):
        monkeypatch.setattr(module, "_DB_PATH", db)
    _seed(db)
    with get_session(db) as session:
        session.add_all([
            PriceCache(
                ticker="AAPL", date="2024-01-02", open=10, high=11, low=9,
                close=10.5, adjusted_close=10.25, volume=123, dividend=0,
                split_ratio=0, source="yahoo", price_mode="raw",
            ),
            PriceCache(
                ticker="AAPL", date="2024-01-03", open=10, high=11, low=9,
                close=10.5, adjusted_close=10.25, volume=123, dividend=0,
                split_ratio=0, source="yahoo", price_mode="raw",
            ),
            CacheCoverage(
                market="US", ticker="AAPL", data_kind="prices",
                requested_start="2024-01-02", requested_end="2024-01-02",
                actual_start="2024-01-02", actual_end="2024-01-02", row_count=1,
                expected_sessions=1, missing_sessions=0, status="complete",
                fetched_at="2024-01-03T00:00:00+00:00",
            ),
            CacheCoverage(
                market="US", ticker="AAPL", data_kind="prices",
                requested_start="2024-01-03", requested_end="2024-01-03",
                actual_start="2024-01-03", actual_end="2024-01-03", row_count=1,
                expected_sessions=1, missing_sessions=0, status="complete",
                fetched_at="2024-01-04T00:00:00+00:00",
            ),
        ])
        session.commit()

    inventory = cache.cached_securities_list(
        search="apple", status="complete", price_mode="raw", page=1, page_size=20,
        sort_by="symbol", sort_dir="asc",
    )

    coverage = inventory["items"][0]["coverage"]
    assert coverage["requested_start"] == "2024-01-02"
    assert coverage["requested_end"] == "2024-01-03"
    assert coverage["actual_start"] == "2024-01-02"
    assert coverage["actual_end"] == "2024-01-03"


def test_cached_security_inventory_does_not_merge_across_a_gap(tmp_path: Path, monkeypatch):
    db = str(tmp_path / "coverage-gap.db")
    for module in (securities, universes, cache):
        monkeypatch.setattr(module, "_DB_PATH", db)
    _seed(db)
    with get_session(db) as session:
        session.add_all([
            PriceCache(
                ticker="AAPL", date="2024-01-02", open=10, high=11, low=9,
                close=10.5, adjusted_close=10.25, volume=123, dividend=0,
                split_ratio=0, source="yahoo", price_mode="raw",
            ),
            PriceCache(
                ticker="AAPL", date="2024-01-04", open=10, high=11, low=9,
                close=10.5, adjusted_close=10.25, volume=123, dividend=0,
                split_ratio=0, source="yahoo", price_mode="raw",
            ),
            CacheCoverage(
                market="US", ticker="AAPL", data_kind="prices",
                requested_start="2024-01-02", requested_end="2024-01-02",
                actual_start="2024-01-02", actual_end="2024-01-02", row_count=1,
                expected_sessions=1, missing_sessions=0, status="complete",
                fetched_at="2024-01-03T00:00:00+00:00",
            ),
            CacheCoverage(
                market="US", ticker="AAPL", data_kind="prices",
                requested_start="2024-01-04", requested_end="2024-01-04",
                actual_start="2024-01-04", actual_end="2024-01-04", row_count=1,
                expected_sessions=1, missing_sessions=0, status="complete",
                fetched_at="2024-01-05T00:00:00+00:00",
            ),
        ])
        session.commit()

    inventory = cache.cached_securities_list(
        search="apple", status="complete", price_mode="raw", page=1, page_size=20,
        sort_by="symbol", sort_dir="asc",
    )
    all_rows = cache.cached_securities_list(
        search="apple", status=None, price_mode="raw", page=1, page_size=20,
        sort_by="symbol", sort_dir="asc",
    )

    assert inventory["total"] == 0
    assert all_rows["items"][0]["coverage"]["status"] == "partial"
    assert all_rows["items"][0]["coverage"]["missing_sessions"] == 1


def test_cached_security_inventory_counts_cached_dates_from_partial_coverage(tmp_path: Path, monkeypatch):
    db = str(tmp_path / "partial-coverage.db")
    for module in (securities, universes, cache):
        monkeypatch.setattr(module, "_DB_PATH", db)
    _seed(db)
    with get_session(db) as session:
        session.add_all([
            PriceCache(
                ticker="AAPL", date="2024-01-02", open=10, high=11, low=9,
                close=10.5, adjusted_close=10.25, volume=123, dividend=0,
                split_ratio=0, source="yahoo", price_mode="raw",
            ),
            PriceCache(
                ticker="AAPL", date="2024-01-04", open=10, high=11, low=9,
                close=10.5, adjusted_close=10.25, volume=123, dividend=0,
                split_ratio=0, source="yahoo", price_mode="raw",
            ),
            CacheCoverage(
                market="US", ticker="AAPL", data_kind="prices",
                requested_start="2024-01-02", requested_end="2024-01-04",
                actual_start="2024-01-02", actual_end="2024-01-04", row_count=2,
                expected_sessions=3, missing_sessions=1, status="partial",
                fetched_at="2024-01-05T00:00:00+00:00",
            ),
        ])
        session.commit()

    inventory = cache.cached_securities_list(
        search="apple", status="partial", price_mode="raw", page=1, page_size=20,
        sort_by="symbol", sort_dir="asc",
    )

    assert inventory["total"] == 1
    assert inventory["items"][0]["coverage"]["missing_sessions"] == 1
