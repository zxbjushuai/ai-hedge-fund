"""Deterministic end-to-end coverage for catalog to simulation result."""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

from hedge_fund.data.cache_service import sync_us_catalog
from hedge_fund.data.market import CatalogSecurity, USMarketDataAdapter
from hedge_fund.data.models import Price
from hedge_fund.persistence.database import get_session
from hedge_fund.persistence.models import CacheCoverage, PriceCache
from research_app.backend.routes import cache, schemas, securities, simulations

DAYS = {
    "2024-01-10": {"AAA": 10.0, "SPY": 100.0},
    "2024-01-11": {"AAA": 11.0, "SPY": 101.0},
    "2024-01-12": {"AAA": 12.0, "SPY": 102.0},
    "2024-01-16": {"AAA": 13.0, "SPY": 103.0},
}


def _bar(day: str, price: float) -> Price:
    return Price(
        open=price,
        high=price,
        low=price,
        close=price,
        adjusted_close=price,
        volume=10_000,
        time=day,
        source="test",
        price_mode="raw",
    )


def _write_spec(path: Path) -> None:
    path.write_text(
        """
name: deterministic-daily-path
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


def _wait_for_job(job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        job = cache.cache_job_detail(job_id)
        if job["status"] not in {"pending", "running", "cancelling"}:
            return job
        if time.monotonic() >= deadline:
            raise AssertionError(f"cache job did not finish: {job}")
        time.sleep(0.01)


def _wait_for_simulation(sim_id: int, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        status = simulations.sim_status(sim_id)
        if status["status"] in {"completed", "failed"}:
            return status
        if time.monotonic() >= deadline:
            raise AssertionError(f"simulation did not finish: {status}")
        time.sleep(0.01)


def test_catalog_cache_preflight_run_and_result(tmp_path: Path, monkeypatch):
    db = tmp_path / "daily-path.db"
    spec_path = tmp_path / "fund.yaml"
    _write_spec(spec_path)

    class CatalogAdapter:
        def sync_catalog(self):
            return [
                CatalogSecurity("US", "AAA", "AAA", "AAA Inc", "NASDAQ", "equity"),
                CatalogSecurity("US", "SPY", "SPY", "SPDR S&P 500 ETF", "NYSE Arca", "etf"),
            ]

    sync_us_catalog(str(db), CatalogAdapter())  # type: ignore[arg-type]
    for module in (securities, cache, simulations):
        monkeypatch.setattr(module, "_DB_PATH", str(db))
    monkeypatch.setattr(simulations, "_fund_path", lambda: str(spec_path))

    def fake_batch(self, tickers, start_date, end_date):
        assert start_date == "2024-01-10"
        assert end_date == "2024-01-16"
        assert set(tickers) <= set(DAYS[start_date])
        return {ticker: [_bar(day, prices[ticker]) for day, prices in DAYS.items()] for ticker in tickers}

    def reject_individual_fetch(*args, **kwargs):
        raise AssertionError("cache job should not need an individual price fallback")

    monkeypatch.setattr(USMarketDataAdapter, "get_prices_batch", fake_batch)
    monkeypatch.setattr(USMarketDataAdapter, "get_prices", reject_individual_fetch)

    catalog = securities.securities_list(
        search="",
        exchange=None,
        asset_type=None,
        active=True,
        selectable=True,
        page=1,
        page_size=50,
        sort_by="symbol",
        sort_dir="asc",
    )
    selected_id = next(item["id"] for item in catalog["items"] if item["symbol"] == "AAA")

    job = cache.cache_job_create(
        schemas.CacheJobCreateRequest(
            selection=schemas.CacheSelectionRequest(security_ids=[selected_id]),
            benchmark="SPY",
            start_date=date(2024, 1, 10),
            end_date=date(2024, 1, 16),
            data_types=["prices"],
        )
    )
    job = _wait_for_job(job["id"])
    assert job["status"] == "completed", job
    assert job["items"]["AAA"]["prices"]["status"] == "complete"
    assert job["items"]["SPY"]["prices"]["status"] == "complete"

    with get_session(str(db)) as session:
        assert session.query(PriceCache).filter(PriceCache.ticker.in_(["AAA", "SPY"])).count() == 8
        coverage = session.query(CacheCoverage).filter_by(data_kind="prices", status="complete").all()
    assert {row.ticker for row in coverage} == {"AAA", "SPY"}
    assert all(row.missing_sessions == 0 for row in coverage)

    request = schemas.SimRunRequest(
        tickers=["AAA"],
        benchmark="SPY",
        start_date=date(2024, 1, 10),
        end_date=date(2024, 1, 16),
        initial_capital=1000.0,
        name="daily-path",
        confirm_cost=True,
    )
    preflight = simulations.sim_preflight(request)
    assert preflight["provider"] == "none"
    assert preflight["estimated_llm_calls"] == 0
    assert preflight["trading_days"] == 4
    assert preflight["enabled_models"] == ["price_momentum"]

    started = simulations.sim_run(request)
    status = _wait_for_simulation(started["sim_id"])
    assert status["status"] == "completed", status
    assert status["current_day"] == 4
    assert status["model"] == "none"

    result = simulations.sim_result(started["sim_id"])
    assert result["status"] == "completed"
    assert result["valuation_date"] == "2024-01-16"
    assert len(result["nav_curve"]) == 4
    assert result["nav_curve"][-1]["benchmark_nav"] == 1030.0
    assert result["benchmark_return_pct"] == 3.0
    assert result["trade_count"] >= 1
    assert {trade["ticker"] for trade in result["trades"]} == {"AAA"}
    assert result["trades"][0]["price"] == 13.0
    assert result["audit_available"] is True
