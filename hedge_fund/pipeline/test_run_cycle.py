"""run_cycle end-to-end tests — fake data client + fake analysts + real SimBroker."""

from threading import Event

import pytest

from hedge_fund.brokers.sim import SimBroker
from hedge_fund.data.models import Price
from hedge_fund.fund.spec import Fund, FundSpec
from hedge_fund.models import Signal
from hedge_fund.pipeline.models import CycleRecord
from hedge_fund.pipeline.run_cycle import run_cycle
from hedge_fund.simulation.cancellation import SimulationCancelled


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeDataClient:
    """Canned closes per ticker; a ticker absent from `closes` has no bars."""

    def __init__(self, closes):
        self._closes = closes

    def get_prices(self, ticker, start_date, end_date, **kwargs):
        close = self._closes.get(ticker)
        if close is None:
            return []
        return [Price(open=close, close=close, high=close, low=close,
                      volume=1000, time=f"{end_date}T00:00:00Z")]


class FakeAnalyst:
    """Fixed conviction per ticker; counts predict calls."""

    def __init__(self, name, views=None, abstain=False, error=None):
        self._name = name
        self._views = views or {}
        self._abstain = abstain
        self._error = error
        self.predict_calls = []

    @property
    def name(self):
        return self._name

    def predict(self, ticker, date, data_client):
        self.predict_calls.append(ticker)
        if self._error is not None:
            raise self._error
        metadata = {"abstained": True} if self._abstain else {}
        value = 0.0 if self._abstain else self._views.get(ticker, 0.0)
        return Signal(model_name=self._name, ticker=ticker, date=date,
                      value=value, metadata=metadata)


class CancellingBroker(SimBroker):
    """Real fills, then requests cancellation before the cycle record is built."""

    def __init__(self, cancel_event, **kwargs):
        super().__init__(**kwargs)
        self.cancel_event = cancel_event

    def place_order(self, order, cycle_date=None):
        fill = super().place_order(order, cycle_date=cycle_date)
        self.cancel_event.set()
        return fill


def _spec(strategies=None, max_position_pct=0.25, universe=("AAPL", "MSFT", "NVDA")):
    if strategies is None:
        strategies = [{"name": "solo", "models": [{"name": "a"}]}]
    return FundSpec(
        name="test-fund",
        universe=list(universe),
        strategies=strategies,
        risk={"max_position_pct": max_position_pct, "max_gross_exposure": 1.0},
        capital=100_000.0,
    )


CLOSES = {"AAPL": 200.0, "MSFT": 400.0, "NVDA": 100.0}
# What to trade is a run-time argument, not a mandate field.
UNIVERSE = ["AAPL", "MSFT", "NVDA"]


@pytest.mark.parametrize('ratio', [2.0, 0.4, 1.5])
def test_split_sizing_preserves_equity_and_signal_marks(ratio):
    from hedge_fund.brokers.models import Order
    broker = SimBroker(cash=1010, fee_rate=0)
    broker.place_order(Order(ticker='AAPL', side='buy', quantity=101, price=10))
    execution_price = 10 / ratio
    broker.apply_split('AAPL', ratio, execution_price)
    fund = Fund(_spec(universe=('AAPL',), max_position_pct=1),
                models={'solo': [FakeAnalyst('a', {'AAPL': 1})]})
    record = run_cycle(fund, '2024-01-09', broker, FakeDataClient({'AAPL': 10}),
        execution_prices={'AAPL': execution_price},
        valuation_prices={'AAPL': execution_price}, execution_date='2024-01-10',
        sizing_split_ratios={'AAPL': ratio})
    assert record.marks == {'AAPL': 10}
    assert record.sizing_marks['AAPL'] == pytest.approx(execution_price)
    assert record.equity_before == pytest.approx(1010)
    assert record.nav == pytest.approx(1010)
    assert record.cash >= -1e-9
    assert not record.orders


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------

