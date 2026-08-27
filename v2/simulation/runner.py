"""Simulation runner — run_cycle day-by-day over cached historical data."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from v2.brokers import SimBroker
from v2.data.mock_client import MockDataClient
from v2.fund import Fund, load_spec
from v2.persistence.database import get_session, init_db
from v2.persistence.models import EarningsCache, MetricsCache, PriceCache, SimNavSnapshot, SimRun, SimTradeLog
from v2.pipeline import run_cycle

logger = logging.getLogger(__name__)

_RUNNERS: dict[int, "SimRunner"] = {}
_LOCK = threading.Lock()


def _trading_days(db_path: str, tickers: list[str], start: str, end: str) -> list[str]:
    """Actual market days for which every selected ticker has a cached bar."""
    normalized = sorted({ticker.upper() for ticker in tickers})
    with get_session(db_path) as session:
        return list(session.execute(
            select(PriceCache.date).where(
                PriceCache.ticker.in_(normalized),
                PriceCache.date >= start, PriceCache.date <= end,
            )
            .group_by(PriceCache.date)
            .having(func.count(func.distinct(PriceCache.ticker)) == len(normalized))
            .order_by(PriceCache.date)
        ).scalars())


def estimate_filing_prompt_calls(
    db_path: str,
    tickers: list[str],
    trading_days: list[str],
    persona_names: set[str],
) -> int:
    """Cold-cache calls for bootstrap snapshots plus visible filing changes.

    Signals are formed on every trading day except the final execution day.
    Exact daily prices do not enter the quarterly fundamentals prompt.
    """
    if len(trading_days) < 2 or not persona_names:
        return 0
    first_signal_day = trading_days[0]
    last_signal_day = trading_days[-2]
    snapshot_count = 0
    with get_session(db_path) as session:
        for ticker in sorted(set(t.upper() for t in tickers)):
            changes = session.execute(
                select(MetricsCache.filing_date)
                .where(
                    MetricsCache.ticker == ticker,
                    MetricsCache.filing_date > first_signal_day,
                    MetricsCache.filing_date <= last_signal_day,
                )
                .distinct()
            ).scalars().all()
            snapshot_count += 1 + len(changes)
    return snapshot_count * len(persona_names)


def validate_cached_data(db_path: str, tickers: list[str], start: str, end: str, require_earnings: bool = True) -> tuple[list[str], list[str]]:
    """Fail-fast point-in-time coverage validation shared by API and runner."""
    days = _trading_days(db_path, tickers, start, end)
    errors: list[str] = []
    warnings: list[str] = []
    if len(days) < 2:
        errors.append("cached prices must cover at least two trading days")
    with get_session(db_path) as session:
        for ticker in tickers:
            ticker_days = session.query(PriceCache).filter(
                PriceCache.ticker == ticker, PriceCache.date >= start, PriceCache.date <= end
            ).count()
            if ticker_days == 0:
                errors.append(f"{ticker}: no cached prices in requested range")
            visible_metrics = session.query(MetricsCache).filter(
                MetricsCache.ticker == ticker, MetricsCache.filing_date <= start
            ).count()
            if visible_metrics < 4:
                errors.append(f"{ticker}: requires at least four visible quarterly metrics (found {visible_metrics})")
            earnings = session.query(EarningsCache).filter(
                EarningsCache.ticker == ticker,
                EarningsCache.announcement_date <= end,
                EarningsCache.surprise_pct.is_not(None),
                EarningsCache.surprise_pct != 0,
            ).count()
            if require_earnings and earnings == 0:
                warnings.append(f"{ticker}: no actionable EPS surprise; PEAD will be disabled if unavailable for the whole universe")
            elif earnings == 0:
                warnings.append(f"{ticker}: no earnings events; PEAD will be neutral")
    return errors, warnings


def disable_unavailable_models(spec, db_path: str, tickers: list[str], end: str) -> list[str]:
    """Disable optional strategies whose cached inputs cannot produce a signal."""
    warnings: list[str] = []
    has_pead = any(model.name == "pead" for strategy in spec.strategies for model in strategy.models)
    if has_pead:
        with get_session(db_path) as session:
            actionable = session.query(EarningsCache).filter(
                EarningsCache.ticker.in_([ticker.upper() for ticker in tickers]),
                EarningsCache.announcement_date <= end,
                EarningsCache.surprise_pct.is_not(None),
                EarningsCache.surprise_pct != 0,
            ).count()
        if actionable == 0:
            for strategy in spec.strategies:
                strategy.models = [model for model in strategy.models if model.name != "pead"]
            spec.strategies = [strategy for strategy in spec.strategies if strategy.models]
            warnings.append("PEAD disabled: cached Yahoo earnings contain no actionable EPS surprise")
    if not spec.strategies:
        raise ValueError("no strategy has usable cached inputs")
    return warnings


class SimRunner:
    """Run a fund simulation day-by-day against cached price/metrics data."""

    def __init__(
        self,
        sim_run_id: int,
        tickers: list[str],
        start_date: str,
        end_date: str,
        initial_capital: float,
        db_path: str,
        fund_spec_path: str,
        fee_rate: float = 0.001,
    ) -> None:
        self._id = sim_run_id
        self._tickers = tickers
        self._start = start_date
        self._end = end_date
        self._capital = initial_capital
        self._db_path = db_path
        self._fund_spec_path = fund_spec_path
        self._fee_rate = fee_rate
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        tickers: list[str],
        start_date: str,
        end_date: str,
        initial_capital: float,
        db_path: str,
        fund_spec_path: str,
        name: str = "",
        fee_rate: float = 0.001,
    ) -> int:
        """Create a SimRun row and return its id. Call start() to run."""
        init_db(db_path)
        session = get_session(db_path)
        try:
            days = _trading_days(db_path, tickers, start_date, end_date)
            if len(days) < 2:
                raise ValueError("cached prices must cover at least two trading days")
            run = SimRun(
                name=name,
                tickers=json.dumps(tickers),
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                status="pending",
                total_days=len(days),
            )
            session.add(run)
            session.commit()
            sim_id = run.id
        finally:
            session.close()

        with _LOCK:
            runner = cls(
                sim_run_id=sim_id,
                tickers=tickers,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                db_path=db_path,
                fund_spec_path=fund_spec_path,
                fee_rate=fee_rate,
            )
            _RUNNERS[sim_id] = runner
        return sim_id

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @staticmethod
    def _get(sim_id: int) -> SimRunner | None:
        with _LOCK:
            return _RUNNERS.get(sim_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        self._set_status("running")
        try:
            spec = load_spec(self._fund_spec_path)
            spec.universe = self._tickers
            spec.capital = self._capital
            require_earnings = any(m.name == "pead" for s in spec.strategies for m in s.models)
            errors, warnings = validate_cached_data(
                self._db_path, self._tickers, self._start, self._end, require_earnings
            )
            if errors:
                raise ValueError("; ".join(errors))
            warnings.extend(disable_unavailable_models(spec, self._db_path, self._tickers, self._end))
            enabled_models = [m.name for s in spec.strategies for m in s.models]
            logger.info(
                "sim %d started: tickers=%s range=%s..%s capital=%.2f models=%s warnings=%s",
                self._id, self._tickers, self._start, self._end, self._capital,
                enabled_models, warnings,
            )
            with get_session(self._db_path) as session:
                run = session.execute(select(SimRun).where(SimRun.id == self._id)).scalar_one()
                run.warnings = json.dumps(warnings)
                run.models = json.dumps(enabled_models)
                session.commit()
            days = _trading_days(self._db_path, self._tickers, self._start, self._end)
            data_client = MockDataClient(self._db_path)
            broker = SimBroker(cash=self._capital, fee_rate=self._fee_rate)
            fund = Fund(spec)  # preserve model and prompt caches across the whole run
            self._save_nav_snapshot(get_session(self._db_path), days[0], self._capital, self._capital, 0.0)
            self._set_progress(1)
            for i, day in enumerate(days[1:], start=1):
                signal_day = days[i - 1]
                opens, closes = self._prices_for_day(day)
                record = run_cycle(
                    fund, signal_day, broker, data_client,
                    execution_prices=opens, valuation_prices=closes, execution_date=day,
                )

                self._save_nav_snapshot(
                    session=get_session(self._db_path),
                    cycle_date=day,
                    nav=record.nav,
                    cash=record.cash,
                    equity=record.nav - record.cash,
                )

                if broker._last_trades:
                    logger.info(
                        "sim %d trades on %s: count=%d nav=%.2f cash=%.2f",
                        self._id, day, len(broker._last_trades), record.nav, record.cash,
                    )
                    self._save_trades(session=get_session(self._db_path), trades=broker._last_trades)
                    broker._last_trades = []
                self._set_progress(i + 1)
            self._finish(days)
        except Exception as exc:
            logger.exception("simulation %s failed", self._id)
            self._fail(str(exc))

    def _prices_for_day(self, day: str) -> tuple[dict[str, float], dict[str, float]]:
        with get_session(self._db_path) as session:
            rows = session.execute(select(PriceCache).where(
                PriceCache.ticker.in_(self._tickers), PriceCache.date == day
            )).scalars().all()
        return ({r.ticker: r.open for r in rows}, {r.ticker: r.close for r in rows})

    def _set_status(self, status: str) -> None:
        session = get_session(self._db_path)
        try:
            run = session.execute(select(SimRun).where(SimRun.id == self._id)).scalar_one()
            run.status = status
            session.commit()
        finally:
            session.close()

    def _set_progress(self, day: int) -> None:
        session = get_session(self._db_path)
        try:
            run = session.execute(select(SimRun).where(SimRun.id == self._id)).scalar_one()
            run.current_day = day
            session.commit()
        finally:
            session.close()

    def _save_nav_snapshot(
        self, session: Session, cycle_date: str, nav: float, cash: float, equity: float
    ) -> None:
        try:
            snap = SimNavSnapshot(
                sim_run_id=self._id,
                cycle_date=cycle_date,
                nav=nav,
                cash=cash,
                equity=equity,
            )
            session.add(snap)
            session.commit()
        finally:
            session.close()

    def _save_trades(self, session: Session, trades: list[dict]) -> None:
        try:
            for t in trades:
                sim_trade = SimTradeLog(
                    sim_run_id=self._id,
                    ticker=t.get("ticker", ""),
                    side=t.get("side", "BUY"),
                    quantity=t.get("quantity", 0),
                    price=t.get("price", 0.0),
                    fee=t.get("fee", 0.0),
                    total_amount=t.get("total_amount", 0.0),
                    cycle_date=t.get("cycle_date", ""),
                )
                session.add(sim_trade)
            session.commit()
        finally:
            session.close()

    def _finish(self, days: list[str]) -> None:
        final_session = get_session(self._db_path)
        try:
            run2 = final_session.execute(select(SimRun).where(SimRun.id == self._id)).scalar_one()
            nav_row = final_session.execute(
                select(SimNavSnapshot.nav)
                .where(SimNavSnapshot.sim_run_id == self._id)
                .order_by(SimNavSnapshot.cycle_date.desc())
                .limit(1)
            ).scalar_one_or_none()
            run2.final_nav = float(nav_row) if nav_row else self._capital
            run2.status = "completed"
            run2.current_day = len(days)
            run2.completed_at = datetime.now(timezone.utc).isoformat()
            final_session.commit()
        finally:
            final_session.close()

        logger.info("sim %d complete: final nav $%.2f", self._id, run2.final_nav)

    def _fail(self, message: str) -> None:
        with get_session(self._db_path) as session:
            run = session.execute(select(SimRun).where(SimRun.id == self._id)).scalar_one()
            run.status = "failed"
            run.error_message = message[:4000]
            run.completed_at = datetime.now(timezone.utc).isoformat()
            session.commit()


def get_sim_status(sim_id: int, db_path: str) -> dict | None:
    init_db(db_path)
    session = get_session(db_path)
    try:
        run = session.execute(select(SimRun).where(SimRun.id == sim_id)).scalar_one_or_none()
        if run is None:
            return None
        return {
            "id": run.id,
            "status": run.status,
            "current_day": run.current_day,
            "total_days": run.total_days,
            "final_nav": run.final_nav,
            "error_message": run.error_message,
            "completed_at": run.completed_at,
            "warnings": json.loads(run.warnings or "[]"),
            "models": json.loads(run.models or "[]"),
        }
    finally:
        session.close()


def get_sim_result(sim_id: int, db_path: str) -> dict | None:
    init_db(db_path)
    session = get_session(db_path)
    try:
        run = session.execute(select(SimRun).where(SimRun.id == sim_id)).scalar_one_or_none()
        if run is None:
            return None

        nav_rows = (
            session.execute(
                select(SimNavSnapshot)
                .where(SimNavSnapshot.sim_run_id == sim_id)
                .order_by(SimNavSnapshot.cycle_date.asc())
            )
            .scalars()
            .all()
        )

        trade_rows = (
            session.execute(
                select(SimTradeLog)
                .where(SimTradeLog.sim_run_id == sim_id)
                .order_by(SimTradeLog.cycle_date.asc())
            )
            .scalars()
            .all()
        )

        nav_curve = [
            {"date": n.cycle_date, "nav": n.nav, "cash": n.cash, "equity": n.equity}
            for n in nav_rows
        ]

        trades = [
            {
                "id": t.id,
                "date": t.cycle_date,
                "ticker": t.ticker,
                "side": t.side,
                "quantity": t.quantity,
                "price": t.price,
                "fee": t.fee,
                "total_amount": t.total_amount,
            }
            for t in trade_rows
        ]

        initial_nav = run.initial_capital
        final_nav = run.final_nav or initial_nav
        total_return = (final_nav - initial_nav) / initial_nav

        nav_values = [n.nav for n in nav_rows]
        peak = initial_nav
        max_drawdown = 0.0
        for v in nav_values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd

        returns = []
        for i in range(1, len(nav_values)):
            if nav_values[i - 1] > 0:
                returns.append((nav_values[i] - nav_values[i - 1]) / nav_values[i - 1])
        sharpe = 0.0
        if returns:
            mean_ret = sum(returns) / len(returns)
            variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
            if variance > 0:
                sharpe = (mean_ret / (variance ** 0.5)) * (252 ** 0.5)

        buy_count = sum(1 for t in trade_rows if t.side == "BUY")
        sell_count = sum(1 for t in trade_rows if t.side == "SELL")

        return {
            "id": run.id,
            "name": run.name,
            "tickers": json.loads(run.tickers),
            "start_date": run.start_date,
            "end_date": run.end_date,
            "initial_capital": run.initial_capital,
            "final_nav": round(final_nav, 2),
            "total_return_pct": round(total_return * 100, 2),
            "max_drawdown_pct": round(max_drawdown * 100, 2),
            "sharpe_ratio": round(sharpe, 4),
            "nav_curve": nav_curve,
            "trades": trades,
            "trade_count": len(trades),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "total_days": run.total_days,
            "status": run.status,
            "error_message": run.error_message,
            "completed_at": run.completed_at,
            "warnings": json.loads(run.warnings or "[]"),
            "models": json.loads(run.models or "[]"),
        }
    finally:
        session.close()


def list_sim_runs(db_path: str) -> list[dict]:
    init_db(db_path)
    session = get_session(db_path)
    try:
        rows = session.execute(
            select(SimRun).order_by(SimRun.created_at.desc()).limit(50)
        ).scalars().all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "tickers": json.loads(r.tickers),
                "start_date": r.start_date,
                "end_date": r.end_date,
                "initial_capital": r.initial_capital,
                "status": r.status,
                "current_day": r.current_day,
                "total_days": r.total_days,
                "final_nav": r.final_nav,
                "created_at": r.created_at,
                "completed_at": r.completed_at,
                "error_message": r.error_message,
                "warnings": json.loads(r.warnings or "[]"),
                "models": json.loads(r.models or "[]"),
            }
            for r in rows
        ]
    finally:
        session.close()
