"""Market-level data adapters. Data-source choice stays private to each market."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from enum import StrEnum
from io import StringIO
from typing import Protocol

import httpx

from v2.data.errors import MarketDataParseError, UnsupportedMarketError
from v2.data.models import EarningsRecord, FinancialMetrics, Price
from v2.data.yfinance_client import YFinanceClient


class Market(StrEnum):
    US = "US"
    HK = "HK"
    CN = "CN"


@dataclass(frozen=True)
class CatalogSecurity:
    market: str
    symbol: str
    data_symbol: str
    name: str
    exchange: str
    asset_type: str
    currency: str = "USD"
    is_test: bool = False
    selectable: bool = True


class MarketDataAdapter(Protocol):
    market: Market

    def sync_catalog(self) -> list[CatalogSecurity]:
        ...

    def get_prices(
        self, ticker: str, start_date: str, end_date: str
    ) -> list[Price]:
        ...

    def get_prices_batch(
        self, tickers: list[str], start_date: str, end_date: str
    ) -> dict[str, list[Price]]:
        ...

    def get_financial_metrics(
        self, ticker: str, end_date: str, limit: int = 40
    ) -> list[FinancialMetrics]:
        ...

    def get_earnings_history(
        self, ticker: str, limit: int = 40
    ) -> list[EarningsRecord]:
        ...


_NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
_OTHER_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
_EXCHANGES = {"A": "NYSE American", "N": "NYSE", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}
_NON_SELECTABLE = (" warrant", " warrants", " right", " rights", " unit", " units")


def yahoo_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-")


def _asset_type(name: str, is_etf: bool) -> tuple[str, bool]:
    lowered = f" {name.lower()} "
    if is_etf:
        return "etf", True
    if any(term in lowered for term in _NON_SELECTABLE):
        return "other", False
    return "equity", True


def _rows(text: str) -> list[dict[str, str]]:
    records = []
    for row in csv.DictReader(StringIO(text), delimiter="|"):
        if not row or next(iter(row.values()), "").startswith("File Creation Time"):
            continue
        records.append({str(k): str(v or "").strip() for k, v in row.items() if k is not None})
    return records


def parse_nasdaq_catalog(nasdaq_text: str, other_text: str) -> list[CatalogSecurity]:
    result: dict[str, CatalogSecurity] = {}
    try:
        for row in _rows(nasdaq_text):
            symbol = row.get("Symbol", "").upper()
            if not symbol:
                continue
            test = row.get("Test Issue", "N") == "Y"
            kind, selectable = _asset_type(row.get("Security Name", symbol), row.get("ETF", "N") == "Y")
            result[symbol] = CatalogSecurity(
                market="US", symbol=symbol, data_symbol=yahoo_symbol(symbol),
                name=row.get("Security Name", symbol), exchange="NASDAQ",
                asset_type=kind, is_test=test, selectable=selectable and not test,
            )
        for row in _rows(other_text):
            symbol = row.get("ACT Symbol", "").upper()
            if not symbol:
                continue
            test = row.get("Test Issue", "N") == "Y"
            kind, selectable = _asset_type(row.get("Security Name", symbol), row.get("ETF", "N") == "Y")
            result[symbol] = CatalogSecurity(
                market="US", symbol=symbol, data_symbol=yahoo_symbol(row.get("NASDAQ Symbol") or symbol),
                name=row.get("Security Name", symbol), exchange=_EXCHANGES.get(row.get("Exchange", ""), row.get("Exchange", "")),
                asset_type=kind, is_test=test, selectable=selectable and not test,
            )
    except Exception as exc:
        raise MarketDataParseError("could not parse Nasdaq Trader security directory") from exc
    if not result:
        raise MarketDataParseError("Nasdaq Trader security directory was empty")
    return sorted(result.values(), key=lambda item: item.symbol)


class USMarketDataAdapter:
    market = Market.US

    def __init__(self, client: YFinanceClient | None = None) -> None:
        self.client = client or YFinanceClient()

    def sync_catalog(self) -> list[CatalogSecurity]:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            nasdaq = client.get(_NASDAQ_URL)
            other = client.get(_OTHER_URL)
            nasdaq.raise_for_status()
            other.raise_for_status()
        return parse_nasdaq_catalog(nasdaq.text, other.text)

    def get_prices(self, ticker: str, start_date: str, end_date: str) -> list[Price]:
        return self.client.get_prices(yahoo_symbol(ticker), start_date, end_date)

    def get_prices_batch(self, tickers: list[str], start_date: str, end_date: str) -> dict[str, list[Price]]:
        mapped = {ticker: yahoo_symbol(ticker) for ticker in tickers}
        result = self.client.get_prices_batch(list(mapped.values()), start_date, end_date)
        return {ticker: result.get(data_symbol, []) for ticker, data_symbol in mapped.items()}

    def get_financial_metrics(self, ticker: str, end_date: str, limit: int = 40) -> list[FinancialMetrics]:
        return self.client.get_financial_metrics(yahoo_symbol(ticker), end_date, limit=limit)

    def get_earnings_history(self, ticker: str, limit: int = 40) -> list[EarningsRecord]:
        return self.client.get_earnings_history(yahoo_symbol(ticker), limit=limit)


class HKMarketDataAdapter:
    market = Market.HK

    def __getattribute__(self, name: str):
        if name.startswith("get_") or name == "sync_catalog":
            # TODO(workstream-5): define HKEX catalog, HKD normalization, and calendar.
            raise UnsupportedMarketError("Hong Kong market data is not implemented")
        return super().__getattribute__(name)


class CNMarketDataAdapter:
    market = Market.CN

    def __getattribute__(self, name: str):
        if name.startswith("get_") or name == "sync_catalog":
            # TODO(workstream-5): define SSE/SZSE catalog, CNY normalization, and calendar.
            raise UnsupportedMarketError("mainland China market data is not implemented")
        return super().__getattribute__(name)


def adapter_for_market(market: str | Market) -> MarketDataAdapter:
    value = Market(str(market).upper())
    if value == Market.US:
        return USMarketDataAdapter()
    if value == Market.HK:
        return HKMarketDataAdapter()
    return CNMarketDataAdapter()