def test_full_cycle_record_is_consistent():
    spec = _spec(strategies=[
        {"name": "long", "models": [{"name": "a"}]},
        {"name": "short", "models": [{"name": "b"}]},
    ])
    fund = Fund(spec, models={
        "long": [FakeAnalyst("a", views={"AAPL": 1.0, "NVDA": 0.5})],
        "short": [FakeAnalyst("b", views={"MSFT": -1.0})],
    })
    broker = SimBroker(cash=100_000.0, fee_rate=0.0)

    record = run_cycle(fund, "2024-06-03", broker, FakeDataClient(CLOSES),
                       UNIVERSE)

    assert record.fund == "test-fund"
    assert record.equity_before == pytest.approx(100_000.0)
    assert len(record.strategies) == 2
    assert all(len(sr.signals) == 3 for sr in record.strategies)  # 3 tickers x 1 analyst
    # Weights respect the hard caps
    for w in record.final_weights.values():
        assert abs(w) <= 0.25 + 1e-12
    # Fills mirror orders one-to-one, and the books balance
    assert len(record.fills) == len(record.orders) > 0
    assert record.nav == pytest.approx(
        record.cash + sum(s * record.marks[t] for t, s in record.positions.items())
    )
    # The short strategy's bearish view -> short position
    assert record.positions["MSFT"] < 0


def test_cancel_after_fills_raises_before_cycle_record():
    cancel_event = Event()
    fund = Fund(
        _spec(universe=("AAPL",), max_position_pct=1.0),
        models={"solo": [FakeAnalyst("a", views={"AAPL": 1.0})]},
    )
    broker = CancellingBroker(cancel_event, cash=100_000.0, fee_rate=0.0)

    with pytest.raises(SimulationCancelled):
        run_cycle(
            fund, "2024-06-03", broker, FakeDataClient(CLOSES), ["AAPL"],
            cancel_event=cancel_event,
        )

    assert cancel_event.is_set()
    assert broker.positions()  # execution happened; the caller discards the book


def test_netting_math_two_strategies_unequal_slices():
    """Two sleeves, overlapping ticker, 3:1 slices — hand-computed netting."""
    spec = _spec(strategies=[
        {"name": "s1", "weight": 3.0, "models": [{"name": "a"}]},
        {"name": "s2", "weight": 1.0, "models": [{"name": "b"}]},
    ], max_position_pct=1.0)
    fund = Fund(spec, models={
        # s1 sleeve: AAPL 0.5, MSFT 0.5 (equal convictions, gross 1.0)
        "s1": [FakeAnalyst("a", views={"AAPL": 1.0, "MSFT": 1.0})],
        # s2 sleeve: MSFT -1.0 (only conviction takes full gross)
        "s2": [FakeAnalyst("b", views={"MSFT": -1.0})],
    })

    record = run_cycle(fund, "2024-06-03", SimBroker(cash=100_000.0, fee_rate=0.0),
                       FakeDataClient(CLOSES))

    s1, s2 = record.strategies
    assert s1.slice == pytest.approx(0.75)
    assert s2.slice == pytest.approx(0.25)
    assert s1.weights == {"AAPL": pytest.approx(0.5), "MSFT": pytest.approx(0.5),
                          "NVDA": 0.0}
    assert s2.weights["MSFT"] == pytest.approx(-1.0)
    # Netted: AAPL = .75*.5 = .375 ; MSFT = .75*.5 + .25*(-1) = .125
    assert record.target_weights["AAPL"] == pytest.approx(0.375)
    assert record.target_weights["MSFT"] == pytest.approx(0.125)


def test_slices_normalize():
    """weights 2/2 must mean exactly the same as 1/1."""
    def run(w1, w2):
        spec = _spec(strategies=[
            {"name": "s1", "weight": w1, "models": [{"name": "a"}]},
            {"name": "s2", "weight": w2, "models": [{"name": "b"}]},
        ])
        fund = Fund(spec, models={
            "s1": [FakeAnalyst("a", views={"AAPL": 1.0})],
            "s2": [FakeAnalyst("b", views={"NVDA": -0.5})],
        })
        return run_cycle(fund, "2024-06-03", SimBroker(cash=100_000.0, fee_rate=0.0),
                         FakeDataClient(CLOSES))

    assert run(2.0, 2.0).target_weights == run(1.0, 1.0).target_weights


