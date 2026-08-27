"""MockDataClient — reads from SQLite cache tables instead of live APIs.

Implements the DataClient protocol so it can be used wherever FDClient or
YFinanceClient would be used. Data comes from price_cache and metrics_cache
tables populated by the fetch-cache flow (dashboard routes).
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select

from v2.data.models import (
    CompanyFacts,
    CompanyNews,
    Earnings,
    EarningsData,
    EarningsRecord,
    FinancialMetrics,
    InsiderTrade,
    Price,
)
from v2.data.protocol import DataClient
from v2.persistence.database import get_session, init_db
from v2.persistence.models import EarningsCache, MetricsCache as _MetricsCacheRow, PriceCache

logger = logging.getLogger(__name__)


class MockDataClient:
    """Data client backed by the local SQLite cache tables.

    Point-in-time filtering: metrics with filing_date > end_date are excluded.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        init_db(db_path)

    def _new_session(self):
        return get_session(self._db_path)

    # ------------------------------------------------------------------
    # Prices
    # ------------------------------------------------------------------

    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        interval: str = "1d",
        interval_multiplier: int = 1,
        **kwargs,
    ) -> list[Price]:
        session = self._new_session()
        try:
            stmt = (
                select(PriceCache)
                .where(PriceCache.ticker == ticker.upper())
                .where(PriceCache.date >= start_date)
                .where(PriceCache.date <= end_date)
                .order_by(PriceCache.date.asc())
            )
            rows = session.execute(stmt).scalars().all()
            return [
                Price(
                    open=row.open,
                    close=row.close,
                    high=row.high,
                    low=row.low,
                    volume=row.volume,
                    time=row.date + "T00:00:00",
                )
                for row in rows
            ]
        except Exception as e:
            logger.warning("MockDataClient.get_prices(%s) failed: %s", ticker, e)
            return []
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Financial Metrics (point-in-time)
    # ------------------------------------------------------------------

    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        period: str = "ttm",
        limit: int = 20,
    ) -> list[FinancialMetrics]:
        session = self._new_session()
        try:
            stmt = (
                select(_MetricsCacheRow)
                .where(_MetricsCacheRow.ticker == ticker.upper())
                .where(_MetricsCacheRow.filing_date <= end_date)
                .order_by(_MetricsCacheRow.report_period.desc())
                .limit(limit)
            )
            rows = session.execute(stmt).scalars().all()

            results: list[FinancialMetrics] = []
            for row in rows:
                try:
                    d = json.loads(row.data)
                    d.update({
                        "ticker": row.ticker,
                        "report_period": row.report_period,
                        "filing_date": row.filing_date or row.report_period,
                    })
                    fm = FinancialMetrics(**d)
                    results.append(fm)
                except Exception as exc:
                    logger.warning("invalid cached metrics row %s: %s", row.id, exc)
                    continue
                if len(results) >= limit:
                    break
            self._add_filing_date_valuation(session, ticker, end_date, results)
            return results
        except Exception as e:
            logger.warning("MockDataClient.get_financial_metrics(%s) failed: %s", ticker, e)
            return []
        finally:
            session.close()

    @staticmethod
    def _add_filing_date_valuation(session, ticker: str, end_date: str, metrics: list[FinancialMetrics]) -> None:
        """Value the latest visible filing at its own point-in-time close.

        The quarterly LLM prompt must remain stable between filings.  Daily
        market valuation belongs to the event/quant layer, not to the filed
        fundamentals prompt.
        """
        if not metrics:
            return
        latest = metrics[0]
        valuation_date = min(end_date[:10], (latest.filing_date or end_date)[:10])
        price = session.execute(
            select(PriceCache.close)
            .where(PriceCache.ticker == ticker.upper(), PriceCache.date <= valuation_date)
            .order_by(PriceCache.date.desc())
            .limit(1)
        ).scalar_one_or_none()
        if price is None:
            return
        if latest.shares_outstanding and latest.shares_outstanding > 0:
            latest.market_cap = price * latest.shares_outstanding
        if latest.book_value_per_share and latest.book_value_per_share > 0:
            latest.price_to_book_ratio = price / latest.book_value_per_share
        ttm_eps = sum(
            metric.earnings_per_share
            for metric in metrics[:4]
            if metric.earnings_per_share is not None
        )
        if ttm_eps > 0:
            latest.price_to_earnings_ratio = price / ttm_eps

    # ------------------------------------------------------------------
    # Company Facts
    # ------------------------------------------------------------------

    def get_company_facts(self, ticker: str) -> CompanyFacts | None:
        session = self._new_session()
        try:
            stmt = (
                select(_MetricsCacheRow)
                .where(_MetricsCacheRow.ticker == ticker.upper())
                .order_by(_MetricsCacheRow.report_period.desc())
                .limit(1)
            )
            row = session.execute(stmt).scalar_one_or_none()
            if row is None:
                return None
            d = json.loads(row.data)
            return CompanyFacts(
                ticker=ticker.upper(),
                is_active=True,
                name=d.get("ticker"),
                sector=None,
                industry=None,
            )
        except Exception:
            return None
        finally:
            session.close()

    # ------------------------------------------------------------------
    # News, Insider Trades, Earnings — not needed for simulation
    # ------------------------------------------------------------------

    def get_news(self, ticker: str, end_date: str, start_date: str | None = None, limit: int = 1000) -> list[CompanyNews]:
        return []

    def get_insider_trades(self, ticker: str, end_date: str, start_date: str | None = None, limit: int = 1000) -> list[InsiderTrade]:
        return []

    def get_earnings(self, ticker: str) -> Earnings | None:
        return None

    def get_earnings_history(self, ticker: str, limit: int = 12, end_date: str | None = None) -> list[EarningsRecord]:
        with self._new_session() as session:
            stmt = select(EarningsCache).where(EarningsCache.ticker == ticker.upper())
            if end_date:
                stmt = stmt.where(EarningsCache.announcement_date <= end_date)
            rows = session.execute(stmt.order_by(EarningsCache.announcement_date.desc()).limit(limit)).scalars().all()
            return [EarningsRecord(
                ticker=r.ticker, report_period=r.report_period, source_type="earnings",
                filing_date=r.announcement_date, filing_datetime=r.announcement_date,
                quarterly=EarningsData(
                    earnings_per_share=r.actual_eps,
                    estimated_earnings_per_share=r.estimated_eps,
                    eps_surprise=("BEAT" if (r.surprise_pct or 0) > 0 else "MISS" if (r.surprise_pct or 0) < 0 else None),
                    eps_surprise_percent=r.surprise_pct,
                ),
            ) for r in rows]

    def get_market_cap(self, ticker: str, end_date: str) -> float | None:
        return None

    def close(self) -> None:
        pass
