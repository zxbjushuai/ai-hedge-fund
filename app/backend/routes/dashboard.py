"""Dashboard API — fund status, NAV history, trades, manual cycle, cache, simulation."""

from __future__ import annotations

import json
import os
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterator
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from fastapi import APIRouter, Depends, HTTPException, Query
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


class SecurityFilterRequest(BaseModel):
    search: str = Field(default="", max_length=100)
    exchange: str | None = Field(default=None, max_length=32)
    asset_type: str | None = Field(default=None, pattern=r"^(equity|etf|other)$")
    active: bool = True
    selectable: bool = True


class CacheSelectionRequest(BaseModel):
    security_ids: list[int] | None = Field(default=None, max_length=20000)
    universe_id: int | None = Field(default=None, gt=0)
    filter: SecurityFilterRequest | None = None
    tickers: list[str] | None = Field(default=None, max_length=20000)

    @field_validator("tickers")
    @classmethod
    def normalize_selection_tickers(cls, values: list[str] | None):
        return None if values is None else CacheFetchRequest.valid_tickers(values)

    @model_validator(mode="after")
    def exactly_one_selection(self):
        if sum(value is not None for value in (self.security_ids, self.universe_id, self.filter, self.tickers)) != 1:
            raise ValueError("select exactly one of security_ids, universe_id, filter, or tickers")
        if self.security_ids is not None and not self.security_ids:
            raise ValueError("security_ids cannot be empty")
        if self.tickers is not None and not self.tickers:
            raise ValueError("tickers cannot be empty")
        return self


