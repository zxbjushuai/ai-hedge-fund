"""YFinance data client — free Yahoo Finance data source.

Implements the DataClient protocol (hedge_fund/data/protocol.py) so it can
be used wherever FDClient is used. Provides best-effort mapping from
yfinance data to the existing pydantic models.

Usage::

    with YFinanceClient() as client:
        prices = client.get_prices("AAPL", "2024-01-01", "2024-12-31")
"""

from __future__ import annotations

import logging
import time
from datetime import date as _date
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from hedge_fund.data.errors import NoDataError, classify_market_error
from hedge_fund.data.models import (
    CompanyFacts,
    CompanyNews,
    Earnings,
    EarningsData,
    EarningsRecord,
    FinancialMetrics,
    InsiderTrade,
    Price,
)
from hedge_fund.data.earnings import surprise_direction
from hedge_fund.data.protocol import DataClient

logger = logging.getLogger(__name__)

_RETRY_DELAYS = (0.5, 1.0, 2.0)


def _fmt_date(col_date) -> str | None:
    """Convert a pandas Timestamp/Period/str to 'YYYY-MM-DD'."""
    if col_date is None:
        return None
    if hasattr(col_date, "strftime"):
        return col_date.strftime("%Y-%m-%d")
    return str(col_date)[:10]


def _safe_float(val) -> float | None:
    """Convert to float, returning None for NaN/Inf/None."""
    if val is None:
        return None
    try:
        v = float(val)
        if pd.isna(v) or not _isfinite(v):
            return None
        return v
    except (ValueError, TypeError):
        return None


def _isfinite(v: float) -> bool:
    """True if v is finite (not NaN, not Inf)."""
    from math import isfinite as _isf
    return _isf(v)


def _val_at(series_or_none, key: str):
    """Safely get a value from a pandas Series by label."""
    if series_or_none is None:
        return None
    try:
        return series_or_none.get(key)
    except (KeyError, AttributeError):
        return None


def _match_column(df, target_date):
    """Return the closest column (Series) in df to target_date, or None."""
    if df is None or df.empty:
        return None
    try:
        ts = pd.Timestamp(target_date)
        diffs = [(abs((pd.Timestamp(c) - ts).days), c) for c in df.columns]
        diffs.sort()
        closest = diffs[0][1]
        return df[closest]
    except Exception:
        return None


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / abs(previous), 4)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _times(value: float | None, multiplier: float) -> float | None:
    return None if value is None else value * multiplier


def _retry(func, *args, **kwargs):
    """Call func with retries on rate-limited errors."""
    for attempt, delay in enumerate(_RETRY_DELAYS + (0,)):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            msg = str(e).lower()
            if ("rate limit" in msg or "too many" in msg) and delay > 0:
                logger.info("yfinance rate limited, retrying in %.1fs (attempt %d)", delay, attempt + 1)
                time.sleep(delay)
                continue
            raise
    return func(*args, **kwargs)


