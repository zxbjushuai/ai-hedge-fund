"""US catalog synchronization and durable normalized cache persistence."""

from __future__ import annotations

import random
import time
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

import exchange_calendars as xcals

from hedge_fund.data.earnings import earnings_surprise_percent, has_actionable_surprise
from hedge_fund.data.errors import MarketDataError, NoDataError, classify_market_error
from hedge_fund.data.market import USMarketDataAdapter
from hedge_fund.persistence.database import get_session, init_db
from hedge_fund.persistence.models import CacheCoverage, EarningsCache, MetricsCache, PriceCache, Security


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@lru_cache(maxsize=128)
def _us_calendar(start_date: str, end_date: str):
    padding = timedelta(days=7)
    bounded_start = (date.fromisoformat(start_date) - padding).isoformat()
    bounded_end = (date.fromisoformat(end_date) + padding).isoformat()
    return xcals.get_calendar("XNYS", start=bounded_start, end=bounded_end)


def us_sessions(start_date: str, end_date: str) -> list[str]:
    return [str(value.date()) for value in _us_calendar(start_date, end_date).sessions_in_range(start_date, end_date)]


def sync_us_catalog(db_path: str, adapter: USMarketDataAdapter | None = None) -> dict:
    adapter = adapter or USMarketDataAdapter()
    entries = adapter.sync_catalog()
    init_db(db_path)
    stamp = _now()
    with get_session(db_path) as session:
        existing = {row.symbol: row for row in session.query(Security).filter_by(market="US").all()}
        seen: set[str] = set()
        created = updated = 0
        for item in entries:
            seen.add(item.symbol)
            row = existing.get(item.symbol)
            values = {
                "data_symbol": item.data_symbol, "name": item.name,
                "exchange": item.exchange, "asset_type": item.asset_type,
                "currency": item.currency, "active": True,
                "is_test": item.is_test, "selectable": item.selectable,
                "catalog_source": "nasdaq_trader", "synced_at": stamp,
            }
            if row is None:
                session.add(Security(market="US", symbol=item.symbol, **values))
                created += 1
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                updated += 1
        deactivated = 0
        for symbol, row in existing.items():
            if symbol not in seen and row.active:
                row.active = False
                row.synced_at = stamp
                deactivated += 1
        session.commit()
    return {"market": "US", "total": len(entries), "created": created, "updated": updated, "deactivated": deactivated, "synced_at": stamp}


def _retry(operation):
    delays = (1.0, 2.0, 4.0)
    for attempt in range(4):
        try:
            return operation()
        except Exception as exc:
            failure = classify_market_error(exc)
            if not failure.retryable or attempt == 3:
                raise failure from exc
            delay = failure.retry_after if failure.retry_after is not None else delays[attempt]
            time.sleep(max(0.0, delay) + random.uniform(0.0, 0.25))
    raise AssertionError("unreachable")


def _coverage_row(db_path: str, ticker: str, kind: str, start_date: str, end_date: str) -> CacheCoverage | None:
    with get_session(db_path) as session:
        return session.query(CacheCoverage).filter_by(
            market="US", ticker=ticker, data_kind=kind,
            requested_start=start_date, requested_end=end_date,
        ).first()


def _parse_timestamp(stamp: str) -> datetime | None:
    try:
        value = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def _fetched_recently(stamp: str) -> bool:
    fetched_at = _parse_timestamp(stamp)
    return fetched_at is not None and fetched_at >= datetime.now(timezone.utc) - timedelta(hours=24)


def _coverage_end_is_final(session_date: str, fetched_at: str) -> bool:
    fetched = _parse_timestamp(fetched_at)
    if fetched is None:
        return False
    try:
        close = _us_calendar(session_date, session_date).session_close(session_date).to_pydatetime()
    except (KeyError, ValueError):
        return False
    return fetched >= close


def coverage_is_fresh(db_path: str, ticker: str, kind: str, start_date: str, end_date: str) -> bool:
    row = _coverage_row(db_path, ticker, kind, start_date, end_date)
    if row is None or row.status != "complete":
        return False
    return _fetched_recently(row.fetched_at)


