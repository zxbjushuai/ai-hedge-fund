"""Read and validate the closing book of a completed simulation run."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math

from sqlalchemy import select

from hedge_fund.persistence.database import get_session, init_db
from hedge_fund.persistence.models import SimCycleRecord, SimNavSnapshot, SimRun


class CarrySourceError(ValueError):
    """A completed run cannot safely seed the requested child run."""


@dataclass(frozen=True)
class CarriedBook:
    run_id: int
    valuation_date: str
    nav: float
    cash: float
    positions: dict[str, int]
    tickers: tuple[str, ...]
    benchmark: str


def load_carried_book(
    db_path: str,
    source_run_id: int,
    *,
    expected_start: str,
    expected_tickers: list[str],
    expected_benchmark: str,
) -> CarriedBook:
    """Return a parent run's final book after checking continuity constraints."""
    init_db(db_path)
    with get_session(db_path) as session:
        run = session.get(SimRun, source_run_id)
        if run is None:
            raise CarrySourceError(f"carry source run {source_run_id} does not exist")
        if run.status != "completed" or run.final_nav is None:
            raise CarrySourceError(f"carry source run {source_run_id} is not a completed simulation")
        run_tickers = tuple(json.loads(run.tickers))
        if set(run_tickers) != set(expected_tickers):
            raise CarrySourceError("carry source universe must match the child run universe")
        source_benchmark = (run.benchmark or "").strip().upper()
        if source_benchmark != expected_benchmark.strip().upper():
            raise CarrySourceError("carry source benchmark must match the child run benchmark")

        nav_row = session.execute(select(SimNavSnapshot).where(SimNavSnapshot.sim_run_id == source_run_id).order_by(SimNavSnapshot.cycle_date.desc()).limit(1)).scalar_one_or_none()
        if nav_row is None:
            raise CarrySourceError(f"carry source run {source_run_id} has no NAV history")
        if nav_row.cycle_date != expected_start:
            raise CarrySourceError(f"child run must start on carry source final valuation date " f"{nav_row.cycle_date}")

        cycle = session.execute(
            select(SimCycleRecord)
            .where(
                SimCycleRecord.sim_run_id == source_run_id,
                SimCycleRecord.status == "completed",
            )
            .order_by(SimCycleRecord.cycle_number.desc())
            .limit(1)
        ).scalar_one_or_none()
        if cycle is None or cycle.payload is None:
            raise CarrySourceError(f"carry source run {source_run_id} has no completed cycle book")
        payload = json.loads(cycle.payload)
        positions = {ticker.upper(): int(shares) for ticker, shares in payload.get("positions", {}).items() if int(shares) != 0}
        cash = float(payload["cash"])
        cycle_nav = float(payload["nav"])

        if not math.isclose(float(run.final_nav), float(nav_row.nav), abs_tol=0.01):
            raise CarrySourceError("carry source final NAV is inconsistent")
        if not math.isclose(cycle_nav, float(nav_row.nav), abs_tol=0.01):
            raise CarrySourceError("carry source cycle NAV is inconsistent")
        if not math.isclose(cash, float(nav_row.cash), abs_tol=0.01):
            raise CarrySourceError("carry source cycle cash is inconsistent")

        return CarriedBook(
            run_id=source_run_id,
            valuation_date=nav_row.cycle_date,
            nav=float(nav_row.nav),
            cash=cash,
            positions=positions,
            tickers=run_tickers,
            benchmark=source_benchmark,
        )
