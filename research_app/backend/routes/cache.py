from __future__ import annotations
import json
import logging
from datetime import date
from fastapi import APIRouter, HTTPException, Query
from hedge_fund.persistence.database import get_session, init_db
from research_app.backend.config import settings
from .schemas import CacheFetchRequest, SecurityFilterRequest, CacheSelectionRequest, CacheJobCreateRequest
from .securities import _security_query, _security_dict

router = APIRouter(prefix="/dashboard", tags=["cache"])
logger = logging.getLogger(__name__)
_DB_PATH = str(settings.fund_db)

def _resolve_cache_selection(selection: CacheSelectionRequest) -> list[str]:
    from hedge_fund.persistence.models import SavedUniverseMember, Security
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
    from hedge_fund.data.cache_jobs import get_cache_job_manager
    return {"jobs": get_cache_job_manager(_DB_PATH).list()}


@router.post("/cache/jobs", status_code=202)
def cache_job_create(data: CacheJobCreateRequest):
    from hedge_fund.data.cache_jobs import get_cache_job_manager
    tickers = _resolve_cache_selection(data.selection)
    return get_cache_job_manager(_DB_PATH).create(
        tickers, data.benchmark, data.start_date.isoformat(), data.end_date.isoformat(), data.data_types, data.force,
    )


@router.get("/cache/jobs/{job_id}")
def cache_job_detail(job_id: str):
    from hedge_fund.data.cache_jobs import get_cache_job_manager
    result = get_cache_job_manager(_DB_PATH).get(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="cache job not found")
    return result


@router.post("/cache/jobs/{job_id}/cancel")
def cache_job_cancel(job_id: str):
    from hedge_fund.data.cache_jobs import get_cache_job_manager
    result = get_cache_job_manager(_DB_PATH).cancel(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="cache job not found")
    return result


@router.post("/cache/jobs/{job_id}/retry", status_code=202)
def cache_job_retry(job_id: str):
    from hedge_fund.data.cache_jobs import get_cache_job_manager
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
    from hedge_fund.data.cache_service import fetch_security_data
    from hedge_fund.data.market import USMarketDataAdapter
    from hedge_fund.data import yfinance_client as yahoo_module

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
    from hedge_fund.data.cache_service import us_sessions
    from hedge_fund.persistence.models import CacheCoverage, EarningsCache, MetricsCache, PriceCache

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
        coverage_by_ticker = {}
        for row in coverage_rows:
            coverage_by_ticker.setdefault(row.ticker, []).append(row)
        exact_tickers = [
            ticker for ticker, rows in coverage_by_ticker.items()
            if any(row.status != "complete" for row in rows)
        ]
        exact_dates: dict[str, set[str]] = {}
        for offset in range(0, len(exact_tickers), 500):
            for ticker, session_date in session.query(PriceCache.ticker, PriceCache.date).filter(
                PriceCache.ticker.in_(exact_tickers[offset:offset + 500]),
            ).all():
                exact_dates.setdefault(ticker, set()).add(session_date)
        coverage_map = {}
        for ticker, rows in coverage_by_ticker.items():
            latest = rows[-1]
            requested_start = min(row.requested_start for row in rows)
            requested_end = max(row.requested_end for row in rows)
            expected_sessions = set(us_sessions(requested_start, requested_end))
            if ticker in exact_dates:
                covered_sessions = exact_dates[ticker] & expected_sessions
            else:
                covered_sessions = set()
                for row in rows:
                    if row.status != "complete" or not row.actual_end:
                        continue
                    interval_start = min(row.requested_start, row.actual_start or row.requested_start)
                    interval_end = row.actual_end
                    if interval_start <= interval_end:
                        covered_sessions.update(us_sessions(max(requested_start, interval_start), min(requested_end, interval_end)))
            missing_sessions = len(expected_sessions - covered_sessions)
            if expected_sessions and not missing_sessions:
                status = "complete"
            elif covered_sessions:
                status = "partial"
            else:
                status = latest.status
            actual_starts = [row.actual_start for row in rows if row.actual_start]
            actual_ends = [row.actual_end for row in rows if row.actual_end]
            coverage_map[ticker] = {
                "status": status, "requested_start": requested_start,
                "requested_end": requested_end,
                "actual_start": min(actual_starts) if actual_starts else None,
                "actual_end": max(actual_ends) if actual_ends else None,
                "missing_sessions": missing_sessions, "fetched_at": latest.fetched_at,
            }

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
    from hedge_fund.persistence.models import PriceCache, Security

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
    from hedge_fund.persistence.models import CacheCoverage, EarningsCache, MetricsCache, PriceCache, Security

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
    from hedge_fund.persistence.models import CacheCoverage, EarningsCache, MetricsCache, PriceCache

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