def plan_price_fetch(db_path: str, ticker: str, start_date: str, end_date: str, *, force: bool = False) -> dict:
    """Return the smallest session gap that still needs a remote price fetch."""
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    expected_sessions = us_sessions(start_date, end_date)
    if not expected_sessions:
        return {
            "status": "skipped", "reason": "no US trading sessions in requested range",
            "requested_start": start_date, "requested_end": end_date,
            "fetch_start": None, "fetch_end": None,
        }
    if force:
        return {
            "status": "fetch", "reason": "forced refresh",
            "requested_start": start_date, "requested_end": end_date,
            "fetch_start": start_date, "fetch_end": end_date,
        }

    with get_session(db_path) as session:
        rows = session.query(CacheCoverage).filter_by(
            market="US", ticker=ticker, data_kind="prices", status="complete",
        ).all()
    intervals: list[tuple[str, str]] = []
    for row in rows:
        if not row.actual_end or not _fetched_recently(row.fetched_at):
            continue
        coverage_start = min(row.requested_start, row.actual_start or row.requested_start)
        coverage_end = row.actual_end
        if not _coverage_end_is_final(row.actual_end, row.fetched_at):
            try:
                coverage_end = str(_us_calendar(row.actual_end, row.actual_end).previous_session(row.actual_end).date())
            except (KeyError, ValueError):
                continue
        if coverage_start <= end_date and coverage_end >= start_date:
            intervals.append((max(start_date, coverage_start), min(end_date, coverage_end)))

    merged: list[tuple[str, str]] = []
    for interval_start, interval_end in sorted(intervals):
        if merged and interval_start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], interval_end))
        else:
            merged.append((interval_start, interval_end))

    missing: list[str] = []
    interval_index = 0
    for session in expected_sessions:
        while interval_index < len(merged) and merged[interval_index][1] < session:
            interval_index += 1
        if interval_index == len(merged) or not (merged[interval_index][0] <= session <= merged[interval_index][1]):
            missing.append(session)

    if not missing:
        return {
            "status": "skipped", "reason": "no missing US trading sessions",
            "requested_start": start_date, "requested_end": end_date,
            "fetch_start": None, "fetch_end": None,
        }
    fetch_start = missing[0]
    return {
        "status": "fetch", "reason": "missing price sessions",
        "requested_start": start_date, "requested_end": end_date,
        "fetch_start": fetch_start, "fetch_end": end_date,
    }


def contains_corporate_action(prices: list) -> bool:
    for price in prices:
        if (getattr(price, "dividend", 0.0) or 0.0) != 0.0:
            return True
        if (getattr(price, "split_ratio", 0.0) or 0.0) not in {0.0, 1.0}:
            return True
    return False


def annotate_price_result(detail: dict, plan: dict, *, fetch_start: str | None = None, refreshed_for_corporate_action: bool = False) -> dict:
    result = dict(detail)
    actual_fetch_start = fetch_start if fetch_start is not None else plan["fetch_start"]
    result.update({
        "requested_start": plan["requested_start"], "requested_end": plan["requested_end"],
        "fetch_start": actual_fetch_start, "fetch_end": plan["fetch_end"],
        "incremental": actual_fetch_start != plan["requested_start"],
        "refreshed_for_corporate_action": refreshed_for_corporate_action,
    })
    return result


def fetch_price_data(db_path: str, ticker: str, start_date: str, end_date: str, *, force: bool = False, adapter: USMarketDataAdapter | None = None) -> dict:
    adapter = adapter or USMarketDataAdapter()
    plan = plan_price_fetch(db_path, ticker, start_date, end_date, force=force)
    if plan["status"] == "skipped":
        return {"status": "skipped", "reason": plan["reason"], "requested_start": start_date, "requested_end": end_date, "incremental": False}

    fetch_start = plan["fetch_start"]
    values = _retry(lambda: adapter.get_prices(ticker, fetch_start, plan["fetch_end"]))
    refreshed_for_corporate_action = False
    if fetch_start != start_date and contains_corporate_action(values):
        values = _retry(lambda: adapter.get_prices(ticker, start_date, end_date))
        fetch_start = start_date
        refreshed_for_corporate_action = True
    detail = persist_prices(db_path, ticker, values, fetch_start, plan["fetch_end"])
    return annotate_price_result(detail, plan, fetch_start=fetch_start, refreshed_for_corporate_action=refreshed_for_corporate_action)


