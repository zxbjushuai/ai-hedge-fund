"""Deterministic, point-in-time price momentum alpha model."""

from __future__ import annotations

from datetime import date as _date
from datetime import timedelta

from hedge_fund.data.protocol import DataClient
from hedge_fund.models import Signal
from hedge_fund.signals.base import QuantModel


class PriceMomentumModel(QuantModel):
    """Map a trailing close-to-close return into a bounded conviction."""

    def __init__(self, lookback_days: int = 20, full_signal_return: float = 0.10) -> None:
        if lookback_days < 2:
            raise ValueError("lookback_days must be at least 2")
        if full_signal_return <= 0:
            raise ValueError("full_signal_return must be positive")
        self._lookback_days = lookback_days
        self._full_signal_return = full_signal_return

    @property
    def name(self) -> str:
        return "price_momentum"

    def predict(self, ticker: str, date: str, data_client: DataClient) -> Signal:
        start = (_date.fromisoformat(date) - timedelta(days=self._lookback_days * 2 + 10)).isoformat()
        bars = sorted(
            (p for p in data_client.get_prices(ticker, start, date) if p.time[:10] <= date),
            key=lambda p: p.time,
        )
        if len(bars) < self._lookback_days + 1:
            return Signal(
                model_name=self.name,
                ticker=ticker,
                date=date,
                value=0.0,
                reasoning=f"need {self._lookback_days + 1} closes; found {len(bars)}",
            )

        first = bars[-(self._lookback_days + 1)].close
        last = bars[-1].close
        if first <= 0:
            return Signal(model_name=self.name, ticker=ticker, date=date, value=0.0)

        trailing_return = last / first - 1.0
        conviction = self._normalize_to_signal(trailing_return / self._full_signal_return)
        return Signal(
            model_name=self.name,
            ticker=ticker,
            date=date,
            value=conviction,
            reasoning=(
                f"{self._lookback_days}-day price return {trailing_return:+.2%}; "
                f"scaled to {conviction:+.2f} conviction"
            ),
            components={"trailing_return": trailing_return},
        )