class YFinanceClient:
    """Free Yahoo Finance data provider implementing the DataClient protocol."""

    def __enter__(self) -> YFinanceClient:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def close(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Prices
    # ------------------------------------------------------------------

    @staticmethod
    def _prices_from_frame(df, ticker: str) -> list[Price]:
        prices: list[Price] = []
        if df is None or df.empty:
            return prices
        for idx, row in df.iterrows():
            required = [_safe_float(row.get(name)) for name in ("Open", "Close", "High", "Low")]
            if any(value is None for value in required):
                continue
            prices.append(Price(
                open=required[0], close=required[1], high=required[2], low=required[3],
                volume=int(_safe_float(row.get("Volume")) or 0), time=str(idx.isoformat() if hasattr(idx, "isoformat") else idx),
                adjusted_close=_safe_float(row.get("Adj Close")),
                dividend=_safe_float(row.get("Dividends")) or 0.0,
                split_ratio=_safe_float(row.get("Stock Splits")) or 0.0,
                source="yahoo", price_mode="raw",
            ))
        return prices

    def get_prices_batch(self, tickers: list[str], start_date: str, end_date: str) -> dict[str, list[Price]]:
        """Download a Yahoo batch once; callers retry missing members individually."""
        normalized = list(dict.fromkeys(ticker.strip().upper() for ticker in tickers if ticker.strip()))
        if not normalized:
            return {}
        inclusive_end = (datetime.strptime(end_date[:10], "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            frame = _retry(lambda: yf.download(
                tickers=normalized, start=start_date, end=inclusive_end, interval="1d",
                group_by="ticker", auto_adjust=False, back_adjust=False, actions=True,
                threads=min(8, len(normalized)), progress=False, timeout=30,
            ))
            result: dict[str, list[Price]] = {}
            if len(normalized) == 1 and not isinstance(frame.columns, pd.MultiIndex):
                result[normalized[0]] = self._prices_from_frame(frame, normalized[0])
            else:
                for ticker in normalized:
                    try:
                        ticker_frame = frame[ticker]
                    except (KeyError, TypeError):
                        ticker_frame = pd.DataFrame()
                    result[ticker] = self._prices_from_frame(ticker_frame, ticker)
            return result
        except Exception as exc:
            raise classify_market_error(exc) from exc

    def get_prices(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        interval: str = "1d",
        interval_multiplier: int = 1,
        **kwargs,
    ) -> list[Price]:
        """Fetch OHLCV price bars from Yahoo Finance."""
        try:
            stock = yf.Ticker(ticker)
            # yfinance treats ``end`` as exclusive while DataClient uses an
            # inclusive date range.
            inclusive_end = (
                datetime.strptime(end_date[:10], "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")
            df = _retry(lambda: stock.history(
                start=start_date,
                end=inclusive_end,
                interval=interval,
                auto_adjust=False,
                back_adjust=False,
                actions=True,
                timeout=30,
            ))
            if df is None or df.empty:
                raise NoDataError(f"Yahoo returned no prices for {ticker}")
            return self._prices_from_frame(df, ticker)
        except Exception as e:
            logger.warning("yfinance get_prices(%s) failed: %s", ticker, e)
            raise classify_market_error(e) from e

    # ------------------------------------------------------------------
    # Financial Metrics
    # ------------------------------------------------------------------

    def get_financial_metrics(
        self,
        ticker: str,
        end_date: str,
        period: str = "ttm",
        limit: int = 10,
    ) -> list[FinancialMetrics]:
        """Build historical financial metrics from yfinance quarterly statements.

        Uses quarterly_financials + balance_sheet + cashflow DataFrames
        to construct one FinancialMetrics row per historical quarter.
        Falls back to stock.info snapshot if no historical data available.
        """
        try:
            stock = yf.Ticker(ticker)
            info = _retry(lambda: stock.info) or {}

            qf = _retry(lambda: stock.quarterly_financials)
            bs = _retry(lambda: stock.quarterly_balance_sheet)
            cf = _retry(lambda: stock.quarterly_cashflow)

            if qf is None or qf.empty:
                return self._fallback_metrics(ticker, end_date, period, info)

            results: list[FinancialMetrics] = []

            col_dates = list(qf.columns[:limit])

            for i, col_date in enumerate(col_dates):
                rp = _fmt_date(col_date)
                if rp is None:
                    continue

                row = qf.iloc[:, i] if qf.shape[1] > i else None
                if row is None:
                    continue

                revenue = _safe_float(_val_at(row, "Total Revenue"))
                net_income = _safe_float(_val_at(row, "Net Income"))
                gross_profit = _safe_float(_val_at(row, "Gross Profit"))
                op_income = _safe_float(_val_at(row, "Operating Income"))
                ebitda = _safe_float(_val_at(row, "EBITDA"))
                eps_diluted = _safe_float(_val_at(row, "Diluted EPS"))

                bs_match = _match_column(bs, col_date) if bs is not None and not bs.empty else None
                total_assets = _safe_float(_val_at(bs_match, "Total Assets"))
                total_debt = _safe_float(_val_at(bs_match, "Total Debt"))
                equity = _safe_float(_val_at(bs_match, "Stockholders Equity"))
                current_assets = _safe_float(_val_at(bs_match, "Current Assets"))
                current_liabilities = _safe_float(_val_at(bs_match, "Current Liabilities"))
                shares = (
                    _safe_float(_val_at(bs_match, "Ordinary Shares Number"))
                    or _safe_float(_val_at(bs_match, "Share Issued"))
                    or _safe_float(_val_at(row, "Diluted Average Shares"))
                )

                cf_match = _match_column(cf, col_date) if cf is not None and not cf.empty else None
                fcf = _safe_float(_val_at(cf_match, "Free Cash Flow"))
                ocf = _safe_float(_val_at(cf_match, "Operating Cash Flow"))

                prev_row = qf.iloc[:, i + 4] if i + 4 < qf.shape[1] else None
                prev_revenue = _safe_float(_val_at(prev_row, "Total Revenue"))
                prev_net_income = _safe_float(_val_at(prev_row, "Net Income"))

                revenue_growth = _growth(revenue, prev_revenue)
                earnings_growth = _growth(net_income, prev_net_income)
                gross_margin = _ratio(gross_profit, revenue)
                op_margin = _ratio(op_income, revenue)
                net_margin = _ratio(net_income, revenue)
                roe_annual = _ratio(_times(net_income, 4), equity)
                debt_to_equity = _ratio(total_debt, equity)
                current_ratio = _ratio(current_assets, current_liabilities)
                bvps = _ratio(equity, shares)
                fcf_per_share = _ratio(fcf, shares)

                results.append(
                    FinancialMetrics(
                        ticker=ticker,
                        report_period=rp,
                        period=period,
                        currency=info.get("currency"),
                        filing_date=(datetime.strptime(rp, "%Y-%m-%d") + timedelta(days=45)).strftime("%Y-%m-%d"),
                        shares_outstanding=shares,
                        gross_margin=gross_margin,
                        operating_margin=op_margin,
                        net_margin=net_margin,
                        return_on_equity=roe_annual,
                        return_on_assets=_ratio(_times(net_income, 4), total_assets),
                        current_ratio=current_ratio,
                        debt_to_equity=debt_to_equity,
                        revenue_growth=revenue_growth,
                        earnings_growth=earnings_growth,
                        earnings_per_share=eps_diluted,
                        book_value_per_share=bvps,
                        free_cash_flow_per_share=fcf_per_share,
                    )
                )

            results.reverse()
            return results

        except Exception as e:
            logger.warning("yfinance get_financial_metrics(%s) failed: %s", ticker, e)
            raise classify_market_error(e) from e

    def _fallback_metrics(
        self, ticker: str, end_date: str, period: str, info: dict
    ) -> list[FinancialMetrics]:
        """Fallback: single snapshot from stock.info."""
        if not info:
            return []
        return [
            FinancialMetrics(
                ticker=ticker,
                report_period=end_date,
                period=period,
                currency=info.get("currency"),
                filing_date=end_date,
                market_cap=info.get("marketCap"),
                enterprise_value=info.get("enterpriseValue"),
                price_to_earnings_ratio=info.get("trailingPE"),
                price_to_book_ratio=info.get("priceToBook"),
                price_to_sales_ratio=info.get("priceToSalesTrailing12Months"),
                enterprise_value_to_ebitda_ratio=info.get("enterpriseToEbitda"),
                enterprise_value_to_revenue_ratio=info.get("enterpriseToRevenue"),
                free_cash_flow_yield=info.get("freeCashflow"),
                peg_ratio=info.get("pegRatio"),
                gross_margin=info.get("grossMargins"),
                operating_margin=info.get("operatingMargins"),
                net_margin=info.get("profitMargins"),
                return_on_equity=info.get("returnOnEquity"),
                return_on_assets=info.get("returnOnAssets"),
                return_on_invested_capital=info.get("returnOnCapital"),
                current_ratio=info.get("currentRatio"),
                quick_ratio=info.get("quickRatio"),
                debt_to_equity=info.get("debtToEquity"),
                revenue_growth=info.get("revenueGrowth"),
                earnings_growth=info.get("earningsGrowth"),
                earnings_per_share_growth=info.get("earningsQuarterlyGrowth"),
                earnings_per_share=info.get("trailingEps"),
                book_value_per_share=info.get("bookValue"),
                free_cash_flow_per_share=info.get("freeCashflow"),
                payout_ratio=info.get("payoutRatio"),
                operating_cash_flow_ratio=info.get("operatingCashflow"),
            )
        ]

    # ------------------------------------------------------------------
    # Company Facts
    # ------------------------------------------------------------------

    def get_company_facts(self, ticker: str) -> CompanyFacts | None:
        """Fetch company metadata from yfinance info."""
        try:
            stock = yf.Ticker(ticker)
            info = _retry(lambda: stock.info) or {}
            if not info:
                return None
            return CompanyFacts(
                ticker=ticker,
                is_active=True,
                name=info.get("longName") or info.get("shortName"),
                sector=info.get("sector"),
                industry=info.get("industry"),
                exchange=info.get("exchange"),
                location=info.get("country"),
                category=info.get("industry"),
            )
        except Exception as e:
            logger.warning("yfinance get_company_facts(%s) failed: %s", ticker, e)
            return None

    # ------------------------------------------------------------------
    # News — not available from yfinance
    # ------------------------------------------------------------------

    def get_news(
        self,
        ticker: str,
        end_date: str,
        start_date: str | None = None,
        limit: int = 1000,
    ) -> list[CompanyNews]:
        """yfinance does not provide news access."""
        return []

    # ------------------------------------------------------------------
    # Insider Trades — not available from yfinance
    # ------------------------------------------------------------------

    def get_insider_trades(
        self,
        ticker: str,
        end_date: str,
        start_date: str | None = None,
        limit: int = 1000,
    ) -> list[InsiderTrade]:
        """yfinance does not provide insider trades."""
        return []

    # ------------------------------------------------------------------
    # Earnings
    # ------------------------------------------------------------------

    def get_earnings(self, ticker: str) -> Earnings | None:
        """Fetch latest earnings data from yfinance."""
        try:
            stock = yf.Ticker(ticker)
            info = _retry(lambda: stock.info) or {}

            quarterly_data = EarningsData(
                revenue=info.get("totalRevenue"),
                earnings_per_share=info.get("trailingEps"),
                net_income=info.get("netIncomeToCommon"),
                gross_profit=info.get("grossProfits"),
                operating_income=info.get("operatingIncome"),
                free_cash_flow=info.get("freeCashflow"),
                total_debt=info.get("totalDebt"),
                total_assets=info.get("totalAssets"),
                total_liabilities=info.get("totalLiabilitiesGrossMinorityInterest"),
                shareholders_equity=info.get("shareholdersEquity"),
            )

            today = _date.today().isoformat()
            return Earnings(
                ticker=ticker,
                report_period=today,
                fiscal_period="FY",
                currency=info.get("currency"),
                quarterly=quarterly_data,
            )
        except Exception as e:
            logger.warning("yfinance get_earnings(%s) failed: %s", ticker, e)
            return None

    def get_earnings_history(
        self,
        ticker: str,
        limit: int = 12,
    ) -> list[EarningsRecord]:
        """Fetch historical earnings filings."""
        try:
            stock = yf.Ticker(ticker)
            info = {}
            dates_error: Exception | None = None

            try:
                dates = _retry(lambda: stock.get_earnings_dates(limit=limit))
                if dates is not None and not dates.empty:
                    records = []
                    for idx, row in dates.iterrows():
                        announced = _fmt_date(idx)
                        actual = _safe_float(row.get("Reported EPS"))
                        estimate = _safe_float(row.get("EPS Estimate"))
                        surprise = _safe_float(row.get("Surprise(%)"))
                        if announced and actual is not None:
                            records.append(EarningsRecord(
                                ticker=ticker, report_period=announced,
                                source_type="earnings", filing_date=announced,
                                quarterly=EarningsData(
                                    earnings_per_share=actual,
                                    estimated_earnings_per_share=estimate,
                                    eps_surprise=surprise_direction(surprise),
                                    eps_surprise_percent=surprise,
                                ),
                            ))
                    return records
            except Exception as exc:
                dates_error = exc
                logger.warning(
                    "yfinance get_earnings_dates(%s) failed; PEAD may be unavailable: %s",
                    ticker,
                    exc,
                )

            def _empty_earnings_data() -> EarningsData:
                return EarningsData()

            records: list[EarningsRecord] = []

            try:
                quarterly_financials = stock.quarterly_financials
                if quarterly_financials is not None and not quarterly_financials.empty:
                    for col_date in quarterly_financials.columns[:limit]:
                        filing_date = col_date
                        if hasattr(filing_date, "strftime"):
                            filing_date = filing_date.strftime("%Y-%m-%d")

                        qtr = _empty_earnings_data()
                        if "Total Revenue" in quarterly_financials.index:
                            qtr.revenue = float(quarterly_financials.loc["Total Revenue", col_date])
                        if "Net Income" in quarterly_financials.index:
                            qtr.net_income = float(quarterly_financials.loc["Net Income", col_date])
                        if "Gross Profit" in quarterly_financials.index:
                            qtr.gross_profit = float(quarterly_financials.loc["Gross Profit", col_date])

                        records.append(
                            EarningsRecord(
                                ticker=ticker,
                                report_period=filing_date,
                                source_type="10-Q",
                                filing_date=filing_date,
                                fiscal_period=quarterly_financials.columns.name or "Q",
                                currency=info.get("currency"),
                                quarterly=qtr,
                            )
                        )
            except Exception as exc:
                if dates_error is None:
                    dates_error = exc

            if not records and dates_error is not None:
                raise classify_market_error(dates_error) from dates_error
            return records
        except Exception as e:
            logger.warning("yfinance get_earnings_history(%s) failed: %s", ticker, e)
            raise classify_market_error(e) from e

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def get_market_cap(self, ticker: str, end_date: str) -> float | None:
        """Return market cap from yfinance info."""
        try:
            stock = yf.Ticker(ticker)
            info = stock.info or {}
            return info.get("marketCap")
        except Exception:
            return None