def _save_coverage(
    db_path: str, ticker: str, kind: str, start_date: str, end_date: str,
    *, status: str, row_count: int = 0, actual_start: str | None = None,
    actual_end: str | None = None, expected: int = 0, missing: int = 0,
    failure: MarketDataError | None = None,
) -> None:
    with get_session(db_path) as session:
        row = session.query(CacheCoverage).filter_by(
            market="US", ticker=ticker, data_kind=kind,
            requested_start=start_date, requested_end=end_date,
        ).first()
        values = dict(
            actual_start=actual_start, actual_end=actual_end, row_count=row_count,
            expected_sessions=expected, missing_sessions=missing, status=status,
            error_category=failure.category if failure else None,
            error_message=str(failure)[:500] if failure else None, fetched_at=_now(),
        )
        if row is None:
            row = CacheCoverage(
                market="US", ticker=ticker, data_kind=kind,
                requested_start=start_date, requested_end=end_date, **values,
            )
            session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        session.commit()


def persist_prices(db_path: str, ticker: str, prices: list, start_date: str, end_date: str) -> dict:
    returned_dates: set[str] = set()
    stamp = _now()
    with get_session(db_path) as session:
        existing = {
            row.date: row for row in session.query(PriceCache).filter(
                PriceCache.ticker == ticker,
                PriceCache.date >= start_date,
                PriceCache.date <= end_date,
            ).all()
        }
        for price in prices:
            day = price.time[:10]
            returned_dates.add(day)
            values = dict(
                open=price.open, high=price.high, low=price.low, close=price.close,
                adjusted_close=price.adjusted_close, volume=price.volume,
                dividend=price.dividend, split_ratio=price.split_ratio,
                source="yahoo", price_mode="raw", updated_at=stamp,
            )
            row = existing.get(day)
            if row is None:
                session.add(PriceCache(ticker=ticker, date=day, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        session.commit()
    actual_start = min(returned_dates) if returned_dates else None
    actual_end = max(returned_dates) if returned_dates else None
    expected_dates = us_sessions(actual_start or start_date, end_date) if returned_dates else us_sessions(start_date, end_date)
    missing = len(set(expected_dates) - returned_dates)
    status = "complete" if returned_dates and missing == 0 else ("partial" if returned_dates else "no_data")
    _save_coverage(
        db_path, ticker, "prices", start_date, end_date, status=status,
        row_count=len(returned_dates), actual_start=actual_start, actual_end=actual_end,
        expected=len(expected_dates), missing=missing,
    )
    return {
        "status": status, "count": len(returned_dates), "requested_start": start_date,
        "requested_end": end_date, "actual_start": actual_start, "actual_end": actual_end,
        "expected_sessions": len(expected_dates), "missing_sessions": missing,
        "price_mode": "raw",
    }


def _persist_metrics(db_path: str, ticker: str, metrics: list, end_date: str) -> int:
    with get_session(db_path) as session:
        for metric in metrics:
            row = session.query(MetricsCache).filter_by(ticker=ticker, report_period=metric.report_period).first()
            payload = metric.model_dump_json(exclude={
                "ticker", "market_cap", "enterprise_value", "price_to_earnings_ratio",
                "price_to_book_ratio", "price_to_sales_ratio", "enterprise_value_to_ebitda_ratio",
                "enterprise_value_to_revenue_ratio", "peg_ratio",
            })
            # TODO(event-driven-persona): replace this estimate with authoritative filing timestamps.
            filing_date = (date.fromisoformat(metric.report_period) + timedelta(days=45)).isoformat()
            values = dict(data=payload, filing_date=filing_date, filing_date_source="estimated_45d")
            if row is None:
                session.add(MetricsCache(ticker=ticker, report_period=metric.report_period, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        session.commit()
    return len(metrics)


def _persist_earnings(db_path: str, ticker: str, earnings: list) -> tuple[int, list[str]]:
    warnings: list[str] = []
    if not earnings:
        warnings.append("Yahoo returned no earnings history; PEAD will remain neutral")
    elif not has_actionable_surprise(earnings):
        warnings.append("Yahoo returned no complete actual/estimate EPS surprise; PEAD will remain neutral")
    with get_session(db_path) as session:
        for event in earnings:
            if not event.filing_date:
                continue
            quarterly = event.quarterly
            values = dict(
                report_period=event.report_period,
                actual_eps=quarterly.earnings_per_share if quarterly else None,
                estimated_eps=quarterly.estimated_earnings_per_share if quarterly else None,
                surprise_pct=earnings_surprise_percent(event), source="yahoo",
            )
            row = session.query(EarningsCache).filter_by(ticker=ticker, announcement_date=event.filing_date).first()
            if row is None:
                session.add(EarningsCache(ticker=ticker, announcement_date=event.filing_date, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        session.commit()
    return len(earnings), warnings


def fetch_security_data(
    db_path: str,
    ticker: str,
    start_date: str,
    end_date: str,
    data_types: list[str] | tuple[str, ...] = ("prices",),
    *,
    force: bool = False,
    adapter: USMarketDataAdapter | None = None,
) -> dict:
    """Fetch one ticker. Each data kind commits independently."""
    init_db(db_path)
    adapter = adapter or USMarketDataAdapter()
    ticker = ticker.strip().upper()
    result = {"ticker": ticker, "prices": None, "metrics": None, "earnings": None, "warnings": []}
    for kind in data_types:
        try:
            if kind == "prices":
                result[kind] = fetch_price_data(db_path, ticker, start_date, end_date, force=force, adapter=adapter)
            elif kind == "metrics":
                if not force and coverage_is_fresh(db_path, ticker, kind, start_date, end_date):
                    result[kind] = {"status": "skipped", "reason": "fresh complete coverage"}
                    continue
                values = _retry(lambda: adapter.get_financial_metrics(ticker, end_date, limit=40))
                count = _persist_metrics(db_path, ticker, values, end_date)
                result[kind] = {"status": "complete" if count else "no_data", "count": count}
                _save_coverage(db_path, ticker, kind, start_date, end_date, status=result[kind]["status"], row_count=count)
            elif kind == "earnings":
                if not force and coverage_is_fresh(db_path, ticker, kind, start_date, end_date):
                    result[kind] = {"status": "skipped", "reason": "fresh complete coverage"}
                    continue
                values = _retry(lambda: adapter.get_earnings_history(ticker, limit=40))
                count, warnings = _persist_earnings(db_path, ticker, values)
                result["warnings"].extend(warnings)
                result[kind] = {"status": "complete" if count else "no_data", "count": count}
                _save_coverage(db_path, ticker, kind, start_date, end_date, status=result[kind]["status"], row_count=count)
            else:
                raise ValueError(f"unsupported data type: {kind}")
        except Exception as exc:
            failure = classify_market_error(exc)
            _save_coverage(db_path, ticker, kind, start_date, end_date, status="no_data" if isinstance(failure, NoDataError) else "failed", failure=failure)
            result[kind] = {"status": "no_data" if isinstance(failure, NoDataError) else "failed", "error_category": failure.category, "error": str(failure)}
    return result


def serialize_coverage(row: CacheCoverage | None) -> dict | None:
    if row is None:
        return None
    return {
        "status": row.status, "requested_start": row.requested_start,
        "requested_end": row.requested_end, "actual_start": row.actual_start,
        "actual_end": row.actual_end, "row_count": row.row_count,
        "expected_sessions": row.expected_sessions, "missing_sessions": row.missing_sessions,
        "error_category": row.error_category, "error": row.error_message,
        "fetched_at": row.fetched_at,
    }