def test_deterministic_and_json_round_trips():
    def make():
        spec = _spec()
        fund = Fund(spec, models={
            "solo": [FakeAnalyst("a", views={"AAPL": 1.0, "MSFT": -0.5})],
        })
        return run_cycle(fund, "2024-06-03", SimBroker(cash=100_000.0, fee_rate=0.0),
                         FakeDataClient(CLOSES))

    first, second = make(), make()
    assert first.model_dump_json() == second.model_dump_json()
    assert CycleRecord.model_validate_json(first.model_dump_json()) == first


def test_second_cycle_rebalances_not_restarts():
    analyst = FakeAnalyst("a", views={"AAPL": 1.0})
    fund = Fund(_spec(universe=["AAPL"], max_position_pct=1.0),
                models={"solo": [analyst]})
    broker = SimBroker(cash=100_000.0, fee_rate=0.0)
    data = FakeDataClient({"AAPL": 200.0})

    first = run_cycle(fund, "2024-06-03", broker, data, ["AAPL"])
    second = run_cycle(fund, "2024-06-04", broker, data, ["AAPL"])

    assert first.positions["AAPL"] == 500  # 100k at 200
    assert second.orders == []  # already at target; nothing to trade
    assert second.positions["AAPL"] == 500


# ---------------------------------------------------------------------------
# Abstain / flat behavior
# ---------------------------------------------------------------------------

def test_all_abstain_closes_the_book_to_flat():
    analyst = FakeAnalyst("a", views={"AAPL": 1.0})
    fund = Fund(_spec(universe=["AAPL"], max_position_pct=1.0),
                models={"solo": [analyst]})
    broker = SimBroker(cash=100_000.0, fee_rate=0.0)
    data = FakeDataClient({"AAPL": 200.0})
    run_cycle(fund, "2024-06-03", broker, data, ["AAPL"])
    assert broker.positions()["AAPL"].shares == 500

    analyst._abstain = True
    record = run_cycle(fund, "2024-06-04", broker, data, ["AAPL"])

    assert record.positions == {}  # book closed to flat
    assert record.nav == pytest.approx(100_000.0)  # flat closes at same price


# ---------------------------------------------------------------------------
# Pricing edge cases
# ---------------------------------------------------------------------------

def test_unpriced_unowned_ticker_skipped_and_analysts_never_called():
    analyst = FakeAnalyst("a", views={"AAPL": 1.0})
    fund = Fund(_spec(), models={"solo": [analyst]})
    closes = dict(CLOSES)
    del closes["NVDA"]

    record = run_cycle(fund, "2024-06-03", SimBroker(cash=100_000.0, fee_rate=0.0),
                       FakeDataClient(closes))

    assert [s.ticker for s in record.skipped] == ["NVDA"]
    assert "NVDA" not in analyst.predict_calls
    assert "NVDA" not in record.final_weights


def test_unpriced_held_ticker_raises():
    broker = SimBroker(cash=100_000.0, fee_rate=0.0)
    fund = Fund(_spec(), models={"solo": [FakeAnalyst("a", views={"AAPL": 1.0})]})
    run_cycle(fund, "2024-06-03", broker, FakeDataClient(CLOSES), UNIVERSE)
    assert broker.positions()  # something is held

    closes = {t: c for t, c in CLOSES.items() if t not in broker.positions()}
    with pytest.raises(ValueError, match="cannot value the book"):
        run_cycle(fund, "2024-06-04", broker, FakeDataClient(closes), UNIVERSE)


