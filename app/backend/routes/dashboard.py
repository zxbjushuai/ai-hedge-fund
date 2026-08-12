"""Dashboard API — fund status, NAV history, trades, manual cycle, cache, simulation."""

from __future__ import annotations

import json
import os
import logging
from datetime import date, timedelta
from pydantic import BaseModel, Field, field_validator, model_validator

from fastapi import APIRouter, HTTPException

from v2.persistence.database import get_session, init_db
from v2.persistence.repository import LedgerRepository

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
logger = logging.getLogger(__name__)

_DAEMON = None  # FundDaemon instance, set by the startup script
_DB_PATH = os.environ.get("FUND_DB_PATH", "fund.db")


class CacheFetchRequest(BaseModel):
    tickers: list[str] = Field(min_length=1, max_length=50)
    start_date: date
    end_date: date

    @field_validator("tickers")
    @classmethod
    def valid_tickers(cls, values):
        import re
        cleaned = [v.strip().upper() for v in values]
        if any(not re.fullmatch(r"[A-Z0-9.\-]{1,10}", v) for v in cleaned):
            raise ValueError("invalid ticker")
        return list(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def valid_range(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        if (self.end_date - self.start_date).days > 3650:
            raise ValueError("date range cannot exceed 10 years")
        return self


class SimRunRequest(CacheFetchRequest):
    initial_capital: float = Field(gt=0)
    name: str = Field(default="", max_length=100)
    confirm_cost: bool = False


def set_daemon(daemon) -> None:
    global _DAEMON
    _DAEMON = daemon


def _get_repo() -> LedgerRepository:
    init_db(_DB_PATH)
    session = get_session(_DB_PATH)
    return LedgerRepository(session)


@router.get("/summary")
def get_summary():
    """Return fund-level summary: NAV, cash, equity, P&L, position count."""
    try:
        repo = _get_repo()
        return repo.get_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trades")
def get_trades(ticker: str = None, limit: int = 100, offset: int = 0):
    """Return recent trade log entries, optionally filtered by ticker."""
    try:
        repo = _get_repo()
        trades = repo.get_trades(ticker=ticker, limit=limit, offset=offset)
        return {
            "trades": [
                {
                    "id": t.id,
                    "ticker": t.ticker,
                    "side": t.side,
                    "quantity": t.quantity,
                    "price": t.price,
                    "fee": t.fee,
                    "total_amount": t.total_amount,
                    "cycle_date": t.cycle_date,
                    "created_at": t.created_at,
                }
                for t in trades
            ],
            "total": len(trades),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/positions")
def get_positions():
    """Return current portfolio positions derived from trade_log."""
    try:
        repo = _get_repo()
        return {"positions": repo.get_current_positions()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nav-history")
def get_nav_history(limit: int = 365):
    """Return NAV history for P&L charting."""
    try:
        repo = _get_repo()
        snapshots = repo.get_nav_history(limit=limit)
        return {
            "history": [
                {
                    "date": s.cycle_date,
                    "nav": s.nav,
                    "cash": s.cash,
                    "equity": s.equity,
                }
                for s in reversed(snapshots)
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run-cycle")
def trigger_cycle():
    """Manually trigger one fund cycle."""
    if _DAEMON is None:
        raise HTTPException(status_code=400, detail="daemon not initialized")
    try:
        result = _DAEMON.run_now()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
def get_status():
    """Return daemon status and fund configuration."""
    if _DAEMON is None:
        return {"running": False, "message": "daemon not initialized"}
    spec = _DAEMON.spec
    return {
        "running": _DAEMON.is_running,
        "fund": spec.name,
        "universe": spec.universe,
        "capital": spec.capital,
        "db_path": _DAEMON.db_path,
    }


# ---------------------------------------------------------------------------
# Data cache endpoints
# ---------------------------------------------------------------------------


@router.post("/cache/fetch")
def cache_fetch(data: CacheFetchRequest):
    """Fetch and cache historical prices + financial metrics from yfinance.

    Body: {"tickers": ["AAPL"], "start_date": "2024-01-01", "end_date": "2024-12-31"}
    """
    tickers, start_date, end_date = data.tickers, data.start_date.isoformat(), data.end_date.isoformat()

    from v2.data.yfinance_client import YFinanceClient
    from v2.persistence.models import EarningsCache, MetricsCache, PriceCache

    client = YFinanceClient()
    init_db(_DB_PATH)
    results = {}

    try:
        for ticker in tickers:
            t = ticker.upper().strip()
            if not t:
                continue
            ticker_results = {"prices": 0, "metrics": 0, "earnings": 0, "error": None, "warnings": []}
            session = get_session(_DB_PATH)

            try:
                prices = client.get_prices(t, start_date, end_date)
                for p in prices:
                    date_str = p.time[:10] if p.time and len(p.time) >= 10 else ""
                    if not date_str:
                        continue
                    existing = session.query(PriceCache).filter(
                        PriceCache.ticker == t, PriceCache.date == date_str
                    ).first()
                    if existing:
                        existing.open = p.open
                        existing.high = p.high
                        existing.low = p.low
                        existing.close = p.close
                        existing.volume = p.volume
                    else:
                        session.add(PriceCache(
                            ticker=t, date=date_str,
                            open=p.open, high=p.high, low=p.low, close=p.close,
                            volume=p.volume,
                        ))
                session.commit()
                ticker_results["prices"] = len(prices)
                if not prices:
                    ticker_results["error"] = "prices: Yahoo returned no data"
            except Exception as e:
                session.rollback()
                ticker_results["error"] = f"prices: {e}"

            try:
                metrics = client.get_financial_metrics(t, end_date, limit=40)
                for m in metrics:
                    existing = session.query(MetricsCache).filter(
                        MetricsCache.ticker == t, MetricsCache.report_period == m.report_period
                    ).first()
                    # Current valuation fields from stock.info are not historical.
                    # Never persist them as if they were known in a past quarter.
                    m_json = m.model_dump_json(exclude={
                        "ticker", "market_cap", "enterprise_value",
                        "price_to_earnings_ratio", "price_to_book_ratio",
                        "price_to_sales_ratio", "enterprise_value_to_ebitda_ratio",
                        "enterprise_value_to_revenue_ratio", "peg_ratio",
                    })
                    if existing:
                        existing.data = m_json
                        existing.filing_date = (date.fromisoformat(m.report_period) + timedelta(days=45)).isoformat()
                        existing.filing_date_source = "estimated_45d"
                    else:
                        session.add(MetricsCache(
                            ticker=t,
                            report_period=m.report_period,
                            filing_date=(date.fromisoformat(m.report_period) + timedelta(days=45)).isoformat(),
                            filing_date_source="estimated_45d",
                            data=m_json,
                        ))
                session.commit()
                ticker_results["metrics"] = len(metrics)
            except Exception as e:
                session.rollback()
                if ticker_results["error"]:
                    ticker_results["error"] += f"; metrics: {e}"
                else:
                    ticker_results["error"] = f"metrics: {e}"

            try:
                earnings = client.get_earnings_history(t, limit=40)
                for e in earnings:
                    q = e.quarterly
                    actual = q.earnings_per_share if q else None
                    surprise_label = q.eps_surprise if q else None
                    estimated = q.estimated_earnings_per_share if q else None
                    if actual is not None and estimated not in (None, 0):
                        surprise = ((actual - estimated) / abs(estimated)) * 100
                    else:
                        surprise = 1.0 if surprise_label == "BEAT" else -1.0 if surprise_label == "MISS" else None
                    existing = session.query(EarningsCache).filter_by(ticker=t, announcement_date=e.filing_date).first()
                    values = dict(
                        report_period=e.report_period,
                        actual_eps=actual,
                        estimated_eps=estimated,
                        surprise_pct=surprise,
                    )
                    if existing:
                        for key, value in values.items(): setattr(existing, key, value)
                    elif e.filing_date:
                        session.add(EarningsCache(ticker=t, announcement_date=e.filing_date, **values))
                ticker_results["earnings"] = len(earnings)
                session.commit()
            except Exception as e:
                session.rollback()
                ticker_results["error"] = (ticker_results["error"] + "; " if ticker_results["error"] else "") + f"earnings: {e}"
            finally:
                session.close()

            results[t] = ticker_results

        return {"results": results}
    finally:
        client.close()


@router.get("/cache/list")
def cache_list():
    """List all cached tickers with data ranges."""
    from sqlalchemy import func
    from v2.persistence.models import EarningsCache, MetricsCache, PriceCache

    init_db(_DB_PATH)
    session = get_session(_DB_PATH)
    try:
        price_rows = (
            session.query(
                PriceCache.ticker,
                func.min(PriceCache.date).label("min_date"),
                func.max(PriceCache.date).label("max_date"),
                func.count().label("cnt"),
            )
            .group_by(PriceCache.ticker)
            .all()
        )

        metrics_rows = (
            session.query(
                MetricsCache.ticker,
                func.min(MetricsCache.report_period).label("min_period"),
                func.max(MetricsCache.report_period).label("max_period"),
                func.count().label("cnt"),
            )
            .group_by(MetricsCache.ticker)
            .all()
        )
        earnings_rows = session.query(EarningsCache.ticker, func.min(EarningsCache.announcement_date), func.max(EarningsCache.announcement_date), func.count()).group_by(EarningsCache.ticker).all()

        price_map = {r.ticker: {"min": r.min_date, "max": r.max_date, "count": r.cnt} for r in price_rows}
        metrics_map = {r.ticker: {"min": r.min_period, "max": r.max_period, "count": r.cnt} for r in metrics_rows}
        earnings_map = {r[0]: {"min": r[1], "max": r[2], "count": r[3]} for r in earnings_rows}

        all_tickers = set(price_map) | set(metrics_map) | set(earnings_map)
        result = {}
        for t in sorted(all_tickers):
            result[t] = {
                "prices": price_map.get(t),
                "metrics": metrics_map.get(t),
                "earnings": earnings_map.get(t),
                "filing_date_note": "quarterly metrics use estimated report_period + 45 days",
            }
        return {"cached": result}
    finally:
        session.close()


@router.delete("/cache/{ticker}")
def cache_delete(ticker: str):
    """Delete all cached data for a ticker."""
    from v2.persistence.models import EarningsCache, MetricsCache, PriceCache

    t = ticker.upper().strip()
    init_db(_DB_PATH)
    session = get_session(_DB_PATH)
    try:
        pc = session.query(PriceCache).filter(PriceCache.ticker == t).delete()
        mc = session.query(MetricsCache).filter(MetricsCache.ticker == t).delete()
        ec = session.query(EarningsCache).filter(EarningsCache.ticker == t).delete()
        session.commit()
        return {
            "ticker": t,
            "deleted_prices": pc,
            "deleted_metrics": mc,
            "deleted_earnings": ec,
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Simulation endpoints
# ---------------------------------------------------------------------------


def _fund_path() -> str:
    fund_path = os.environ.get("FUND_SPEC_PATH", "")
    if not fund_path and _DAEMON is not None:
        fund_path = str(_DAEMON._spec._path) if hasattr(_DAEMON._spec, "_path") else ""
    if not fund_path:
        from pathlib import Path
        fund_path = str(Path("v2/funds/example.yaml").resolve())
    return fund_path


def _simulation_preflight(data: SimRunRequest) -> dict:
    from v2.fund import load_spec
    from v2.simulation.runner import (
        _trading_days,
        disable_unavailable_models,
        validate_cached_data,
    )

    tickers = data.tickers
    start_date, end_date = data.start_date.isoformat(), data.end_date.isoformat()
    spec = load_spec(_fund_path())
    spec.universe = tickers
    require_earnings = any(model.name == "pead" for strategy in spec.strategies for model in strategy.models)
    errors, warnings = validate_cached_data(_DB_PATH, tickers, start_date, end_date, require_earnings)
    if errors:
        raise HTTPException(status_code=422, detail={
            "message": "simulation data preflight failed", "errors": errors,
        })
    warnings.extend(disable_unavailable_models(spec, _DB_PATH, tickers, end_date))
    from v2.signals import ALPHA_MODEL_REGISTRY, LLMAgent
    llm_models = sum(
        1
        for strategy in spec.strategies
        for model in strategy.models
        if issubclass(ALPHA_MODEL_REGISTRY[model.name], LLMAgent)
    )
    provider = "none"
    model_name = "none"
    estimate = 0
    trading_days = _trading_days(_DB_PATH, tickers, start_date, end_date)
    if llm_models:
        from v2.llm import get_llm
        llm = get_llm()
        provider, model_name = type(llm).__name__, llm.model
        # The first trading day seeds NAV. Every subsequent day forms signals
        # from the preceding close for every ticker. Historical valuation
        # fields normally change with that close, so each is a distinct cold
        # prompt even between financial filings.
        estimate = max(len(trading_days) - 1, 0) * len(tickers) * llm_models
    result = {
        "estimated_llm_calls": estimate,
        "estimate_kind": "cold_cache_upper_bound",
        "provider": provider,
        "model": model_name,
        "trading_days": len(trading_days),
        "enabled_models": [model.name for strategy in spec.strategies for model in strategy.models],
        "warnings": warnings,
    }
    logger.info(
        "simulation preflight: tickers=%s range=%s..%s calls=%d provider=%s model=%s warnings=%s",
        tickers, start_date, end_date, estimate, provider, model_name, warnings,
    )
    return result


@router.post("/sim/preflight")
def sim_preflight(data: SimRunRequest):
    """Always return the model-call estimate before starting a simulation."""
    return _simulation_preflight(data)


@router.post("/sim/run")
def sim_run(data: SimRunRequest):
    """Start a backtest simulation using cached data.

    Body: {
        "tickers": ["AAPL"],
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "initial_capital": 100000,
        "name": ""
    }
    """
    tickers, start_date, end_date = data.tickers, data.start_date.isoformat(), data.end_date.isoformat()
    capital, name = data.initial_capital, data.name

    try:
        preflight = _simulation_preflight(data)
        if not data.confirm_cost:
            raise HTTPException(status_code=409, detail={
                "message": "LLM call confirmation required",
                **preflight,
            })
        from v2.simulation.runner import SimRunner
        sim_id = SimRunner.create(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            initial_capital=capital,
            db_path=_DB_PATH,
            fund_spec_path=_fund_path(),
            name=name,
        )
        runner = SimRunner._get(sim_id)
        if runner is None:
            raise HTTPException(status_code=500, detail="failed to create runner")
        runner.start()
        return {"sim_id": sim_id, "status": "started"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("sim run failed")
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/sim/status/{sim_id}")
def sim_status(sim_id: int):
    """Get simulation progress."""
    try:
        from v2.simulation.runner import get_sim_status
        result = get_sim_status(sim_id, _DB_PATH)
        if result is None:
            raise HTTPException(status_code=404, detail="sim not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sim/result/{sim_id}")
def sim_result(sim_id: int):
    """Get full simulation results."""
    try:
        from v2.simulation.runner import get_sim_result
        result = get_sim_result(sim_id, _DB_PATH)
        if result is None:
            raise HTTPException(status_code=404, detail="sim not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sim/runs")
def sim_runs():
    """List all simulation runs."""
    try:
        from v2.simulation.runner import list_sim_runs
        return {"runs": list_sim_runs(_DB_PATH)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
