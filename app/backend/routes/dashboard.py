"""Dashboard API — fund status, NAV history, trades, manual cycle, cache, simulation."""

from __future__ import annotations

import json
import os
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterator
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backend.database import get_db

from v2.persistence.database import get_session, init_db
from v2.persistence.repository import LedgerRepository

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
logger = logging.getLogger(__name__)

_DAEMON = None  # FundDaemon instance, set by the startup script
_DB_PATH = os.environ.get("FUND_DB_PATH", "fund.db")


class CacheFetchRequest(BaseModel):
    tickers: list[str] = Field(min_length=1, max_length=50)
    benchmark: str = "SPY"
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

    @field_validator("benchmark")
    @classmethod
    def valid_benchmark(cls, value):
        import re
        cleaned = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9.\-]{1,10}", cleaned):
            raise ValueError("invalid benchmark")
        return cleaned

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
    provider: str | None = Field(default=None, min_length=1, max_length=32)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    llm_connection_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def complete_llm_selection(self):
        if self.llm_connection_id is not None:
            if self.model is None:
                raise ValueError("model is required with llm_connection_id")
            if self.provider is not None:
                raise ValueError("provider cannot be combined with llm_connection_id")
        elif (self.provider is None) != (self.model is None):
            raise ValueError("provider and model must be supplied together")
        return self


class LlmProviderCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    vendor: str | None = None
    protocol: str | None = None
    provider_type: str | None = None
    base_url: str = Field(default="", max_length=500)
    api_key: SecretStr
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def strip_required(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError("value cannot be empty")
        return value

    @model_validator(mode="after")
    def complete_connection_kind(self):
        from v2.llm.registry import connection_kind_for_legacy

        if self.vendor is not None or self.protocol is not None:
            if not self.vendor or not self.protocol:
                raise ValueError("vendor and protocol must be supplied together")
        elif self.provider_type:
            self.vendor, self.protocol = connection_kind_for_legacy(self.provider_type)
        else:
            raise ValueError("vendor and protocol are required")
        return self


class LlmProviderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: SecretStr | None = None
    enabled: bool | None = None


class LlmModelCreateRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    enabled: bool = True

    @field_validator("model_id")
    @classmethod
    def strip_model_id(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError("model_id cannot be empty")
        return value


class LlmModelUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None


@dataclass(frozen=True)
class ResolvedSimulationLlm:
    client: object
    provider: str
    protocol: str | None
    model: str
    connection_id: int | None = None
    connection_name: str | None = None
    base_url: str | None = None
    session_id: str | None = None


def set_daemon(daemon) -> None:
    global _DAEMON
    _DAEMON = daemon


@contextmanager
def _get_repo() -> Iterator[LedgerRepository]:
    init_db(_DB_PATH)
    session = get_session(_DB_PATH)
    try:
        yield LedgerRepository(session)
    finally:
        session.close()


@router.get("/summary")
def get_summary():
    """Return fund-level summary: NAV, cash, equity, P&L, position count."""
    try:
        with _get_repo() as repo:
            return repo.get_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trades")
def get_trades(ticker: str = None, limit: int = 100, offset: int = 0):
    """Return recent trade log entries, optionally filtered by ticker."""
    try:
        with _get_repo() as repo:
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
        with _get_repo() as repo:
            return {"positions": repo.get_current_positions()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nav-history")
def get_nav_history(limit: int = 365):
    """Return NAV history for P&L charting."""
    try:
        with _get_repo() as repo:
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
    tickers, benchmark = data.tickers, data.benchmark
    start_date, end_date = data.start_date.isoformat(), data.end_date.isoformat()

    from v2.data.yfinance_client import YFinanceClient
    from v2.data.earnings import (
        earnings_surprise_percent,
        has_actionable_surprise,
    )
    from v2.persistence.models import EarningsCache, MetricsCache, PriceCache

    client = YFinanceClient()
    init_db(_DB_PATH)
    results = {}

    def fetch_prices(ticker, session):
        prices = client.get_prices(ticker, start_date, end_date)
        for price in prices:
            date_str = price.time[:10] if price.time and len(price.time) >= 10 else ""
            if not date_str:
                continue
            existing = session.query(PriceCache).filter(
                PriceCache.ticker == ticker, PriceCache.date == date_str
            ).first()
            if existing:
                existing.open = price.open
                existing.high = price.high
                existing.low = price.low
                existing.close = price.close
                existing.volume = price.volume
            else:
                session.add(PriceCache(
                    ticker=ticker, date=date_str,
                    open=price.open, high=price.high, low=price.low,
                    close=price.close, volume=price.volume,
                ))
        session.commit()
        return len(prices)

    try:
        for ticker in tickers:
            t = ticker.upper().strip()
            if not t:
                continue
            ticker_results = {"prices": 0, "metrics": 0, "earnings": 0, "error": None, "warnings": []}
            session = get_session(_DB_PATH)

            try:
                ticker_results["prices"] = fetch_prices(t, session)
                if not ticker_results["prices"]:
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
                    # TODO(event-driven-persona): yfinance quarterly statements expose
                    # report periods here, not authoritative public filing timestamps.
                    # Replace this +45-day estimate with source-aware SEC/filing dates
                    # before treating it as the exact availability date of new metrics.
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
                if not earnings:
                    ticker_results["warnings"].append(
                        "Yahoo returned no earnings history; PEAD will remain neutral"
                    )
                elif not has_actionable_surprise(earnings):
                    ticker_results["warnings"].append(
                        "Yahoo returned no complete actual/estimate EPS surprise; PEAD will remain neutral"
                    )
                for e in earnings:
                    q = e.quarterly
                    actual = q.earnings_per_share if q else None
                    estimated = q.estimated_earnings_per_share if q else None
                    surprise = earnings_surprise_percent(e)
                    existing = session.query(EarningsCache).filter_by(ticker=t, announcement_date=e.filing_date).first()
                    values = dict(
                        report_period=e.report_period,
                        actual_eps=actual,
                        estimated_eps=estimated,
                        surprise_pct=surprise,
                        source="yahoo",
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

        benchmark_result = None
        if benchmark not in tickers:
            session = get_session(_DB_PATH)
            try:
                try:
                    count = fetch_prices(benchmark, session)
                    benchmark_result = {
                        "ticker": benchmark,
                        "prices": count,
                        "error": None if count else "prices: Yahoo returned no data",
                    }
                except Exception as exc:
                    session.rollback()
                    benchmark_result = {
                        "ticker": benchmark, "prices": 0,
                        "error": f"prices: {exc}",
                    }
            finally:
                session.close()

        return {"results": results, "benchmark": benchmark_result}
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


@router.get("/llm/providers")
def llm_provider_connections(db: Session = Depends(get_db)):
    from app.backend.database.models import LlmProviderConnection
    from app.backend.services.llm_provider_service import connection_dict, ensure_provider_tables

    ensure_provider_tables(db)
    rows = db.query(LlmProviderConnection).order_by(LlmProviderConnection.name).all()
    return {"providers": [connection_dict(row) for row in rows]}


@router.post("/llm/providers", status_code=201)
def create_llm_provider(data: LlmProviderCreateRequest, db: Session = Depends(get_db)):
    from app.backend.database.models import LlmProviderConnection
    from app.backend.services.llm_provider_service import (
        connection_dict, ensure_provider_tables, normalize_connection_base_url,
    )
    from v2.llm.registry import legacy_provider_type

    ensure_provider_tables(db)
    vendor = (data.vendor or "").strip().lower()
    protocol = (data.protocol or "").strip()
    secret = data.api_key.get_secret_value().strip()
    if not secret:
        raise HTTPException(status_code=422, detail="api_key cannot be empty")
    try:
        base_url = normalize_connection_base_url(data.base_url, vendor, protocol)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if db.query(LlmProviderConnection).filter(LlmProviderConnection.name == data.name).first():
        raise HTTPException(status_code=409, detail="connection name already exists")
    row = LlmProviderConnection(
        name=data.name,
        vendor=vendor,
        protocol=protocol,
        provider_type=legacy_provider_type(vendor, protocol),
        base_url=base_url,
        api_key=secret,
        enabled=data.enabled,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="connection name already exists") from exc
    db.refresh(row)
    return connection_dict(row)


@router.patch("/llm/providers/{connection_id}")
def update_llm_provider(
    connection_id: int,
    data: LlmProviderUpdateRequest,
    db: Session = Depends(get_db),
):
    from app.backend.database.models import LlmProviderConnection, LlmProviderModel
    from app.backend.services.llm_provider_service import (
        connection_dict, connection_kind, get_connection,
        normalize_connection_base_url,
    )

    try:
        row = get_connection(db, connection_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    changes = data.model_dump(exclude_unset=True)
    endpoint_changed = False
    if "name" in changes:
        name = changes["name"].strip()
        if not name:
            raise HTTPException(status_code=422, detail="name cannot be empty")
        duplicate = db.query(LlmProviderConnection).filter(
            LlmProviderConnection.name == name,
            LlmProviderConnection.id != connection_id,
        ).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="connection name already exists")
        row.name = name
    if "base_url" in changes:
        try:
            vendor, protocol = connection_kind(row)
            normalized = normalize_connection_base_url(
                changes["base_url"] or "", vendor, protocol,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        endpoint_changed = endpoint_changed or normalized != row.base_url
        row.base_url = normalized
    if changes.get("api_key"):
        replacement = changes["api_key"].get_secret_value().strip()
        if replacement:
            endpoint_changed = endpoint_changed or replacement != row.api_key
            row.api_key = replacement
    if "enabled" in changes:
        row.enabled = changes["enabled"]
    if endpoint_changed:
        db.query(LlmProviderModel).filter(
            LlmProviderModel.connection_id == row.id,
            LlmProviderModel.source == "remote",
        ).update({"available": False}, synchronize_session=False)
        row.last_tested_at = None
        row.last_test_status = None
        row.last_error = None
        row.last_synced_at = None
    db.commit()
    db.refresh(row)
    return connection_dict(row)


@router.post("/llm/providers/{connection_id}/test")
async def test_llm_provider(connection_id: int, db: Session = Depends(get_db)):
    from app.backend.services.llm_provider_service import get_connection, test_connection

    try:
        row = get_connection(db, connection_id)
        models = await test_connection(db, row)
        return {"status": "success", "model_count": len(models)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("LLM connection test failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="unable to reach model endpoint") from exc


@router.post("/llm/providers/{connection_id}/models/sync")
async def sync_llm_provider_models(connection_id: int, db: Session = Depends(get_db)):
    from app.backend.services.llm_provider_service import get_connection, model_dict, sync_models

    try:
        row = get_connection(db, connection_id)
        models = await sync_models(db, row)
        return {"models": [model_dict(model) for model in models]}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("LLM model sync failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="unable to synchronize models") from exc


@router.get("/llm/providers/{connection_id}/models")
def list_llm_provider_models(connection_id: int, db: Session = Depends(get_db)):
    from app.backend.database.models import LlmProviderModel
    from app.backend.services.llm_provider_service import get_connection, model_dict

    try:
        row = get_connection(db, connection_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    models = db.query(LlmProviderModel).filter(
        LlmProviderModel.connection_id == row.id
    ).order_by(LlmProviderModel.display_name).all()
    return {"models": [model_dict(model) for model in models]}


@router.post("/llm/providers/{connection_id}/models", status_code=201)
def create_llm_provider_model(
    connection_id: int,
    data: LlmModelCreateRequest,
    db: Session = Depends(get_db),
):
    from app.backend.database.models import LlmProviderModel
    from app.backend.services.llm_provider_service import get_connection, model_dict

    try:
        row = get_connection(db, connection_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    exists = db.query(LlmProviderModel).filter(
        LlmProviderModel.connection_id == row.id,
        LlmProviderModel.model_id == data.model_id,
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail="model already exists for this connection")
    model = LlmProviderModel(
        connection_id=row.id,
        model_id=data.model_id,
        display_name=(data.display_name or data.model_id).strip(),
        source="manual",
        enabled=data.enabled,
        available=True,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return model_dict(model)


@router.patch("/llm/providers/{connection_id}/models/{model_id:path}")
def update_llm_provider_model(
    connection_id: int,
    model_id: str,
    data: LlmModelUpdateRequest,
    db: Session = Depends(get_db),
):
    from app.backend.database.models import LlmProviderModel
    from app.backend.services.llm_provider_service import get_connection, model_dict

    try:
        get_connection(db, connection_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    model = db.query(LlmProviderModel).filter(
        LlmProviderModel.connection_id == connection_id,
        LlmProviderModel.model_id == model_id,
    ).first()
    if model is None:
        raise HTTPException(status_code=404, detail="LLM model not found")
    changes = data.model_dump(exclude_unset=True)
    if "display_name" in changes and changes["display_name"] is not None:
        model.display_name = changes["display_name"].strip() or model.model_id
    if "enabled" in changes:
        model.enabled = changes["enabled"]
    db.commit()
    db.refresh(model)
    return model_dict(model)


@router.get("/llm/options")
def llm_options(db: Session = Depends(get_db)):
    from app.backend.database.models import LlmProviderConnection, LlmProviderModel
    from app.backend.services.llm_provider_service import ensure_provider_tables

    ensure_provider_tables(db)
    connections = db.query(LlmProviderConnection).filter(
        LlmProviderConnection.enabled.is_(True),
    ).order_by(LlmProviderConnection.name).all()
    options = []
    for connection in connections:
        if not connection.api_key:
            continue
        models = db.query(LlmProviderModel).filter(
            LlmProviderModel.connection_id == connection.id,
            LlmProviderModel.enabled.is_(True),
        ).order_by(LlmProviderModel.display_name).all()
        models = [model for model in models if model.source == "manual" or model.available]
        if models:
            options.append({
                "id": connection.id,
                "name": connection.name,
                "provider_type": connection.provider_type,
                "vendor": connection.vendor,
                "protocol": connection.protocol,
                "models": [
                    {"model_id": model.model_id, "display_name": model.display_name}
                    for model in models
                ],
            })
    return {"providers": options}


@router.get("/llm/models")
async def llm_models():
    """List v2-supported models and credential availability, never secrets."""
    from app.backend.database.connection import SessionLocal
    from app.backend.services.v2_llm_service import credential_configured
    from v2.llm import catalog

    session = SessionLocal()
    try:
        from app.backend.services.ollama_service import OllamaService
        ollama_models = await OllamaService().get_available_models()
        providers = []
        for provider in catalog():
            models = provider["models"]
            configured = credential_configured(provider["id"], session)
            if provider["id"] == "ollama":
                models = [
                    {"display_name": item["display_name"], "model": item["model_name"]}
                    for item in ollama_models
                ]
                configured = bool(models)
            providers.append({
                "id": provider["id"],
                "display_name": provider["display_name"],
                "credential_configured": configured,
                "models": models,
            })
        return {"providers": providers}
    finally:
        session.close()


def _fund_path() -> str:
    fund_path = os.environ.get("FUND_SPEC_PATH", "")
    if not fund_path and _DAEMON is not None:
        fund_path = str(_DAEMON._spec._path) if hasattr(_DAEMON._spec, "_path") else ""
    if not fund_path:
        from pathlib import Path
        fund_path = str(Path("v2/funds/example.yaml").resolve())
    return fund_path


def _resolve_simulation_llm(data: SimRunRequest, required: bool):
    """Resolve one immutable client for this request/run."""
    if data.llm_connection_id is not None:
        from app.backend.database.connection import SessionLocal
        from app.backend.services.llm_provider_service import resolve_connection
        from v2.llm import LlmProtocol, LlmRuntimeConfig, make_connection_llm
        from v2.llm.adapter_registry import get_vendor

        session = SessionLocal()
        try:
            snapshot = resolve_connection(session, data.llm_connection_id, data.model or "")
        finally:
            session.close()
        vendor = get_vendor(snapshot.vendor)
        session_id = vendor.new_session_id()
        client = make_connection_llm(LlmRuntimeConfig(
            vendor=snapshot.vendor,
            protocol=LlmProtocol(snapshot.protocol),
            model=data.model or "",
            base_url=snapshot.base_url,
            api_key=snapshot.api_key,
            session_id=session_id,
        ))
        return ResolvedSimulationLlm(
            client=client,
            provider=snapshot.vendor,
            protocol=snapshot.protocol,
            model=data.model or "",
            connection_id=snapshot.id,
            connection_name=snapshot.name,
            base_url=snapshot.base_url,
            session_id=session_id,
        )

    if data.provider is None:
        if not required:
            return None
        from v2.llm import get_llm
        client = get_llm()  # compatibility for older API callers and CLI-style setup
        return ResolvedSimulationLlm(
            client=client,
            provider=getattr(client, "provider", type(client).__name__),
            protocol=getattr(client, "protocol", None),
            model=client.model,
        )

    from app.backend.database.connection import SessionLocal
    from app.backend.services.v2_llm_service import resolve_credential
    from v2.llm import make_llm, validate_selection

    provider, model = validate_selection(data.provider, data.model or "")
    session = SessionLocal()
    try:
        credential = resolve_credential(provider, session)
    finally:
        session.close()
    client = make_llm(provider, model, credential=credential)
    return ResolvedSimulationLlm(
        client=client,
        provider=provider,
        protocol=getattr(client, "protocol", None),
        model=model,
    )


def _simulation_preflight(data: SimRunRequest, resolved_llm=None) -> dict:
    from v2.fund import load_spec
    from v2.simulation.runner import (
        _trading_days,
        disable_unavailable_models,
        estimate_persona_event_schedule,
        validate_cached_data,
    )

    tickers = data.tickers
    start_date, end_date = data.start_date.isoformat(), data.end_date.isoformat()
    benchmark = data.benchmark
    spec = load_spec(_fund_path())
    require_earnings = any(model.name == "pead" for strategy in spec.strategies for model in strategy.models)
    errors, warnings = validate_cached_data(
        _DB_PATH, tickers, benchmark, start_date, end_date, require_earnings,
    )
    if errors:
        raise HTTPException(status_code=422, detail={
            "message": "simulation data preflight failed", "errors": errors,
        })
    warnings.extend(disable_unavailable_models(spec, _DB_PATH, tickers, end_date))
    from v2.signals import ALPHA_MODEL_REGISTRY, LLMAgent
    persona_names = {
        model.name
        for strategy in spec.strategies
        for model in strategy.models
        if issubclass(ALPHA_MODEL_REGISTRY[model.name], LLMAgent)
    }
    provider = "none"
    model_name = "none"
    estimate = 0
    event_estimate = {
        "estimated_refresh_events": 0,
        "persona_count": len(persona_names),
        "event_reason_counts": {
            reason: 0 for reason in (
                "bootstrap", "new_filing", "actionable_earnings",
                "valuation_change", "max_age", "universe_entry",
            )
        },
    }
    trading_days = _trading_days(_DB_PATH, benchmark, start_date, end_date)
    llm = resolved_llm if resolved_llm is not None else _resolve_simulation_llm(
        data, required=bool(persona_names)
    )
    if llm is not None:
        provider = getattr(llm, "provider", type(llm).__name__)
        model_name = llm.model
    if persona_names:
        event_estimate = estimate_persona_event_schedule(
            _DB_PATH, tickers, trading_days, persona_names, spec.persona_refresh,
        )
        estimate = event_estimate["estimated_llm_calls"]
    result = {
        "estimated_llm_calls": estimate,
        "estimate_kind": "event_schedule_upper_bound",
        **event_estimate,
        "persona_refresh_policy": spec.persona_refresh.model_dump(),
        "provider": provider,
        "model": model_name,
        "benchmark": benchmark,
        "trading_days": len(trading_days),
        "enabled_models": [model.name for strategy in spec.strategies for model in strategy.models],
        "warnings": warnings,
    }
    logger.info(
        "simulation preflight: tickers=%s benchmark=%s range=%s..%s calls=%d provider=%s model=%s warnings=%s",
        tickers, benchmark, start_date, end_date, estimate, provider, model_name, warnings,
    )
    return result


@router.post("/sim/preflight")
def sim_preflight(data: SimRunRequest):
    """Always return the model-call estimate before starting a simulation."""
    try:
        return _simulation_preflight(data)
    except HTTPException:
        raise
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
        resolved = (
            _resolve_simulation_llm(data, required=True)
            if data.llm_connection_id is not None or data.provider is not None
            else None
        )
        preflight = _simulation_preflight(data, resolved_llm=resolved)
        if not data.confirm_cost:
            raise HTTPException(status_code=409, detail={
                "message": "LLM call confirmation required",
                **preflight,
            })
        from v2.simulation.runner import SimRunner
        if resolved is None:
            resolved = _resolve_simulation_llm(data, required=preflight["provider"] != "none")
        llm = getattr(resolved, "client", resolved)
        sim_id = SimRunner.create(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            initial_capital=capital,
            benchmark=data.benchmark,
            db_path=_DB_PATH,
            fund_spec_path=_fund_path(),
            name=name,
            llm=llm,
            llm_provider=preflight["provider"],
            llm_protocol=getattr(resolved, "protocol", None),
            llm_model=preflight["model"],
            llm_connection_id=getattr(resolved, "connection_id", None),
            llm_connection_name=getattr(resolved, "connection_name", None),
            llm_base_url=getattr(resolved, "base_url", None),
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


@router.get("/sim/{sim_id}/cycles")
def sim_cycles(
    sim_id: int,
    date: str | None = None,
    signal_date: str | None = None,
    execution_date: str | None = None,
    ticker: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """List indexed decision-cycle audit summaries for one simulation."""
    if not 1 <= limit <= 500 or offset < 0:
        raise HTTPException(status_code=422, detail="invalid audit pagination")
    try:
        from v2.simulation.audit import list_cycle_audits

        result = list_cycle_audits(
            sim_id,
            _DB_PATH,
            date=date,
            signal_date=signal_date,
            execution_date=execution_date,
            ticker=ticker,
            limit=limit,
            offset=offset,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="sim not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("cycle audit list failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sim/{sim_id}/cycles/{cycle_id}")
def sim_cycle_detail(sim_id: int, cycle_id: int):
    """Return one full serialized cycle after run ownership validation."""
    try:
        from v2.simulation.audit import get_cycle_audit

        result = get_cycle_audit(sim_id, cycle_id, _DB_PATH)
        if result is None:
            raise HTTPException(status_code=404, detail="cycle not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("cycle audit detail failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sim/runs")
def sim_runs():
    """List all simulation runs."""
    try:
        from v2.simulation.runner import list_sim_runs
        return {"runs": list_sim_runs(_DB_PATH)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