class CacheJobCreateRequest(BaseModel):
    selection: CacheSelectionRequest
    benchmark: str = "SPY"
    start_date: date
    end_date: date
    data_types: list[str] = Field(default_factory=lambda: ["prices"])
    force: bool = False

    @field_validator("benchmark")
    @classmethod
    def normalize_job_benchmark(cls, value: str):
        return CacheFetchRequest.valid_benchmark(value)

    @field_validator("data_types")
    @classmethod
    def valid_data_types(cls, values: list[str]):
        values = list(dict.fromkeys(values))
        if not values or any(value not in {"prices", "metrics", "earnings"} for value in values):
            raise ValueError("data_types must contain prices, metrics, or earnings")
        return values

    @model_validator(mode="after")
    def valid_job_range(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        if (self.end_date - self.start_date).days > 3650:
            raise ValueError("date range cannot exceed 10 years")
        return self


class UniverseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    security_ids: list[int] = Field(min_length=1, max_length=20000)

    @field_validator("name")
    @classmethod
    def normalize_universe_name(cls, value: str):
        return value.strip()


class UniverseUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    security_ids: list[int] | None = Field(default=None, min_length=1, max_length=20000)
    archived: bool | None = None


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


def _security_query(session, filters: SecurityFilterRequest):
    from sqlalchemy import or_
    from v2.persistence.models import Security

    query = session.query(Security).filter(Security.market == "US")
    if filters.active:
        query = query.filter(Security.active.is_(True))
    if filters.selectable:
        query = query.filter(Security.selectable.is_(True), Security.is_test.is_(False))
    if filters.exchange:
        query = query.filter(Security.exchange == filters.exchange)
    if filters.asset_type:
        query = query.filter(Security.asset_type == filters.asset_type)
    if filters.search.strip():
        pattern = f"%{filters.search.strip()}%"
        query = query.filter(or_(Security.symbol.ilike(pattern), Security.name.ilike(pattern)))
    return query


def _security_dict(row) -> dict:
    return {
        "id": row.id, "market": row.market, "symbol": row.symbol,
        "data_symbol": row.data_symbol, "name": row.name, "exchange": row.exchange,
        "asset_type": row.asset_type, "currency": row.currency, "active": row.active,
        "selectable": row.selectable, "catalog_source": row.catalog_source,
        "synced_at": row.synced_at,
    }


def _security_order(sort_by: str, sort_dir: str):
    from v2.persistence.models import Security

    columns = {
        "symbol": Security.symbol,
        "name": Security.name,
        "exchange": Security.exchange,
        "asset_type": Security.asset_type,
    }
    column = columns[sort_by]
    return column.desc() if sort_dir == "desc" else column.asc()


@router.post("/securities/sync")
def securities_sync():
    from v2.data.cache_service import sync_us_catalog
    try:
        return sync_us_catalog(_DB_PATH)
    except Exception as exc:
        logger.exception("US security catalog synchronization failed")
        raise HTTPException(status_code=502, detail=f"catalog synchronization failed: {type(exc).__name__}") from exc


@router.get("/securities")
def securities_list(
    search: str = Query(default="", max_length=100),
    exchange: str | None = Query(default=None, max_length=32),
    asset_type: str | None = Query(default=None, pattern=r"^(equity|etf|other)$"),
    active: bool = True,
    selectable: bool = True,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    sort_by: str = Query(default="symbol", pattern=r"^(symbol|name|exchange|asset_type)$"),
    sort_dir: str = Query(default="asc", pattern=r"^(asc|desc)$"),
):
    from sqlalchemy import distinct
    from v2.persistence.models import Security

    init_db(_DB_PATH)
    filters = SecurityFilterRequest(search=search, exchange=exchange, asset_type=asset_type, active=active, selectable=selectable)
    with get_session(_DB_PATH) as session:
        query = _security_query(session, filters)
        total = query.count()
        rows = query.order_by(_security_order(sort_by, sort_dir), Security.symbol).offset((page - 1) * page_size).limit(page_size).all()
        exchanges = [row[0] for row in session.query(distinct(Security.exchange)).filter(Security.market == "US", Security.active.is_(True)).order_by(Security.exchange).all() if row[0]]
        return {"items": [_security_dict(row) for row in rows], "total": total, "page": page, "page_size": page_size, "exchanges": exchanges}


@router.get("/securities/selection")
def securities_selection(
    search: str = Query(default="", max_length=100),
    exchange: str | None = Query(default=None, max_length=32),
    asset_type: str | None = Query(default=None, pattern=r"^(equity|etf|other)$"),
    sort_by: str = Query(default="symbol", pattern=r"^(symbol|name|exchange|asset_type)$"),
    sort_dir: str = Query(default="asc", pattern=r"^(asc|desc)$"),
):
    """Return the complete filtered selection as typed IDs, not a filter token."""
    from v2.persistence.models import Security

    init_db(_DB_PATH)
    filters = SecurityFilterRequest(search=search, exchange=exchange, asset_type=asset_type)
    with get_session(_DB_PATH) as session:
        rows = _security_query(session, filters).order_by(
            _security_order(sort_by, sort_dir), Security.symbol,
        ).all()
        return {
            "items": [
                {
                    "id": row.id,
                    "symbol": row.symbol,
                    "name": row.name,
                    "exchange": row.exchange,
                    "asset_type": row.asset_type,
                }
                for row in rows
            ],
            "total": len(rows),
        }


@router.get("/securities/{security_id}")
def security_detail(security_id: int):
    from v2.persistence.models import Security
    init_db(_DB_PATH)
    with get_session(_DB_PATH) as session:
        row = session.get(Security, security_id)
        if row is None:
            raise HTTPException(status_code=404, detail="security not found")
        return _security_dict(row)


def _universe_dict(session, universe) -> dict:
    from v2.persistence.models import SavedUniverseMember, Security
    rows = session.query(SavedUniverseMember, Security).join(Security, Security.id == SavedUniverseMember.security_id).filter(SavedUniverseMember.universe_id == universe.id).order_by(SavedUniverseMember.position).all()
    return {
        "id": universe.id, "name": universe.name, "market": universe.market,
        "archived": universe.archived, "created_at": universe.created_at,
        "updated_at": universe.updated_at,
        "securities": [_security_dict(security) for _, security in rows],
    }


@router.get("/universes")
def universes_list(include_archived: bool = False):
    from v2.persistence.models import SavedUniverse
    init_db(_DB_PATH)
    with get_session(_DB_PATH) as session:
        query = session.query(SavedUniverse)
        if not include_archived:
            query = query.filter(SavedUniverse.archived.is_(False))
        return {"universes": [_universe_dict(session, row) for row in query.order_by(SavedUniverse.name).all()]}


def _replace_universe_members(session, universe_id: int, security_ids: list[int]) -> None:
    from v2.persistence.models import SavedUniverseMember, Security
    unique_ids = list(dict.fromkeys(security_ids))
    found = {
        row[0]
        for offset in range(0, len(unique_ids), 500)
        for row in session.query(Security.id).filter(
            Security.id.in_(unique_ids[offset:offset + 500]),
            Security.market == "US",
            Security.selectable.is_(True),
        ).all()
    }
    if found != set(unique_ids):
        raise HTTPException(status_code=422, detail="one or more securities are missing or not selectable")
    session.query(SavedUniverseMember).filter_by(universe_id=universe_id).delete()
    for position, security_id in enumerate(unique_ids):
        session.add(SavedUniverseMember(universe_id=universe_id, security_id=security_id, position=position))


@router.post("/universes", status_code=201)
def universe_create(data: UniverseCreateRequest):
    from v2.persistence.models import SavedUniverse
    init_db(_DB_PATH)
    with get_session(_DB_PATH) as session:
        row = SavedUniverse(name=data.name, market="US")
        session.add(row)
        try:
            session.flush()
            _replace_universe_members(session, row.id, data.security_ids)
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail="universe name already exists") from exc
        return _universe_dict(session, row)


