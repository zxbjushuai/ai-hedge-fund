"""SEC filing metadata used to replace estimated fundamental filing dates."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date
from typing import Callable

import httpx

logger = logging.getLogger(__name__)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_FORMS = frozenset({"10-Q", "10-K", "20-F"})
_DEFAULT_TOLERANCE_DAYS = 7


@dataclass(frozen=True)
class SecFiling:
    form: str
    report_period: str
    filing_date: str
    filing_datetime: str | None
    accession_number: str | None


def _fetch_json(url: str) -> dict:
    headers = {
        "User-Agent": os.getenv(
            "AIHF_SEC_USER_AGENT",
            "aihf-research/1.0 admin@example.invalid",
        ),
        "Accept": "application/json",
    }
    with httpx.Client(timeout=20.0, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


class SecFilingClient:
    """Resolve recent SEC periodic-filing report and acceptance dates."""

    def __init__(self, *, fetch_json: Callable[[str], dict] | None = None) -> None:
        self._fetch_json = fetch_json or _fetch_json
        self._cik_by_ticker: dict[str, int] | None = None

    def get_filings(self, ticker: str) -> list[SecFiling]:
        cik = self._ticker_to_cik(ticker)
        if cik is None:
            return []
        payload = self._fetch_json(_SUBMISSIONS_URL.format(cik=cik))
        recent = (payload.get("filings") or {}).get("recent") or {}
        fields = ("form", "filingDate", "acceptanceDateTime", "reportDate", "accessionNumber")
        columns = [recent.get(name) or [] for name in fields]
        filings: list[SecFiling] = []
        for form, filed, accepted, report, accession in zip(*columns):
            if form not in _FORMS:
                continue
            filing_date = _date_part(filed) or _date_part(accepted)
            report_period = _date_part(report)
            if not filing_date or not report_period:
                continue
            filings.append(
                SecFiling(
                    form=form,
                    report_period=report_period,
                    filing_date=filing_date,
                    filing_datetime=accepted or None,
                    accession_number=accession or None,
                )
            )
        return filings

    def _ticker_to_cik(self, ticker: str) -> int | None:
        symbol = ticker.strip().upper()
        if self._cik_by_ticker is None:
            payload = self._fetch_json(_TICKERS_URL)
            self._cik_by_ticker = {str(row.get("ticker", "")).upper(): int(row["cik_str"]) for row in payload.values() if row.get("ticker") and row.get("cik_str") is not None}
        cik = self._cik_by_ticker.get(symbol)
        if cik is None:
            logger.info("SEC ticker map has no CIK for %s; keeping estimated filing dates", symbol)
        return cik


def resolve_filing_dates(
    report_periods: list[str] | tuple[str, ...],
    filings: list[SecFiling],
    *,
    tolerance_days: int = _DEFAULT_TOLERANCE_DAYS,
) -> dict[str, SecFiling]:
    """Return the nearest safe SEC filing for each fiscal report period."""
    resolved: dict[str, SecFiling] = {}
    for report_period in report_periods:
        try:
            period = date.fromisoformat(report_period[:10])
        except ValueError:
            continue
        candidates = []
        for filing in filings:
            try:
                delta = abs((date.fromisoformat(filing.report_period) - period).days)
            except ValueError:
                continue
            if delta <= tolerance_days:
                candidates.append((delta, filing.filing_date, filing))
        if candidates:
            resolved[report_period] = min(candidates, key=lambda item: (item[0], item[1]))[2]
    return resolved


def _date_part(value) -> str | None:
    if not value:
        return None
    text = str(value)
    return text[:10] if len(text) >= 10 else None