def test_universe_is_a_run_time_argument():
    """The same fund, pointed at different names, trades different names —
    and the record says what it was asked to trade."""
    fund = Fund(_spec(max_position_pct=1.0), models={
        "solo": [FakeAnalyst("a", views={"AAPL": 1.0, "MSFT": 1.0})],
    })

    record = run_cycle(fund, "2024-06-03", SimBroker(cash=100_000.0),
                       FakeDataClient(CLOSES), ["aapl", "AAPL"])

    assert record.universe == ["AAPL"]  # upper-cased and de-duped
    assert "MSFT" not in record.final_weights


def test_empty_universe_raises():
    fund = Fund(_spec(), models={"solo": [FakeAnalyst("a")]})
    with pytest.raises(ValueError, match="universe is empty"):
        run_cycle(fund, "2024-06-03", SimBroker(cash=100_000.0),
                  FakeDataClient(CLOSES), [])


def test_runtime_universe_takes_precedence_without_mutating_spec():
    spec = _spec(universe=["AAPL", "MSFT"])
    analyst = FakeAnalyst("a", views={"NVDA": 1.0})
    fund = Fund(spec, models={"solo": [analyst]})

    record = run_cycle(
        fund, "2024-06-03", SimBroker(cash=100_000.0, fee_rate=0.0),
        FakeDataClient(CLOSES), universe=[" nvda ", "NVDA"],
    )

    assert record.universe == ["NVDA"]
    assert analyst.predict_calls == ["NVDA"]
    assert spec.universe == ["AAPL", "MSFT"]


def test_missing_execution_open_skips_only_that_ticker():
    analyst = FakeAnalyst("a", views={"AAPL": 1.0, "MSFT": 1.0})
    fund = Fund(_spec(universe=["AAPL", "MSFT"], max_position_pct=1.0),
                models={"solo": [analyst]})
    record = run_cycle(
        fund, "2024-06-03", SimBroker(cash=100_000.0, fee_rate=0.0),
        FakeDataClient(CLOSES),
        execution_prices={"AAPL": 201.0},
        valuation_prices={"AAPL": 202.0},
        execution_date="2024-06-04",
    )

    assert {order.ticker for order in record.orders} == {"AAPL"}
    assert any(skip.ticker == "MSFT" and "no execution open" in skip.reason
               for skip in record.skipped)


def test_empty_execution_map_never_falls_back_to_signal_marks():
    fund = Fund(_spec(universe=["AAPL"], max_position_pct=1.0), models={
        "solo": [FakeAnalyst("a", views={"AAPL": 1.0})],
    })
    record = run_cycle(
        fund, "2024-06-03", SimBroker(cash=100_000.0, fee_rate=0.0),
        FakeDataClient(CLOSES), execution_prices={}, valuation_prices={},
        execution_date="2024-06-04",
    )
    assert record.orders == []
    assert record.positions == {}


def test_explicit_empty_valuation_map_fails_for_held_position():
    fund = Fund(_spec(universe=["AAPL"], max_position_pct=1.0), models={
        "solo": [FakeAnalyst("a", views={"AAPL": 1.0})],
    })
    broker = SimBroker(cash=100_000.0, fee_rate=0.0)
    run_cycle(fund, "2024-06-03", broker, FakeDataClient(CLOSES))

    with pytest.raises(ValueError, match="closing prices"):
        run_cycle(
            fund, "2024-06-04", broker, FakeDataClient(CLOSES),
            execution_prices={"AAPL": 200.0}, valuation_prices={},
            execution_date="2024-06-05",
        )


def test_analyst_error_propagates():
    """Fail loud: an infrastructure failure must not become a quiet no-trade."""
    fund = Fund(_spec(), models={
        "solo": [FakeAnalyst("a", error=ConnectionError("API down"))],
    })
    with pytest.raises(ConnectionError):
        run_cycle(fund, "2024-06-03", SimBroker(cash=100_000.0, fee_rate=0.0),
                  FakeDataClient(CLOSES))
