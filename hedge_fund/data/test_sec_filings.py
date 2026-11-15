from __future__ import annotations

from hedge_fund.data.market import USMarketDataAdapter
from hedge_fund.data.models import FinancialMetrics
from hedge_fund.data.sec_filings import resolve_filing_dates, SecFiling, SecFilingClient


class FakeFilingClient:
    def __init__(self, filings):
        self.filings = filings

    def get_filings(self, ticker):
        return self.filings


class FakeYFinance:
    def __init__(self, metrics):
        self.metrics = metrics

    def get_financial_metrics(self, ticker, end_date, limit=40):
        return [metric.model_copy(deep=True) for metric in self.metrics]


def test_sec_client_filters_forms_and_exposes_acceptance_metadata():
    calls = []

    def fetch_json(url):
        calls.append(url)
        if url.endswith("company_tickers.json"):
            return {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
        return {
            "filings": {
                "recent": {
                    "form": ["10-Q", "8-K", "10-K", "10-Q/A"],
                    "filingDate": ["2024-05-03", "2024-05-02", "2024-11-01", "2024-05-04"],
                    "acceptanceDateTime": [
                        "2024-05-03T16:01:02.000Z",
                        "2024-05-02T20:30:00.000Z",
                        "2024-11-01T16:01:02.000Z",
                        "2024-05-04T12:00:00.000Z",
                    ],
                    "reportDate": ["2024-03-30", "2024-05-02", "2024-09-28", "2024-03-30"],
                    "accessionNumber": ["a", "b", "c", "d"],
                }
            }
        }

    filings = SecFilingClient(fetch_json=fetch_json).get_filings("AAPL")

    assert calls == [
        "https://www.sec.gov/files/company_tickers.json",
        "https://data.sec.gov/submissions/CIK0000320193.json",
    ]
    assert filings == [
        SecFiling("10-Q", "2024-03-30", "2024-05-03", "2024-05-03T16:01:02.000Z", "a"),
        SecFiling("10-K", "2024-09-28", "2024-11-01", "2024-11-01T16:01:02.000Z", "c"),
    ]


def test_resolve_filing_dates_uses_nearest_safe_report_date():
    filings = [
        SecFiling("10-Q", "2024-03-15", "2024-05-01", None, "distant"),
        SecFiling("10-Q", "2024-03-29", "2024-05-03", None, "near"),
        SecFiling("10-K", "2024-09-28", "2024-11-01", None, "annual"),
    ]

    resolved = resolve_filing_dates(["2024-03-31", "2024-06-30"], filings)

    assert resolved["2024-03-31"].accession_number == "near"
    assert "2024-06-30" not in resolved


def test_us_adapter_enriches_only_matching_metrics_and_keeps_estimate_fallback():
    metrics = [
        FinancialMetrics(
            ticker="AAPL",
            report_period="2024-03-31",
            period="ttm",
            filing_date="2024-05-15",
            filing_date_source="estimated_45d",
        ),
        FinancialMetrics(
            ticker="AAPL",
            report_period="2024-06-30",
            period="ttm",
            filing_date="2024-08-14",
            filing_date_source="estimated_45d",
        ),
    ]
    filings = [
        SecFiling(
            "10-Q",
            "2024-03-30",
            "2024-05-03",
            "2024-05-03T16:01:02.000Z",
            "a",
        )
    ]
    adapter = USMarketDataAdapter(
        client=FakeYFinance(metrics),
        filing_client=FakeFilingClient(filings),
    )

    rows = adapter.get_financial_metrics("AAPL", "2024-07-01")

    assert rows[0].filing_date == "2024-05-03"
    assert rows[0].filing_datetime == "2024-05-03T16:01:02.000Z"
    assert rows[0].filing_date_source == "sec_submissions"
    assert rows[1].filing_date == "2024-08-14"
    assert rows[1].filing_date_source == "estimated_45d"


def test_us_adapter_keeps_metrics_when_sec_lookup_fails():
    metric = FinancialMetrics(
        ticker="AAPL",
        report_period="2024-03-31",
        period="ttm",
        filing_date="2024-05-15",
        filing_date_source="estimated_45d",
    )

    class BrokenFilingClient:
        def get_filings(self, ticker):
            raise RuntimeError("SEC unavailable")

    adapter = USMarketDataAdapter(
        client=FakeYFinance([metric]),
        filing_client=BrokenFilingClient(),
    )

    rows = adapter.get_financial_metrics("AAPL", "2024-07-01")

    assert rows[0].filing_date == "2024-05-15"
    assert rows[0].filing_date_source == "estimated_45d"
