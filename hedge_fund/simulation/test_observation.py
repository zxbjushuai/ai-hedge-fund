"""Offline regression tests for run telemetry and bounded inference."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest

from hedge_fund.fund import PersonaRefreshPolicy
from hedge_fund.llm import PromptCache
from hedge_fund.llm.base import ChatLLM, ResponseError
from hedge_fund.failures import classify_llm_failure
from hedge_fund.persistence.database import get_session
from hedge_fund.persistence.models import SimRun, SimNavSnapshot
from hedge_fund.signals import BuffettAgent
from hedge_fund.simulation.observation import RunObservation, http_request, http_response
from hedge_fund.simulation.persona_state import PersonaSignalEngine
from hedge_fund.simulation.runner import get_sim_result
from hedge_fund.simulation.test_persona_state import EventData, RESPONSE


@pytest.mark.parametrize("concurrency", [1, 4, 8])
def test_bounded_inference_main_thread_state_and_dedup(tmp_path, concurrency):
    owner = threading.get_ident()
    lock = threading.Lock()
    active = peak = calls = 0

    class Client:
        provider = "fake"
        model = "fake"

        def complete(self, system, user):
            nonlocal active, peak, calls
            assert threading.get_ident() != owner
            with lock:
                active += 1
                calls += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            return RESPONSE

    class Data(EventData):
        def get_financial_metrics(self, *args, **kwargs):
            assert threading.get_ident() == owner
            return super().get_financial_metrics(*args, **kwargs)

    class BoundedObserver(RunObservation):
        def queue(self, count):
            assert count <= 2 * concurrency
            assert threading.get_ident() == owner
            super().queue(count)
    observer = BoundedObserver(1, concurrency, tmp_path)
    engine = PersonaSignalEngine(PersonaRefreshPolicy(), concurrency, observer)
    agent = BuffettAgent(llm=Client(), cache=PromptCache(tmp_path / "cache"))
    engine.begin_cycle(1)
    requests = [(agent, f"T{i}", "2024-01-02", 100) for i in range(24)]
    engine.prepare_cycle(requests + requests, Data())
    events = engine.finish_cycle()
    assert calls == 24
    assert 1 <= peak <= concurrency
    assert [e.ticker for e in events] == [f"T{i}" for i in range(24)]
    assert all(e.effective_signal.value == 0.75 for e in events)
    engine.begin_cycle(2)
    engine.prepare_cycle([(agent, f"T{i}", "2024-01-03", 100) for i in range(24)], Data())
    assert calls == 24
    assert all(e.provenance == "reused" for e in engine.finish_cycle())
    observer.close()
    assert observer.snapshot()["counts"]["opinion_reused"] == 24


def test_safe_diagnostics_http_success_is_not_valid_signal(tmp_path):
    observer = RunObservation(2, 1, tmp_path)
    client = ChatLLM("fake", "openai_chat_completions", "fake", SimpleNamespace(
        invoke=lambda messages: SimpleNamespace(content="", response_metadata={"finish_reason": "length"})))
    with observer.call(ticker="AAPL", persona="buffett", signal_date="2024-01-02"):
        req = httpx.Request("POST", "https://example.invalid?api_key=SECRET", headers={"Authorization": "SECRET"})
        http_request(req)
        http_response(httpx.Response(200, request=req))
        with pytest.raises(ResponseError) as error:
            client.complete("SECRET PROMPT", "SECRET INPUT")
        assert classify_llm_failure(error.value).category == "truncated_response"
    observer.close()
    text = (tmp_path / "sim-2.log").read_text(encoding="utf-8")
    assert "SECRET" not in text
    rows = [json.loads(line) for line in text.splitlines()]
    assert next(r for r in rows if r["event"] == "http_response")["http_status"] == 200
    assert len({r["call_id"] for r in rows}) == 1


@pytest.mark.parametrize("status,category", [(401, "authentication"), (403, "authentication"), (429, "rate_limit"), (503, "server_error")])
def test_safe_failure_categories(status, category):
    error = ResponseError("http_error", status)
    assert classify_llm_failure(error).category == category


@pytest.mark.parametrize("status,value", [("running", 80), ("failed", 80), ("completed", 0), ("pending", None)])
def test_partial_and_zero_nav(tmp_path, status, value):
    db = str(tmp_path / "test.db")
    with get_session(db) as session:
        run = SimRun(tickers='["AAPL"]', start_date="2024-01-02", end_date="2024-01-03",
                     initial_capital=100, status=status, final_nav=value if status == "completed" else None)
        session.add(run)
        session.flush()
        sim_id = run.id
        if value is not None:
            session.add(SimNavSnapshot(sim_run_id=sim_id, cycle_date="2024-01-03", nav=value,
                                       cash=value, equity=0, benchmark_nav=120))
        session.commit()
    result = get_sim_result(sim_id, db)
    assert result["final_nav"] == value
    assert result["total_return_pct"] == (value - 100 if value is not None else None)
    assert result["excess_return_pct"] == (value - 120 if value is not None else None)
    if value is None:
        assert result["max_drawdown_pct"] is None
        assert result["sharpe_ratio"] is None


def test_log_failure_is_visible(tmp_path):
    observer = RunObservation(3, 1, tmp_path)
    observer.close()
    observer.emit("test")
    assert observer.snapshot()["error"] == "Simulation log write failed"


def test_process_limit_across_runs(tmp_path):
    lock = threading.Lock()
    active = peak = 0
    class Client:
        provider = "fake"
        model = "fake"
        def complete(self, system, user):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return RESPONSE
    def run(index):
        engine = PersonaSignalEngine(PersonaRefreshPolicy(), 8)
        agent = BuffettAgent(llm=Client(), cache=PromptCache(tmp_path / str(index)))
        engine.begin_cycle(1)
        engine.prepare_cycle([(agent, f"T{i}", "2024-01-02", 100) for i in range(16)], EventData())
        return len(engine.finish_cycle())
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, [1, 2])) == [16, 16]
    assert 1 < peak <= 8


def test_sdk_retries_keep_call_identity_and_actual_status(tmp_path, monkeypatch):
    from hedge_fund.llm.providers import make_connection_llm
    from hedge_fund.llm.types import LlmRuntimeConfig, LlmProtocol
    attempts = 0
    def transport(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": {"message": "SECRET", "type": "server_error"}})
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0, "model": "fake",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": RESPONSE}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
        })
    http = httpx.Client(transport=httpx.MockTransport(transport),
                        event_hooks={"request": [http_request], "response": [http_response]})
    monkeypatch.setattr("hedge_fund.llm.protocols.observed_http_client", lambda: http)
    client = make_connection_llm(LlmRuntimeConfig(vendor="openai", protocol=LlmProtocol.OPENAI_CHAT,
        model="fake", base_url="https://example.invalid/v1", api_key="SECRET"))
    observer = RunObservation(4, 1, tmp_path)
    with observer.call(ticker="AAPL", persona="buffett"):
        assert client.complete("SECRET", "SECRET") == RESPONSE
    observer.close()
    http.close()
    text = (tmp_path / "sim-4.log").read_text()
    assert "SECRET" not in text
    records = [json.loads(line) for line in text.splitlines()]
    assert [r["http_status"] for r in records if r["event"] == "http_response"] == [503, 200]
    assert [r["attempt_number"] for r in records if r["event"] == "http_attempt"] == [1, 2]
    assert len({r["call_id"] for r in records}) == 1


@pytest.mark.parametrize("protocol", ["chat", "responses", "anthropic"])
def test_protocols_report_empty_and_usage_without_body(tmp_path, monkeypatch, protocol):
    from hedge_fund.llm.base import ResponsesLLM, AnthropicMessagesLLM
    result = SimpleNamespace(content="", output_text="", usage={"input_tokens": 3},
                             response_metadata={"finish_reason": "stop"})
    if protocol == "chat":
        client = ChatLLM("fake", protocol, "fake", SimpleNamespace(invoke=lambda _: result))
    elif protocol == "responses":
        client = ResponsesLLM("fake", protocol, "fake", SimpleNamespace(
            responses=SimpleNamespace(create=lambda **kwargs: result)))
    else:
        monkeypatch.setattr("hedge_fund.llm.base.httpx.post", lambda *args, **kwargs:
                            httpx.Response(200, json={"content": [], "usage": {"input_tokens": 3}, "stop_reason": "end_turn"}))
        client = AnthropicMessagesLLM("fake", protocol, "fake", "https://example.invalid", "SECRET")
    observer = RunObservation(5, 1, tmp_path)
    with observer.call(ticker="AAPL", persona="buffett"):
        with pytest.raises(ResponseError) as error:
            client.complete("SECRET", "SECRET")
        assert classify_llm_failure(error.value).category == "empty_response"
    observer.close()
    assert "SECRET" not in (tmp_path / "sim-5.log").read_text()


@pytest.mark.parametrize("value", [0, 9, 1.5, True, "4"])
def test_api_rejects_invalid_concurrency(value):
    from research_app.backend.routes.schemas import SimRunRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        SimRunRequest(tickers=["AAPL"], start_date="2024-01-02", end_date="2024-01-03",
                      initial_capital=100, llm_concurrency=value)


def test_runner_concurrency_preserves_nav_fills_actions_and_audit(tmp_path, monkeypatch):
    from sqlalchemy import select
    from hedge_fund.fund import FundSpec
    from hedge_fund.persistence.models import PriceCache, MetricsCache, SimCycleRecord
    from hedge_fund.simulation.runner import SimRunner
    import hedge_fund.simulation.runner as module
    spec = FundSpec.model_validate({"name": "parallel-test", "capital": 10000,
        "risk": {"max_position_pct": 0.5, "max_gross_exposure": 1.0},
        "strategies": [{"name": "value", "models": [{"name": "buffett"}]}]})
    monkeypatch.setattr(module, "load_spec", lambda _: spec.model_copy(deep=True))
    comparisons = []
    for concurrency in (1, 4, 8):
        folder = tmp_path / str(concurrency)
        folder.mkdir()
        monkeypatch.setenv("PROMPT_CACHE_DIR", str(folder / "cache"))
        db = str(folder / "fund.db")
        with get_session(db) as session:
            for ticker in ("AAA", "BBB", "SPY"):
                for index, (day, price) in enumerate(zip(
                        ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"], [10, 12, 6, 7])):
                    session.add(PriceCache(ticker=ticker, date=day, open=price, high=price,
                        low=price, close=price, adjusted_close=10+index,
                        dividend=1 if index == 1 else 0, split_ratio=2 if index == 2 else 0))
                if ticker != "SPY":
                    for metric in EventData().get_financial_metrics(ticker, "2024-01-02"):
                        session.add(MetricsCache(ticker=ticker, report_period=metric.report_period,
                            filing_date=metric.filing_date, filing_date_source="test",
                            data=metric.model_dump_json(exclude={"ticker"})))
            session.commit()
        class Client:
            provider = "fake"
            model = "fake"
            identity = "fake:fake"
            def complete(self, system, user):
                time.sleep(0.002 if "AAA" in user else 0.001)
                return RESPONSE
        sim_id = SimRunner.create(tickers=["AAA", "BBB"], start_date="2024-01-02",
            end_date="2024-01-05", initial_capital=10000, db_path=db,
            fund_spec_path=__file__, llm=Client(), llm_concurrency=concurrency)
        runner = SimRunner._get(sim_id)
        runner._run()
        result = get_sim_result(sim_id, db)
        assert result["status"] == "completed", result.get("error_message")
        with get_session(db) as session:
            audits = [json.loads(row.payload) for row in session.scalars(
                select(SimCycleRecord).where(SimCycleRecord.sim_run_id == sim_id)
                .order_by(SimCycleRecord.cycle_number))]
        comparisons.append((result["nav_curve"], result["trades"], audits))
        assert runner.observer.snapshot()["active"] == []
    assert comparisons[0] == comparisons[1] == comparisons[2]


def test_cannot_create_run_without_log(tmp_path, monkeypatch):
    import hedge_fund.simulation.runner as module
    from hedge_fund.persistence.models import PriceCache
    db = str(tmp_path / "fund.db")
    with get_session(db) as session:
        for day in ("2024-01-02", "2024-01-03"):
            session.add(PriceCache(ticker="SPY", date=day, open=10, high=10, low=10, close=10))
        session.commit()
    def denied(*args, **kwargs):
        raise PermissionError("Log directory unavailable")
    monkeypatch.setattr(module, "RunObservation", denied)
    with pytest.raises(PermissionError):
        module.SimRunner.create(tickers=["AAPL"], start_date="2024-01-02", end_date="2024-01-03",
            initial_capital=100, db_path=db, fund_spec_path=str(tmp_path / "missing.yaml"))
    with get_session(db) as session:
        assert session.query(SimRun).count() == 0


def test_mixed_immediate_and_async_events_keep_order(tmp_path):
    outputs = []
    class PartialData(EventData):
        def get_financial_metrics(self, ticker, *args, **kwargs):
            return [] if ticker == "MISSING" else super().get_financial_metrics(ticker, *args, **kwargs)
    class Client:
        provider = "fake"
        model = "fake"
        def complete(self, *args):
            return RESPONSE
    for concurrency in (1, 4, 8):
        engine = PersonaSignalEngine(PersonaRefreshPolicy(), concurrency)
        agent = BuffettAgent(llm=Client(), cache=PromptCache(tmp_path / str(concurrency)))
        engine.begin_cycle(1)
        engine.prepare_cycle([(agent, ticker, "2024-01-02", 100)
                              for ticker in ("AAA", "BBB", "MISSING", "CCC")], PartialData())
        outputs.append([event.model_dump() for event in engine.finish_cycle()])
    assert outputs[0] == outputs[1] == outputs[2]


def test_remote_error_code_allowlist_never_logs_free_text():
    from hedge_fund.failures import safe_remote_error_code
    error = ResponseError("http_error", 400)
    error.body = {"error": {"code": "MissingSessionId", "message": "Bearer SECRET"}}
    assert safe_remote_error_code(error) == "MissingSessionId"
    error.body = {"error": {"code": "SECRET", "message": "Bearer SECRET"}}
    assert safe_remote_error_code(error) is None


def test_transport_timeout_has_no_http_status(tmp_path):
    from hedge_fund.llm.protocols import ObservedHTTPClient
    def timeout(request):
        raise httpx.ReadTimeout("SECRET", request=request)
    observer = RunObservation(9, 1, tmp_path)
    with ObservedHTTPClient(transport=httpx.MockTransport(timeout),
                            event_hooks={"request": [http_request], "response": [http_response]}) as client:
        with observer.call(ticker="AAPL", persona="buffett"):
            with pytest.raises(httpx.ReadTimeout):
                client.get("https://example.invalid")
    observer.close()
    text = (tmp_path / "sim-9.log").read_text()
    assert "SECRET" not in text
    failed = next(json.loads(line) for line in text.splitlines() if '"http_attempt_failed"' in line)
    assert failed["http_status"] is None
    assert failed["category"] == "timeout"
