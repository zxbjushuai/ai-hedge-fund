"""Simulation runner — run_cycle day-by-day over cached historical data."""

from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from v2.brokers import SimBroker
from v2.data.mock_client import MockDataClient
from v2.failures import classify_cycle_failure
from v2.fund import Fund, PersonaRefreshPolicy, load_spec, normalize_universe
from v2.llm import LLMClient
from v2.persistence.database import get_session, init_db
from v2.persistence.models import (
    EarningsCache, MetricsCache, PriceCache, SimCycleRecord,
    SimNavSnapshot, SimRun, SimTradeLog,
)
from v2.pipeline import run_cycle
from v2.simulation.audit import persist_completed_cycle, persist_failed_cycle
from v2.simulation.persona_state import PersonaSignalEngine

logger = logging.getLogger(__name__)

_RUNNERS: dict[int, "SimRunner"] = {}
_LOCK = threading.Lock()


def _benchmark_closes(
    db_path: str, benchmark: str, start: str, end: str,
) -> dict[str, float]:
    """Cached benchmark closes in date order for the requested window."""
    with get_session(db_path) as session:
        rows = session.execute(
            select(PriceCache.date, PriceCache.close).where(
                PriceCache.ticker == benchmark.upper(),
                PriceCache.date >= start, PriceCache.date <= end,
            )
            .order_by(PriceCache.date)
        ).all()
    return {date: float(close) for date, close in rows if close > 0}


def _trading_days(db_path: str, benchmark: str, start: str, end: str) -> list[str]:
    """Actual market days defined exclusively by cached benchmark bars."""
    return list(_benchmark_closes(db_path, benchmark, start, end))


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


def estimate_persona_event_schedule(
    db_path: str,
    tickers: list[str],
    trading_days: list[str],
    persona_names: set[str],
    policy: PersonaRefreshPolicy,
) -> dict:
    """Replay a cold-cache, successful-refresh event timeline from SQLite."""
    reason_counts = {
        reason: 0 for reason in (
            "bootstrap", "new_filing", "actionable_earnings",
            "valuation_change", "max_age", "universe_entry",
        )
    }
    signal_days = trading_days[:-1]
    if not signal_days or not persona_names:
        return {
            "estimated_llm_calls": 0,
            "estimated_refresh_events": 0,
            "persona_count": len(persona_names),
            "event_reason_counts": reason_counts,
        }

    refresh_events = 0
    with get_session(db_path) as session:
        for ticker in sorted(set(t.upper() for t in tickers)):
            price_rows = session.execute(
                select(PriceCache.date, PriceCache.close).where(
                    PriceCache.ticker == ticker,
                    PriceCache.date >= (
                        date.fromisoformat(signal_days[0]) - timedelta(days=7)
                    ).isoformat(),
                    PriceCache.date <= signal_days[-1],
                ).order_by(PriceCache.date)
            ).all()
            metric_rows = session.execute(
                select(MetricsCache.id, MetricsCache.filing_date).where(
                    MetricsCache.ticker == ticker,
                    MetricsCache.filing_date <= signal_days[-1],
                ).order_by(MetricsCache.filing_date, MetricsCache.id)
            ).all()
            earnings_rows = session.execute(
                select(EarningsCache.announcement_date).where(
                    EarningsCache.ticker == ticker,
                    EarningsCache.announcement_date <= signal_days[-1],
                    EarningsCache.surprise_pct.is_not(None),
                    EarningsCache.surprise_pct != 0,
                ).order_by(EarningsCache.announcement_date)
            ).scalars().all()

            source_date: str | None = None
            anchor: float | None = None
            filing_marker: tuple | None = None
            earnings_marker: str | None = None
            for day_index, signal_day in enumerate(signal_days):
                cutoff = date.fromisoformat(signal_day) - timedelta(days=7)
                prices = [
                    (row_date, float(close)) for row_date, close in price_rows
                    if cutoff.isoformat() <= row_date <= signal_day and close > 0
                ]
                visible_metrics = [row for row in metric_rows if row.filing_date <= signal_day]
                if not prices or len(visible_metrics) < 4:
                    continue
                current_close = prices[-1][1]
                current_filing = tuple(row.id for row in visible_metrics[-20:])
                visible_earnings = [value for value in earnings_rows if value <= signal_day]
                current_earnings = visible_earnings[-1] if visible_earnings else None
                reasons: list[str] = []
                if source_date is None:
                    reasons.append("bootstrap" if day_index == 0 else "universe_entry")
                    if current_earnings:
                        reasons.append("actionable_earnings")
                else:
                    # Keep this estimate aligned with PersonaSignalEngine.  The cached
                    # filing marker currently uses estimated_45d dates.
                    # TODO(event-driven-persona): replay authoritative filing dates
                    # once the cache stores source-aware filing timestamps.
                    if filing_marker != current_filing:
                        reasons.append("new_filing")
                    if current_earnings and current_earnings != earnings_marker:
                        reasons.append("actionable_earnings")
                    if (
                        anchor
                        and abs((current_close / anchor - 1) * 100) + 1e-9
                        >= policy.valuation_change_pct
                    ):
                        reasons.append("valuation_change")
                    if (
                        date.fromisoformat(signal_day) - date.fromisoformat(source_date)
                    ).days >= policy.max_age_days:
                        reasons.append("max_age")
                if not reasons:
                    continue
                refresh_events += 1
                for reason in reasons:
                    reason_counts[reason] += 1
                source_date = signal_day
                anchor = current_close
                filing_marker = current_filing
                earnings_marker = current_earnings

    return {
        "estimated_llm_calls": refresh_events * len(persona_names),
        "estimated_refresh_events": refresh_events,
        "persona_count": len(persona_names),
        "event_reason_counts": reason_counts,
    }


