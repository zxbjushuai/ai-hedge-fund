"""Deterministic event-driven persona-state tests; no network."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from hedge_fund.data.models import EarningsData, EarningsRecord, FinancialMetrics
from hedge_fund.fund import FundSpec, PersonaRefreshPolicy
from hedge_fund.llm import PromptCache
from hedge_fund.persistence.database import get_session
from hedge_fund.persistence.models import MetricsCache, PriceCache, SimCorporateAction, SimPersonaState, SimRun
from hedge_fund.pipeline.models import CycleRecord
from hedge_fund.signals import BuffettAgent
from hedge_fund.simulation.audit import persist_completed_cycle
from hedge_fund.simulation.persona_state import PersonaSignalEngine
from hedge_fund.simulation.runner import estimate_persona_event_schedule


RESPONSE = json.dumps({"signal": "bullish", "confidence": 75, "reasoning": "r"})


class SequenceLlm:
    provider = "fake"
    model = "event-model"

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    @property
    def identity(self):
        return f"{self.provider}:{self.model}"

    def complete(self, system, user):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class AuthError(Exception):
    status_code = 401


class EventData:
    def __init__(self):
        self.new_filing_for: set[str] = set()
        self.earnings: dict[str, list[EarningsRecord]] = {}

    def get_financial_metrics(self, ticker, end_date, period="ttm", limit=20):
        dates = ["2024-01-01", "2023-10-01", "2023-07-01", "2023-04-01"]
        if ticker in self.new_filing_for:
            dates.insert(0, "2024-02-01")
        return [
            FinancialMetrics(
                ticker=ticker, report_period=value, filing_date=value, period="ttm",
                market_cap=1_000_000, return_on_equity=0.2,
                book_value_per_share=10,
            )
            for value in dates if value <= end_date
        ][:limit]

    def get_company_facts(self, ticker):
        return None

    def get_earnings_history(self, ticker, limit=40, end_date=None):
        return [
            item for item in self.earnings.get(ticker, [])
            if end_date is None or (item.filing_date or "") <= end_date
        ][:limit]


def _agent(tmp_path, llm):
    return BuffettAgent(llm=llm, cache=PromptCache(tmp_path / "cache"))


def _predict(engine, agent, data, cycle, day, ticker="AAPL", mark=100):
    engine.begin_cycle(cycle)
    signal = engine.predict(agent, ticker, day, mark, data)
    return signal, engine.finish_cycle()[0]


def test_bootstrap_reuse_and_exact_valuation_threshold(tmp_path):
    llm = SequenceLlm([RESPONSE, RESPONSE])
    engine = PersonaSignalEngine(PersonaRefreshPolicy())
    agent = _agent(tmp_path, llm)
    data = EventData()

    first, first_event = _predict(engine, agent, data, 1, "2024-01-02", mark=100)
    below, below_event = _predict(engine, agent, data, 2, "2024-01-03", mark=119.99)
    edge, edge_event = _predict(engine, agent, data, 3, "2024-01-04", mark=120)

    assert first_event.trigger_reasons == ["bootstrap"]
    assert below_event.provenance == "reused"
    assert below.date == "2024-01-03"
    assert below.metadata["persona_state"]["source_signal_date"] == "2024-01-02"
    assert edge_event.trigger_reasons == ["valuation_change"]
    assert edge_event.valuation_anchor == 120
    assert first.value == edge.value == 0.75
    assert llm.calls == 2


def test_only_event_ticker_refreshes_and_duplicate_staffing_is_memoized(tmp_path):
    llm = SequenceLlm([RESPONSE, RESPONSE, RESPONSE])
    engine = PersonaSignalEngine(PersonaRefreshPolicy())
    agent = _agent(tmp_path, llm)
    data = EventData()

    engine.begin_cycle(1)
    engine.predict(agent, "AAPL", "2024-01-02", 100, data)
    engine.predict(agent, "AAPL", "2024-01-02", 100, data)
    engine.predict(agent, "MSFT", "2024-01-02", 100, data)
    assert len(engine.finish_cycle()) == 2
    assert llm.calls == 2

    data.new_filing_for.add("AAPL")
    engine.begin_cycle(2)
    engine.predict(agent, "AAPL", "2024-02-02", 100, data)
    msft = engine.predict(agent, "MSFT", "2024-02-02", 100, data)
    events = {event.ticker: event for event in engine.finish_cycle()}
    assert events["AAPL"].trigger_reasons == ["new_filing"]
    assert events["MSFT"].provenance == "reused"
    assert msft.status == "produced"
    assert llm.calls == 3


def test_retryable_failure_uses_1_2_cycle_backoff_and_preserves_prior(tmp_path):
    llm = SequenceLlm([RESPONSE, TimeoutError(), TimeoutError(), RESPONSE])
    engine = PersonaSignalEngine(PersonaRefreshPolicy())
    agent = _agent(tmp_path, llm)
    data = EventData()

    _predict(engine, agent, data, 1, "2024-01-02", mark=100)
    failed1, event1 = _predict(engine, agent, data, 2, "2024-01-03", mark=120)
    failed2, event2 = _predict(engine, agent, data, 3, "2024-01-04", mark=120)
    waiting, event3 = _predict(engine, agent, data, 4, "2024-01-05", mark=120)
    recovered, event4 = _predict(engine, agent, data, 5, "2024-01-08", mark=120)

    assert failed1.status == failed2.status == waiting.status == "produced"
    assert event1.next_retry_cycle == 3
    assert event2.next_retry_cycle == 5
    assert event3.attempt_status == "not_attempted"
    assert event4.provenance == "refreshed"
    assert recovered.status == "produced"
    assert llm.calls == 4


def test_retryable_failure_backoff_reaches_and_stays_at_five_cycles(tmp_path):
    llm = SequenceLlm([RESPONSE] + [TimeoutError()] * 5)
    engine = PersonaSignalEngine(PersonaRefreshPolicy())
    agent = _agent(tmp_path, llm)
    data = EventData()
    start = date(2024, 1, 1)

    def on_cycle(cycle):
        day = (start + timedelta(days=cycle - 1)).isoformat()
        return _predict(engine, agent, data, cycle, day, mark=100 if cycle == 1 else 120)[1]

    on_cycle(1)
    assert on_cycle(2).next_retry_cycle == 3
    assert on_cycle(3).next_retry_cycle == 5
    assert on_cycle(4).attempt_status == "not_attempted"
    assert on_cycle(5).next_retry_cycle == 9
    for cycle in (6, 7, 8):
        assert on_cycle(cycle).attempt_status == "not_attempted"
    assert on_cycle(9).next_retry_cycle == 14
    for cycle in (10, 11, 12, 13):
        assert on_cycle(cycle).attempt_status == "not_attempted"
    assert on_cycle(14).next_retry_cycle == 19
    assert llm.calls == 6


def test_expired_state_abstains_when_refresh_fails(tmp_path):
    llm = SequenceLlm([RESPONSE, TimeoutError()])
    engine = PersonaSignalEngine(PersonaRefreshPolicy(max_age_days=90))
    agent = _agent(tmp_path, llm)
    data = EventData()

    _predict(engine, agent, data, 1, "2024-01-01", mark=100)
    signal, event = _predict(engine, agent, data, 2, "2024-03-31", mark=100)

    assert signal.status == "abstained"
    assert event.provenance == "expired"
    assert event.attempt_status == "failed"
    assert event.failure["category"] == "timeout"


def test_max_age_refreshes_on_day_90_not_day_89(tmp_path):
    llm = SequenceLlm([RESPONSE, RESPONSE])
    engine = PersonaSignalEngine(PersonaRefreshPolicy(max_age_days=90))
    agent = _agent(tmp_path, llm)
    data = EventData()

    _predict(engine, agent, data, 1, "2024-01-01", mark=100)
    _, day89 = _predict(engine, agent, data, 2, "2024-03-30", mark=100)
    _, day90 = _predict(engine, agent, data, 3, "2024-03-31", mark=100)

    assert day89.provenance == "reused"
    assert day90.trigger_reasons == ["max_age"]
    assert llm.calls == 2


def test_data_infrastructure_failure_propagates(tmp_path):
    class BrokenData(EventData):
        def get_financial_metrics(self, *args, **kwargs):
            raise ConnectionError("database unavailable")

    engine = PersonaSignalEngine(PersonaRefreshPolicy())
    agent = _agent(tmp_path, SequenceLlm([RESPONSE]))
    engine.begin_cycle(1)
    with pytest.raises(ConnectionError, match="database unavailable"):
        engine.predict(agent, "AAPL", "2024-01-02", 100, BrokenData())


def test_non_retryable_failure_waits_for_new_event(tmp_path):
    llm = SequenceLlm([RESPONSE, AuthError(), RESPONSE])
    engine = PersonaSignalEngine(PersonaRefreshPolicy())
    agent = _agent(tmp_path, llm)
    data = EventData()

    _predict(engine, agent, data, 1, "2024-01-02", mark=100)
    _, failed = _predict(engine, agent, data, 2, "2024-01-03", mark=120)
    _, waiting = _predict(engine, agent, data, 3, "2024-01-04", mark=120)
    data.new_filing_for.add("AAPL")
    _, refreshed = _predict(engine, agent, data, 4, "2024-02-02", mark=120)

    assert failed.failure["category"] == "authentication"
    assert failed.next_retry_cycle is None
    assert waiting.attempt_status == "not_attempted"
    assert refreshed.provenance == "refreshed"
    assert llm.calls == 3


def test_earnings_is_invisible_before_announcement_and_coalesces(tmp_path):
    llm = SequenceLlm([RESPONSE, RESPONSE])
    engine = PersonaSignalEngine(PersonaRefreshPolicy())
    agent = _agent(tmp_path, llm)
    data = EventData()
    data.earnings["AAPL"] = [EarningsRecord(
        ticker="AAPL", report_period="2023-12-31", source_type="earnings",
        filing_date="2024-01-05",
        quarterly=EarningsData(
            earnings_per_share=2, estimated_earnings_per_share=1,
            eps_surprise_percent=100,
        ),
    )]

    _predict(engine, agent, data, 1, "2024-01-02", mark=100)
    _, before = _predict(engine, agent, data, 2, "2024-01-04", mark=100)
    _, visible = _predict(engine, agent, data, 3, "2024-01-05", mark=120)

    assert before.provenance == "reused"
    assert visible.trigger_reasons == ["actionable_earnings", "valuation_change"]
    assert llm.calls == 2


def test_event_schedule_estimate_coalesces_and_uses_exact_threshold(tmp_path):
    db = tmp_path / "estimate.db"
    days = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    with get_session(str(db)) as session:
        for day, close in zip(days, (100, 119.99, 120, 120)):
            session.add(PriceCache(
                ticker="AAPL", date=day, open=close, high=close,
                low=close, close=close, volume=1,
            ))
        for index, filing_date in enumerate(
            ("2023-01-01", "2023-04-01", "2023-07-01", "2023-10-01")
        ):
            metric = FinancialMetrics(
                ticker="AAPL", report_period=f"2023-0{index + 1}-01", period="ttm",
            )
            session.add(MetricsCache(
                ticker="AAPL", report_period=metric.report_period,
                filing_date=filing_date, filing_date_source="test",
                data=metric.model_dump_json(exclude={"ticker"}),
            ))
        session.commit()

    estimate = estimate_persona_event_schedule(
        str(db), ["AAPL"], days, {"buffett"}, PersonaRefreshPolicy(),
    )
    assert estimate["estimated_refresh_events"] == 2
    assert estimate["estimated_llm_calls"] == 2
    assert estimate["event_reason_counts"]["bootstrap"] == 1
    assert estimate["event_reason_counts"]["valuation_change"] == 1


def test_persona_state_is_persisted_with_cycle_atomically(tmp_path):
    db = tmp_path / "state.db"
    llm = SequenceLlm([RESPONSE])
    engine = PersonaSignalEngine(PersonaRefreshPolicy())
    agent = _agent(tmp_path, llm)
    signal, event = _predict(engine, agent, EventData(), 1, "2024-01-02", mark=100)
    spec = FundSpec(
        name="test",
        strategies=[{"name": "s", "models": [{"name": "buffett"}]}],
        risk={"max_position_pct": 1, "max_gross_exposure": 1},
    )
    record = CycleRecord(
        fund="test", as_of="2024-01-02", execution_date="2024-01-03",
        spec=spec, universe=["AAPL"], marks={"AAPL": 100},
        execution_prices={}, valuation_prices={}, skipped=[], strategies=[],
        persona_events=[event], target_weights={}, clamps=[], final_weights={},
        corporate_actions=[{
            "ticker": "AAPL", "action_type": "dividend", "value": 1,
            "shares_before": 5, "shares_after": 5, "cash_amount": 5,
        }],
        equity_before=1000, cash_before=1000, orders=[], fills=[], positions={},
        cash=1000, nav=1000,
    )
    with get_session(str(db)) as session:
        run = SimRun(
            tickers='["AAPL"]', benchmark="SPY", start_date="2024-01-02",
            end_date="2024-01-03", initial_capital=1000, status="running",
        )
        session.add(run)
        session.commit()
        sim_id = run.id

    persist_completed_cycle(str(db), sim_id, 1, record, 1000)
    with get_session(str(db)) as session:
        state = session.execute(select(SimPersonaState)).scalar_one()
        assert state.sim_run_id == sim_id
        assert state.source_signal_date == "2024-01-02"
        assert state.valuation_anchor == 100
        assert json.loads(state.signal_payload)["value"] == signal.value
        assert session.execute(select(SimCorporateAction)).scalar_one().cash_amount == 5

    with pytest.raises(IntegrityError):
        persist_completed_cycle(str(db), sim_id, 1, record, 1000)
    with get_session(str(db)) as session:
        assert session.query(SimPersonaState).count() == 1
        assert session.query(SimCorporateAction).count() == 1


def test_concurrent_simulation_engines_do_not_share_persona_state(tmp_path):
    barrier = threading.Barrier(2)

    class BarrierLlm(SequenceLlm):
        def complete(self, system, user):
            barrier.wait(timeout=5)
            return super().complete(system, user)

    def bootstrap(name):
        llm = BarrierLlm([RESPONSE])
        engine = PersonaSignalEngine(PersonaRefreshPolicy())
        agent = BuffettAgent(
            llm=llm, cache=PromptCache(tmp_path / f"cache-{name}"),
        )
        signal, event = _predict(engine, agent, EventData(), 1, "2024-01-02")
        return signal, event, llm.calls

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(bootstrap, ("one", "two")))

    assert [item[1].provenance for item in results] == ["refreshed", "refreshed"]
    assert [item[2] for item in results] == [1, 1]