@router.patch("/universes/{universe_id}")
def universe_update(universe_id: int, data: UniverseUpdateRequest):
    from v2.persistence.models import SavedUniverse
    init_db(_DB_PATH)
    with get_session(_DB_PATH) as session:
        row = session.get(SavedUniverse, universe_id)
        if row is None:
            raise HTTPException(status_code=404, detail="universe not found")
        if data.name is not None:
            row.name = data.name.strip()
        if data.archived is not None:
            row.archived = data.archived
        if data.security_ids is not None:
            _replace_universe_members(session, row.id, data.security_ids)
        row.updated_at = datetime.now(timezone.utc).isoformat()
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail="universe name already exists") from exc
        return _universe_dict(session, row)


def _resolve_cache_selection(selection: CacheSelectionRequest) -> list[str]:
    from v2.persistence.models import SavedUniverseMember, Security
    init_db(_DB_PATH)
    with get_session(_DB_PATH) as session:
        if selection.tickers is not None:
            return selection.tickers
        if selection.security_ids is not None:
            rows = [
                row
                for offset in range(0, len(selection.security_ids), 500)
                for row in session.query(Security).filter(
                    Security.id.in_(selection.security_ids[offset:offset + 500]),
                    Security.market == "US",
                    Security.selectable.is_(True),
                ).all()
            ]
            by_id = {row.id: row.symbol for row in rows}
            if len(by_id) != len(set(selection.security_ids)):
                raise HTTPException(status_code=422, detail="one or more securities are missing or not selectable")
            return [by_id[value] for value in selection.security_ids]
        if selection.universe_id is not None:
            rows = session.query(Security.symbol).join(SavedUniverseMember, SavedUniverseMember.security_id == Security.id).filter(SavedUniverseMember.universe_id == selection.universe_id).order_by(SavedUniverseMember.position).all()
            if not rows:
                raise HTTPException(status_code=422, detail="saved universe is empty or missing")
            return [row[0] for row in rows]
        rows = _security_query(session, selection.filter or SecurityFilterRequest()).order_by(Security.symbol).limit(1001).all()
        if len(rows) > 1000:
            raise HTTPException(status_code=422, detail="filtered selection exceeds 1000 securities")
        if not rows:
            raise HTTPException(status_code=422, detail="filtered selection is empty")
        return [row.symbol for row in rows]


@router.get("/cache/jobs")
def cache_jobs_list():
    from v2.data.cache_jobs import get_cache_job_manager
    return {"jobs": get_cache_job_manager(_DB_PATH).list()}


