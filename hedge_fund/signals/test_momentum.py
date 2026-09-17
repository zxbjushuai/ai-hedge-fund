from __future__ import annotations

from datetime import date, timedelta

import pytest

from hedge_fund.data.models import Price
from hedge_fund.signals.momentum import PriceMomentumModel


class _Prices:
    def __init__(self, closes: list[float]) -> None:
        self._closes = closes

    def get_prices(self, ticker, start_date, end_date, **kwargs):
        first = date.fromisoformat(end_date) - timedelta(days=len(self._closes) - 1)
        return [
            Price(open=value, high=value, low=value, close=value, volume=1, time=(first + timedelta(days=i)).isoformat())
            for i, value in enumerate(self._closes)
        ]


def test_price_momentum_is_point_in_time_and_scaled():
    signal = PriceMomentumModel(lookback_days=2, full_signal_return=0.10).predict(
        "TEST", "2025-01-03", _Prices([100, 105, 110])
    )
    assert signal.value == pytest.approx(1.0)
    assert signal.components["trailing_return"] == pytest.approx(0.10)


def test_price_momentum_abstains_without_enough_bars():
    signal = PriceMomentumModel(lookback_days=20).predict(
        "TEST", "2025-01-03", _Prices([100, 101])
    )
    assert signal.value == 0.0
