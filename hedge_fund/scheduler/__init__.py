"""Scheduler — periodic run_cycle execution backed by PersistentBroker."""

from __future__ import annotations

import logging
from datetime import date as _date
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from hedge_fund.brokers import PersistentBroker
from hedge_fund.data import CachedDataClient, FDClient, YFinanceClient
from hedge_fund.fund import Fund, load_spec
from hedge_fund.pipeline import run_cycle

logger = logging.getLogger(__name__)


class FundDaemon:
    """Runs run_cycle on a configurable schedule, persisting all state to SQLite.

    Usage::

        daemon = FundDaemon(
            fund_path="hedge_fund/fund/example.yaml",
            db_path="fund.db",
            interval="daily",
            time="16:00",
            fee_rate=0.001,
        )
        daemon.start()
    """

    def __init__(
        self,
        fund_path: str,
        db_path: str = "fund.db",
        interval: str = "daily",
        time: str = "16:00",
        fee_rate: float = 0.001,
    ) -> None:
        spec_path = Path(fund_path)
        if not spec_path.exists():
            raise FileNotFoundError(f"fund spec not found: {fund_path}")

        self._spec = load_spec(fund_path)
        self._db_path = db_path
        self._fee_rate = fee_rate
        self._scheduler = BackgroundScheduler()

        if interval == "daily":
            hour, minute = map(int, time.split(":"))
            trigger = CronTrigger(hour=hour, minute=minute)
        elif interval == "hourly":
            trigger = IntervalTrigger(hours=1)
        elif interval == "manual":
            return  # no automatic trigger
        else:
            raise ValueError(f"unknown interval: {interval}")

        self._scheduler.add_job(
            self.run_cycle,
            trigger=trigger,
            id="fund_cycle",
            name="Run fund cycle",
        )
        logger.info(
            "scheduler configured: interval=%s time=%s fund=%s",
            interval, time, fund_path,
        )

    def start(self) -> None:
        """Start the background scheduler."""
        logger.info("starting fund daemon...")
        self._scheduler.start()
        logger.info("fund daemon started")

    def stop(self) -> None:
        """Stop the background scheduler."""
        self._scheduler.shutdown(wait=False)
        logger.info("fund daemon stopped")

    def run_cycle(self) -> dict:
        """Run one cycle and persist results. Also callable manually."""
        import os

        today = _date.today().isoformat()
        fund = Fund(self._spec)
        broker = PersistentBroker(
            cash=self._spec.capital,
            db_path=self._db_path,
            fee_rate=self._fee_rate,
        )

        logger.info("running cycle for %s as of %s", self._spec.name, today)

        raw = _get_data_client()
        fd = CachedDataClient(raw)
        record = run_cycle(fund, today, broker, fd)
        broker.save_nav_snapshot(nav=record.nav, marks=record.marks, cycle_date=today)

        logger.info(
            "cycle complete: nav=$%s cash=$%s orders=%d positions=%d",
            f"{record.nav:,.2f}",
            f"{record.cash:,.0f}",
            len(record.orders),
            len(record.positions),
        )

        return {
            "nav": record.nav,
            "cash": record.cash,
            "orders": len(record.orders),
            "positions": len(record.positions),
            "as_of": record.as_of,
        }

    def run_now(self) -> dict:
        """Run one cycle immediately (for manual trigger)."""
        return self.run_cycle()

    @property
    def spec(self):
        return self._spec

    @property
    def db_path(self) -> str:
        return self._db_path

    @property
    def is_running(self) -> bool:
        return self._scheduler.running


def _get_data_client():
    """Return the best available data client, preferring FD but falling back to YFinance."""
    import os

    fd_key = os.getenv("FINANCIAL_DATASETS_API_KEY", "")
    has_fd = fd_key and fd_key not in ("your-financial-datasets-api-key", "")
    if has_fd:
        try:
            client = FDClient()
            prices = client.get_prices("AAPL", "2024-01-01", "2024-01-05")
            if prices:
                logger.info("using Financial Datasets API")
                return client
            logger.info("FD API returned empty, falling back to YFinance")
        except Exception as e:
            logger.info("FD API unavailable (%s), falling back to YFinance", e)
    logger.info("using YFinance (free)")
    return YFinanceClient()