@router.post("/cache/jobs", status_code=202)
def cache_job_create(data: CacheJobCreateRequest):
    from v2.data.cache_jobs import get_cache_job_manager
    tickers = _resolve_cache_selection(data.selection)
    return get_cache_job_manager(_DB_PATH).create(
        tickers, data.benchmark, data.start_date.isoformat(), data.end_date.isoformat(), data.data_types, data.force,
    )


@router.get("/cache/jobs/{job_id}")
def cache_job_detail(job_id: str):
    from v2.data.cache_jobs import get_cache_job_manager
    result = get_cache_job_manager(_DB_PATH).get(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="cache job not found")
    return result


@router.post("/cache/jobs/{job_id}/cancel")
def cache_job_cancel(job_id: str):
    from v2.data.cache_jobs import get_cache_job_manager
    result = get_cache_job_manager(_DB_PATH).cancel(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="cache job not found")
    return result


@router.post("/cache/jobs/{job_id}/retry", status_code=202)
def cache_job_retry(job_id: str):
    from v2.data.cache_jobs import get_cache_job_manager
    result = get_cache_job_manager(_DB_PATH).retry(job_id)
    if result is None:
        raise HTTPException(status_code=409, detail="cache job has no failed items to retry")
    return result


@router.post("/cache/fetch")
def cache_fetch(data: CacheFetchRequest):
    """Fetch and cache historical prices + financial metrics from yfinance.

    Body: {"tickers": ["AAPL"], "start_date": "2024-01-01", "end_date": "2024-12-31"}
    """
    # Compatibility endpoint: new UI uses background jobs, while older clients
    # retain the original response shape through the same normalized cache service.
    from v2.data.cache_service import fetch_security_data
    from v2.data.market import USMarketDataAdapter
    from v2.data import yfinance_client as yahoo_module

    start_date, end_date = data.start_date.isoformat(), data.end_date.isoformat()
    adapter = USMarketDataAdapter(client=yahoo_module.YFinanceClient())
    results: dict[str, dict] = {}
    for ticker in data.tickers:
        detail = fetch_security_data(
            _DB_PATH, ticker, start_date, end_date,
            ["prices", "metrics", "earnings"], force=True, adapter=adapter,
        )
        failures = [
            f"{kind}: {value.get('error')}"
            for kind in ("prices", "metrics", "earnings")
            if (value := detail.get(kind)) and value.get("status") in {"failed", "no_data"} and value.get("error")
        ]
        results[ticker] = {
            "prices": (detail.get("prices") or {}).get("count", 0),
            "metrics": (detail.get("metrics") or {}).get("count", 0),
            "earnings": (detail.get("earnings") or {}).get("count", 0),
            "error": "; ".join(failures) or None,
            "warnings": detail.get("warnings", []),
        }
    benchmark_result = None
    if data.benchmark not in data.tickers:
        detail = fetch_security_data(
            _DB_PATH, data.benchmark, start_date, end_date,
            ["prices"], force=True, adapter=adapter,
        )
        price = detail.get("prices") or {}
        benchmark_result = {
            "ticker": data.benchmark, "prices": price.get("count", 0),
            "error": price.get("error"),
        }
    adapter.client.close()
    return {"results": results, "benchmark": benchmark_result}


