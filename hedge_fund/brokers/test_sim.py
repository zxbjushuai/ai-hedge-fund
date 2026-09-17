"""SimBroker tests — deterministic fills and bookkeeping."""

import pytest

from hedge_fund.brokers.models import Order
from hedge_fund.brokers.sim import SimBroker


def test_buy_updates_cash_and_position():
    broker = SimBroker(cash=10_000.0, fee_rate=0.0)
    fill = broker.place_order(Order(ticker="AAPL", side="buy", quantity=10, price=100.0))
    assert broker.cash() == pytest.approx(9_000.0)
    assert broker.positions()["AAPL"].shares == 10
    assert fill.quantity == 10
    assert fill.price == 100.0
    assert fill.fee == 0.0


def test_sell_updates_cash_and_position():
    broker = SimBroker(cash=0.0, fee_rate=0.0)
    broker.place_order(Order(ticker="AAPL", side="buy", quantity=10, price=100.0))
    broker.place_order(Order(ticker="AAPL", side="sell", quantity=4, price=110.0))
    assert broker.positions()["AAPL"].shares == 6
    assert broker.cash() == pytest.approx(-1_000.0 + 440.0)


def test_split_and_dividend_apply_before_new_orders():
    broker = SimBroker(cash=1_000, fee_rate=0)
    broker.place_order(Order(ticker="AAA", side="buy", quantity=3, price=100))
    split = broker.apply_split("AAA", 1.5, 70)
    assert broker.positions()["AAA"].shares == 4
    assert split == {
        "ticker": "AAA", "action_type": "split", "value": 1.5,
        "shares_before": 3, "shares_after": 4, "cash_amount": 35,
    }
    dividend = broker.apply_dividend("AAA", 2)
    assert dividend["cash_amount"] == 8
    assert broker.cash() == pytest.approx(743)


def test_position_removed_at_zero():
    broker = SimBroker(cash=1_000.0, fee_rate=0.0)
    broker.place_order(Order(ticker="AAPL", side="buy", quantity=5, price=100.0))
    broker.place_order(Order(ticker="AAPL", side="sell", quantity=5, price=100.0))
    assert broker.positions() == {}


def test_sell_past_zero_creates_short():
    broker = SimBroker(cash=0.0, fee_rate=0.0)
    broker.place_order(Order(ticker="AAPL", side="sell", quantity=3, price=100.0))
    assert broker.positions()["AAPL"].shares == -3
    assert broker.cash() == pytest.approx(300.0)


def test_nonpositive_price_raises():
    broker = SimBroker(cash=1_000.0, fee_rate=0.0)
    with pytest.raises(ValueError):
        broker.place_order(Order(ticker="AAPL", side="buy", quantity=1, price=0.0))


def test_positions_returns_a_copy():
    broker = SimBroker(cash=1_000.0, fee_rate=0.0)
    broker.place_order(Order(ticker="AAPL", side="buy", quantity=5, price=100.0))
    broker.positions().clear()
    assert broker.positions()["AAPL"].shares == 5


def test_buy_with_fee():
    broker = SimBroker(cash=10_000.0, fee_rate=0.001)
    fill = broker.place_order(Order(ticker="AAPL", side="buy", quantity=10, price=100.0))
    gross = 10 * 100.0
    expected_fee = gross * 0.001
    assert fill.fee == pytest.approx(expected_fee)
    assert fill.total_amount == pytest.approx(gross + expected_fee)
    assert broker.cash() == pytest.approx(10_000.0 - gross - expected_fee)


def test_sell_with_fee():
    broker = SimBroker(cash=0.0, fee_rate=0.001)
    fill = broker.place_order(Order(ticker="AAPL", side="sell", quantity=10, price=100.0))
    gross = 10 * 100.0
    expected_fee = gross * 0.001
    assert fill.fee == pytest.approx(expected_fee)
    assert fill.total_amount == pytest.approx(gross - expected_fee)
    assert broker.cash() == pytest.approx(gross - expected_fee)