def validate_cached_data(
    db_path: str,
    tickers: list[str],
    benchmark: str,
    start: str,
    end: str,
    require_earnings: bool = True,
) -> tuple[list[str], list[str]]:
    """Fail-fast point-in-time coverage validation shared by API and runner."""
    days = _trading_days(db_path, benchmark, start, end)
    errors: list[str] = []
    warnings: list[str] = []
    if len(days) < 2:
        errors.append(
            f"{benchmark}: benchmark cache must cover at least two trading days; "
            "fetch benchmark prices in Data Cache first"
        )
    tickers_with_prices = 0
    with get_session(db_path) as session:
        for ticker in tickers:
            ticker_days = session.query(PriceCache).filter(
                PriceCache.ticker == ticker, PriceCache.date >= start, PriceCache.date <= end
            ).count()
            if ticker_days == 0:
                warnings.append(
                    f"{ticker}: no cached prices in requested range; ticker will be skipped"
                )
            else:
                tickers_with_prices += 1
            visible_metrics = session.query(MetricsCache).filter(
                MetricsCache.ticker == ticker, MetricsCache.filing_date <= start
            ).count()
            if visible_metrics < 4:
                warnings.append(
                    f"{ticker}: fewer than four visible quarterly metrics at start "
                    f"(found {visible_metrics}); persona models will abstain until eligible"
                )
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
    if tickers_with_prices == 0:
        errors.append("no universe ticker has cached prices in the requested range")
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
        benchmark: str,
        db_path: str,
        fund_spec_path: str,
        llm: LLMClient | None = None,
        fee_rate: float = 0.001,
    ) -> None:
        self._id = sim_run_id
        self._tickers = tickers
        self._start = start_date
        self._end = end_date
        self._capital = initial_capital
        self._benchmark = benchmark
        self._db_path = db_path
        self._fund_spec_path = fund_spec_path
        self._llm = llm
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
        benchmark: str = "SPY",
        name: str = "",
        fee_rate: float = 0.001,
        llm: LLMClient | None = None,
        llm_provider: str | None = None,
        llm_protocol: str | None = None,
        llm_model: str | None = None,
        llm_connection_id: int | None = None,
        llm_connection_name: str | None = None,
        llm_base_url: str | None = None,
    ) -> int:
        """Create a SimRun row and return its id. Call start() to run."""
        init_db(db_path)
        configured_policy = (
            load_spec(fund_spec_path).persona_refresh
            if Path(fund_spec_path).exists() else PersonaRefreshPolicy()
        )
        tickers = normalize_universe(tickers)
        benchmark = benchmark.strip().upper()
        if not benchmark:
            raise ValueError("benchmark is empty")
        if llm is not None:
            client_protocol = getattr(llm, "protocol", None)
            if llm_provider is not None and llm_provider != llm.provider:
                raise ValueError("persisted LLM provider does not match the injected client")
            if (
                llm_protocol is not None
                and client_protocol is not None
                and llm_protocol != client_protocol
            ):
                raise ValueError("persisted LLM protocol does not match the injected client")
            if llm_model is not None and llm_model != llm.model:
                raise ValueError("persisted LLM model does not match the injected client")
            llm_provider, llm_protocol, llm_model = (
                llm.provider,
                client_protocol or llm_protocol,
                llm.model,
            )
        session = get_session(db_path)
        try:
            days = _trading_days(db_path, benchmark, start_date, end_date)
            if len(days) < 2:
                raise ValueError(
                    f"{benchmark}: benchmark cache must cover at least two trading days"
                )
            run = SimRun(
                name=name,
                tickers=json.dumps(tickers),
                benchmark=benchmark,
                llm_provider=llm_provider,
                llm_protocol=llm_protocol,
                llm_model=llm_model,
                llm_connection_id=llm_connection_id,
                llm_connection_name=llm_connection_name,
                llm_base_url=llm_base_url,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                status="pending",
                total_days=len(days),
                persona_refresh_policy=configured_policy.model_dump_json(),
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
                benchmark=benchmark,
                db_path=db_path,
                fund_spec_path=fund_spec_path,
                llm=llm,
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
            spec = spec.model_copy(deep=True, update={"capital": self._capital})
            require_earnings = any(m.name == "pead" for s in spec.strategies for m in s.models)
            errors, warnings = validate_cached_data(
                self._db_path, self._tickers, self._benchmark,
                self._start, self._end, require_earnings,
            )
            if errors:
                raise ValueError("; ".join(errors))
            warnings.extend(disable_unavailable_models(spec, self._db_path, self._tickers, self._end))
            enabled_models = [m.name for s in spec.strategies for m in s.models]
            logger.info(
                "sim %d started: tickers=%s range=%s..%s capital=%.2f llm=%s models=%s warnings=%s",
                self._id, self._tickers, self._start, self._end, self._capital,
                self._llm.identity if self._llm is not None else "none",
                enabled_models, warnings,
            )
            with get_session(self._db_path) as session:
                run = session.execute(select(SimRun).where(SimRun.id == self._id)).scalar_one()
                run.warnings = json.dumps(warnings)
                run.models = json.dumps(enabled_models)
                run.persona_refresh_policy = spec.persona_refresh.model_dump_json()
                session.commit()
            benchmark_closes = _benchmark_closes(
                self._db_path, self._benchmark, self._start, self._end,
            )
            days = list(benchmark_closes)
            data_client = MockDataClient(self._db_path)
            broker = SimBroker(cash=self._capital, fee_rate=self._fee_rate)
            fund = Fund(spec, llm=self._llm)  # one immutable client for this run
            persona_engine = PersonaSignalEngine(spec.persona_refresh)
            benchmark_base = benchmark_closes[days[0]]
            self._save_nav_snapshot(
                get_session(self._db_path), days[0], self._capital,
                self._capital, 0.0, self._capital,
            )
            self._set_progress(1)
            for i, day in enumerate(days[1:], start=1):
                signal_day = days[i - 1]
                opens, closes = self._prices_for_day(day)
                try:
                    persona_engine.begin_cycle(i)
                    record = run_cycle(
                        fund, signal_day, broker, data_client,
                        execution_prices=opens, valuation_prices=closes, execution_date=day,
                        universe=self._tickers,
                        persona_engine=persona_engine,
                    )
                except Exception as exc:
                    try:
                        persist_failed_cycle(
                            self._db_path,
                            self._id,
                            i,
                            signal_day,
                            day,
                            self._tickers,
                            exc,
                        )
                    except Exception:
                        logger.exception("could not persist failed cycle audit for sim %s", self._id)
                    raise

                benchmark_nav = (
                    self._capital * benchmark_closes[day] / benchmark_base
                )

                persist_completed_cycle(
                    self._db_path, self._id, i, record, benchmark_nav,
                )
                if record.fills:
                    logger.info(
                        "sim %d trades on %s: count=%d nav=%.2f cash=%.2f",
                        self._id, day, len(record.fills), record.nav, record.cash,
                    )
                broker._last_trades = []
                self._set_progress(i + 1)
            self._finish(days)
        except Exception as exc:
            logger.exception("simulation %s failed", self._id)
            self._fail(classify_cycle_failure(exc).message)

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
        self,
        session: Session,
        cycle_date: str,
        nav: float,
        cash: float,
        equity: float,
        benchmark_nav: float,
    ) -> None:
        try:
            snap = SimNavSnapshot(
                sim_run_id=self._id,
                cycle_date=cycle_date,
                nav=nav,
                cash=cash,
                equity=equity,
                benchmark_nav=benchmark_nav,
            )
            session.add(snap)
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
            "provider": run.llm_provider,
            "protocol": run.llm_protocol,
            "model": run.llm_model,
            "llm_connection_id": run.llm_connection_id,
            "llm_connection_name": run.llm_connection_name,
            "llm_base_url": run.llm_base_url,
            "error_message": run.error_message,
            "completed_at": run.completed_at,
            "warnings": json.loads(run.warnings or "[]"),
            "models": json.loads(run.models or "[]"),
            "persona_refresh_policy": (
                json.loads(run.persona_refresh_policy)
                if run.persona_refresh_policy else None
            ),
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
            {
                "date": n.cycle_date,
                "nav": n.nav,
                "cash": n.cash,
                "equity": n.equity,
                "benchmark_nav": n.benchmark_nav,
            }
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
        benchmark_values = [n.benchmark_nav for n in nav_rows]
        has_benchmark_curve = bool(benchmark_values) and all(
            value is not None for value in benchmark_values
        )
        benchmark_return = (
            float(benchmark_values[-1]) / initial_nav - 1
            if has_benchmark_curve else None
        )
        excess_return = (
            total_return - benchmark_return
            if benchmark_return is not None else None
        )

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
        audit_available = session.scalar(
            select(SimCycleRecord.id)
            .where(SimCycleRecord.sim_run_id == sim_id)
            .limit(1)
        ) is not None

        return {
            "id": run.id,
            "name": run.name,
            "tickers": json.loads(run.tickers),
            "start_date": run.start_date,
            "end_date": run.end_date,
            "initial_capital": run.initial_capital,
            "benchmark": run.benchmark,
            "provider": run.llm_provider,
            "protocol": run.llm_protocol,
            "model": run.llm_model,
            "llm_connection_id": run.llm_connection_id,
            "llm_connection_name": run.llm_connection_name,
            "llm_base_url": run.llm_base_url,
            "final_nav": round(final_nav, 2),
            "total_return_pct": round(total_return * 100, 2),
            "benchmark_return_pct": (
                round(benchmark_return * 100, 2)
                if benchmark_return is not None else None
            ),
            "excess_return_pct": (
                round(excess_return * 100, 2)
                if excess_return is not None else None
            ),
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
            "audit_available": audit_available,
            "persona_refresh_policy": (
                json.loads(run.persona_refresh_policy)
                if run.persona_refresh_policy else None
            ),
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
                "benchmark": r.benchmark,
                "provider": r.llm_provider,
                "protocol": r.llm_protocol,
                "model": r.llm_model,
                "llm_connection_id": r.llm_connection_id,
                "llm_connection_name": r.llm_connection_name,
                "llm_base_url": r.llm_base_url,
                "status": r.status,
                "current_day": r.current_day,
                "total_days": r.total_days,
                "final_nav": r.final_nav,
                "created_at": r.created_at,
                "completed_at": r.completed_at,
                "error_message": r.error_message,
                "warnings": json.loads(r.warnings or "[]"),
                "models": json.loads(r.models or "[]"),
                "persona_refresh_policy": (
                    json.loads(r.persona_refresh_policy)
                    if r.persona_refresh_policy else None
                ),
            }
            for r in rows
        ]
    finally:
        session.close()