@router.get("/cache/list")
def cache_list():
    """List all cached tickers with data ranges."""
    from sqlalchemy import func
    from v2.persistence.models import CacheCoverage, EarningsCache, MetricsCache, PriceCache

    init_db(_DB_PATH)
    session = get_session(_DB_PATH)
    try:
        price_rows = (
            session.query(
                PriceCache.ticker,
                func.min(PriceCache.date).label("min_date"),
                func.max(PriceCache.date).label("max_date"),
                func.count().label("cnt"),
                func.group_concat(func.distinct(PriceCache.price_mode)).label("price_modes"),
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
        coverage_rows = session.query(CacheCoverage).filter(CacheCoverage.data_kind == "prices").order_by(CacheCoverage.fetched_at).all()

        price_map = {r.ticker: {"min": r.min_date, "max": r.max_date, "count": r.cnt, "price_modes": (r.price_modes or "legacy_unknown").split(",")} for r in price_rows}
        metrics_map = {r.ticker: {"min": r.min_period, "max": r.max_period, "count": r.cnt} for r in metrics_rows}
        earnings_map = {r[0]: {"min": r[1], "max": r[2], "count": r[3]} for r in earnings_rows}
        coverage_map = {r.ticker: {
            "status": r.status, "requested_start": r.requested_start,
            "requested_end": r.requested_end, "actual_start": r.actual_start,
            "actual_end": r.actual_end, "missing_sessions": r.missing_sessions,
            "fetched_at": r.fetched_at,
        } for r in coverage_rows}

        all_tickers = set(price_map) | set(metrics_map) | set(earnings_map)
        result = {}
        for t in sorted(all_tickers):
            result[t] = {
                "prices": price_map.get(t),
                "metrics": metrics_map.get(t),
                "earnings": earnings_map.get(t),
                "coverage": coverage_map.get(t),
                "filing_date_note": "quarterly metrics use estimated report_period + 45 days",
            }
        return {"cached": result}
    finally:
        session.close()


@router.get("/cache/securities")
def cached_securities_list(
    search: str = Query(default="", max_length=100),
    status: str | None = Query(default=None, max_length=20),
    price_mode: str | None = Query(default=None, pattern=r"^(raw|legacy_unknown)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: str = Query(
        default="symbol",
        pattern=r"^(symbol|name|exchange|actual_start|actual_end|rows|latest_close|latest_volume|updated_at)$",
    ),
    sort_dir: str = Query(default="asc", pattern=r"^(asc|desc)$"),
):
    """Paginated cache inventory used by the cache explorer table."""
    from sqlalchemy import and_, func
    from v2.persistence.models import PriceCache, Security

    cached = cache_list()["cached"]
    tickers = list(cached)
    init_db(_DB_PATH)
    with get_session(_DB_PATH) as session:
        securities = {
            row.symbol: row
            for offset in range(0, len(tickers), 500)
            for row in session.query(Security).filter(
                Security.market == "US",
                Security.symbol.in_(tickers[offset:offset + 500]),
            ).all()
        }
        latest_dates = session.query(
            PriceCache.ticker.label("ticker"),
            func.max(PriceCache.date).label("latest_date"),
        ).group_by(PriceCache.ticker).subquery()
        latest_rows = session.query(PriceCache).join(
            latest_dates,
            and_(
                PriceCache.ticker == latest_dates.c.ticker,
                PriceCache.date == latest_dates.c.latest_date,
            ),
        ).all()
        latest = {row.ticker: row for row in latest_rows}

    rows = []
    needle = search.strip().lower()
    for ticker, item in cached.items():
        security = securities.get(ticker)
        coverage = item.get("coverage") or {}
        modes = (item.get("prices") or {}).get("price_modes") or []
        name = security.name if security else ""
        if needle and needle not in ticker.lower() and needle not in name.lower():
            continue
        if status and coverage.get("status") != status:
            continue
        if price_mode and price_mode not in modes:
            continue
        last = latest.get(ticker)
        rows.append({
            "ticker": ticker,
            "name": name,
            "exchange": security.exchange if security else "",
            "asset_type": security.asset_type if security else "",
            **item,
            "latest_close": last.close if last else None,
            "latest_adjusted_close": last.adjusted_close if last else None,
            "latest_volume": last.volume if last else None,
            "latest_date": last.date if last else None,
        })

    def sort_value(row):
        coverage = row.get("coverage") or {}
        prices = row.get("prices") or {}
        values = {
            "symbol": row["ticker"],
            "name": row.get("name") or "",
            "exchange": row.get("exchange") or "",
            "actual_start": coverage.get("actual_start") or "",
            "actual_end": coverage.get("actual_end") or "",
            "rows": prices.get("count") or 0,
            "latest_close": row.get("latest_close") or 0,
            "latest_volume": row.get("latest_volume") or 0,
            "updated_at": coverage.get("fetched_at") or "",
        }
        return values[sort_by]

    rows.sort(key=lambda row: (sort_value(row), row["ticker"]), reverse=sort_dir == "desc")
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "items": rows[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/cache/securities/{ticker}")
def cached_security_detail(
    ticker: str,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """Return all effective cached data for one security and optional date range."""
    from v2.persistence.models import CacheCoverage, EarningsCache, MetricsCache, PriceCache, Security

    symbol = CacheFetchRequest.valid_benchmark(ticker)
    init_db(_DB_PATH)
    with get_session(_DB_PATH) as session:
        price_query = session.query(PriceCache).filter(PriceCache.ticker == symbol)
        if start_date:
            price_query = price_query.filter(PriceCache.date >= start_date.isoformat())
        if end_date:
            price_query = price_query.filter(PriceCache.date <= end_date.isoformat())
        prices = price_query.order_by(PriceCache.date).all()
        metrics = session.query(MetricsCache).filter_by(ticker=symbol).order_by(MetricsCache.report_period.desc()).all()
        earnings = session.query(EarningsCache).filter_by(ticker=symbol).order_by(EarningsCache.announcement_date.desc()).all()
        coverage = session.query(CacheCoverage).filter_by(ticker=symbol).order_by(CacheCoverage.fetched_at.desc()).all()
        security = session.query(Security).filter_by(market="US", symbol=symbol).one_or_none()
        if not prices and not metrics and not earnings:
            raise HTTPException(status_code=404, detail="cached security not found")
        return {
            "ticker": symbol,
            "security": _security_dict(security) if security else None,
            "prices": [
                {
                    "date": row.date, "open": row.open, "high": row.high,
                    "low": row.low, "close": row.close,
                    "adjusted_close": row.adjusted_close, "volume": row.volume,
                    "dividend": row.dividend, "split_ratio": row.split_ratio,
                    "source": row.source, "price_mode": row.price_mode,
                }
                for row in prices
            ],
            "metrics": [
                {
                    "report_period": row.report_period,
                    "filing_date": row.filing_date,
                    "filing_date_source": row.filing_date_source,
                    "data": json.loads(row.data),
                }
                for row in metrics
            ],
            "earnings": [
                {
                    "report_period": row.report_period,
                    "announcement_date": row.announcement_date,
                    "actual_eps": row.actual_eps,
                    "estimated_eps": row.estimated_eps,
                    "surprise_pct": row.surprise_pct,
                    "source": row.source,
                }
                for row in earnings
            ],
            "coverage_history": [
                {
                    "data_kind": row.data_kind,
                    "requested_start": row.requested_start,
                    "requested_end": row.requested_end,
                    "actual_start": row.actual_start,
                    "actual_end": row.actual_end,
                    "row_count": row.row_count,
                    "missing_sessions": row.missing_sessions,
                    "status": row.status,
                    "error_category": row.error_category,
                    "error_message": row.error_message,
                    "fetched_at": row.fetched_at,
                }
                for row in coverage
            ],
        }


@router.delete("/cache/{ticker}")
def cache_delete(ticker: str):
    """Delete all cached data for a ticker."""
    from v2.persistence.models import CacheCoverage, EarningsCache, MetricsCache, PriceCache

    t = ticker.upper().strip()
    init_db(_DB_PATH)
    session = get_session(_DB_PATH)
    try:
        pc = session.query(PriceCache).filter(PriceCache.ticker == t).delete()
        mc = session.query(MetricsCache).filter(MetricsCache.ticker == t).delete()
        ec = session.query(EarningsCache).filter(EarningsCache.ticker == t).delete()
        cc = session.query(CacheCoverage).filter(CacheCoverage.ticker == t).delete()
        session.commit()
        return {
            "ticker": t,
            "deleted_prices": pc,
            "deleted_metrics": mc,
            "deleted_earnings": ec,
            "deleted_coverage": cc,
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
