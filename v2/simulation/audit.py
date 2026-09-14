"""Atomic cycle audit persistence and read models for simulations."""

from __future__ import annotations

import json

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from v2.failures import classify_cycle_failure
from v2.persistence.database import get_session, init_db
from v2.persistence.models import (
    SimCycleRecord,
    SimCycleTickerIndex,
    SimNavSnapshot,
    SimRun,
    SimTradeLog,
)
from v2.pipeline.models import CycleRecord


def persist_completed_cycle(
    db_path: str,
    sim_run_id: int,
    cycle_number: int,
    record: CycleRecord,
    benchmark_nav: float,
) -> int:
    """Commit audit, ticker indexes, NAV, and fills as one unit."""
    session = get_session(db_path)
    try:
        row = SimCycleRecord(
            sim_run_id=sim_run_id,
            cycle_number=cycle_number,
            signal_date=record.as_of,
            execution_date=record.execution_date or record.as_of,
            status="completed",
            universe=json.dumps(record.universe),
            payload=record.model_dump_json(),
            cash=record.cash,
            nav=record.nav,
        )
        session.add(row)
        session.flush()
        for summary in _ticker_summaries(record):
            session.add(SimCycleTickerIndex(
                sim_cycle_record_id=row.id,
                sim_run_id=sim_run_id,
                **summary,
            ))
        session.add(SimNavSnapshot(
            sim_run_id=sim_run_id,
            cycle_date=record.execution_date or record.as_of,
            nav=record.nav,
            cash=record.cash,
            equity=record.nav - record.cash,
            benchmark_nav=benchmark_nav,
        ))
        for fill in record.fills:
            session.add(SimTradeLog(
                sim_run_id=sim_run_id,
                ticker=fill.ticker,
                side=fill.side.upper(),
                quantity=fill.quantity,
                price=fill.price,
                fee=fill.fee,
                total_amount=(
                    fill.total_amount
                    if fill.total_amount is not None
                    else fill.quantity * fill.price
                ),
                cycle_date=record.execution_date or record.as_of,
            ))
        session.commit()
        return row.id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def persist_failed_cycle(
    db_path: str,
    sim_run_id: int,
    cycle_number: int,
    signal_date: str,
    execution_date: str,
    universe: list[str],
    exc: Exception,
) -> int:
    failure = classify_cycle_failure(exc)
    with get_session(db_path) as session:
        row = SimCycleRecord(
            sim_run_id=sim_run_id,
            cycle_number=cycle_number,
            signal_date=signal_date,
            execution_date=execution_date,
            status="failed",
            universe=json.dumps(universe),
            error_category=failure.category,
            error_message=failure.message,
        )
        session.add(row)
        session.flush()
        for ticker in sorted(set(universe)):
            session.add(SimCycleTickerIndex(
                sim_cycle_record_id=row.id,
                sim_run_id=sim_run_id,
                ticker=ticker,
            ))
        session.commit()
        return row.id


def list_cycle_audits(
    sim_run_id: int,
    db_path: str,
    *,
    date: str | None = None,
    signal_date: str | None = None,
    execution_date: str | None = None,
    ticker: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict | None:
    init_db(db_path)
    with get_session(db_path) as session:
        if session.get(SimRun, sim_run_id) is None:
            return None
        query = select(SimCycleRecord).where(SimCycleRecord.sim_run_id == sim_run_id)
        if date:
            query = query.where(or_(
                SimCycleRecord.signal_date == date,
                SimCycleRecord.execution_date == date,
            ))
        if signal_date:
            query = query.where(SimCycleRecord.signal_date == signal_date)
        if execution_date:
            query = query.where(SimCycleRecord.execution_date == execution_date)
        if ticker:
            query = query.join(
                SimCycleTickerIndex,
                SimCycleTickerIndex.sim_cycle_record_id == SimCycleRecord.id,
            ).where(SimCycleTickerIndex.ticker == ticker.strip().upper())
        rows = session.execute(
            query.order_by(SimCycleRecord.cycle_number).offset(offset).limit(limit)
        ).scalars().all()
        items = [_summary(session, row) for row in rows]
        return {
            "sim_run_id": sim_run_id,
            "audit_available": bool(session.scalar(
                select(SimCycleRecord.id)
                .where(SimCycleRecord.sim_run_id == sim_run_id)
                .limit(1)
            )),
            "items": items,
            "limit": limit,
            "offset": offset,
        }


def get_cycle_audit(sim_run_id: int, cycle_id: int, db_path: str) -> dict | None:
    init_db(db_path)
    with get_session(db_path) as session:
        row = session.execute(select(SimCycleRecord).where(
            SimCycleRecord.id == cycle_id,
            SimCycleRecord.sim_run_id == sim_run_id,
        )).scalar_one_or_none()
        if row is None:
            return None
        result = _summary(session, row)
        result["record"] = json.loads(row.payload) if row.payload else None
        return result


def _ticker_summaries(record: CycleRecord) -> list[dict]:
    tickers = set(record.universe) | set(record.positions)
    tickers |= set(record.target_weights) | set(record.final_weights)
    tickers |= {item.ticker for item in record.orders}
    tickers |= {item.ticker for item in record.fills}
    tickers |= {item.ticker for item in record.skipped}
    signals = [signal for strategy in record.strategies for signal in strategy.signals]
    tickers |= {signal.ticker for signal in signals}

    result = []
    for ticker in sorted(tickers):
        ticker_signals = [signal for signal in signals if signal.ticker == ticker]
        statuses = [_effective_status(signal) for signal in ticker_signals]
        produced = [
            signal for signal, status in zip(ticker_signals, statuses)
            if status == "produced"
        ]
        result.append({
            "ticker": ticker,
            "produced_count": len(produced),
            "neutral_count": sum(signal.value == 0 for signal in produced),
            "abstained_count": statuses.count("abstained"),
            "failed_count": statuses.count("failed"),
            "target_weight": record.target_weights.get(ticker),
            "final_weight": record.final_weights.get(ticker),
            "order_count": sum(item.ticker == ticker for item in record.orders),
            "fill_count": sum(item.ticker == ticker for item in record.fills),
        })
    return result


def _effective_status(signal) -> str:
    """Honor pre-Workstream-3 metadata while new producers adopt typed status."""
    if signal.status != "produced":
        return signal.status
    if signal.metadata.get("failed") is True:
        return "failed"
    if signal.metadata.get("abstained") is True:
        return "abstained"
    return "produced"


def _summary(session: Session, row: SimCycleRecord) -> dict:
    tickers = session.execute(
        select(SimCycleTickerIndex)
        .where(SimCycleTickerIndex.sim_cycle_record_id == row.id)
        .order_by(SimCycleTickerIndex.ticker)
    ).scalars().all()
    return {
        "id": row.id,
        "sim_run_id": row.sim_run_id,
        "cycle_number": row.cycle_number,
        "signal_date": row.signal_date,
        "execution_date": row.execution_date,
        "status": row.status,
        "universe": json.loads(row.universe or "[]"),
        "error_category": row.error_category,
        "error_message": row.error_message,
        "cash": row.cash,
        "nav": row.nav,
        "tickers": [
            {
                "ticker": item.ticker,
                "produced_count": item.produced_count,
                "neutral_count": item.neutral_count,
                "abstained_count": item.abstained_count,
                "failed_count": item.failed_count,
                "target_weight": item.target_weight,
                "final_weight": item.final_weight,
                "order_count": item.order_count,
                "fill_count": item.fill_count,
            }
            for item in tickers
        ],
    }
