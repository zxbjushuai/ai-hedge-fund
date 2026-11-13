"""Run-scoped event-driven effective state for LLM persona signals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from collections.abc import Callable, Generator
from threading import Event

from hedge_fund.data.earnings import earnings_surprise_percent
from hedge_fund.data.protocol import DataClient
from hedge_fund.features.snapshot import InsufficientData
from hedge_fund.fund import PersonaRefreshPolicy
from hedge_fund.models import FailureDetail, Signal
from hedge_fund.pipeline.models import PersonaEventRecord
from hedge_fund.simulation.cancellation import SimulationCancelled
from hedge_fund.signals.llm_agent import LLMAgent


@dataclass
class _PersonaState:
    signal: Signal | None = None
    source_signal_date: str | None = None
    snapshot_hash: str | None = None
    prompt_key: str | None = None
    valuation_anchor: float | None = None
    latest_filing_date: str | None = None
    latest_earnings_date: str | None = None
    pending_event_fingerprint: str | None = None
    failure_count: int = 0
    next_retry_cycle: int | None = None
    last_failure: FailureDetail | None = None


class PersonaSignalEngine:
    """Materialize one effective persona signal per identity and cycle."""

    def __init__(
        self,
        policy: PersonaRefreshPolicy,
        concurrency: int = 1,
        observer=None,
        cancel_event: Event | None = None,
    ) -> None:
        if type(concurrency) is not int or not 1 <= concurrency <= 8:
            raise ValueError("concurrency must be an integer between 1 and 8")
        self.concurrency = concurrency
        self.observer = observer
        self.cancel_event = cancel_event
        self.policy = policy
        self._states: dict[tuple[str, str, str, str], _PersonaState] = {}
        self._cycle_number = 0
        self._memo: dict[tuple[str, str, str, str], Signal] = {}
        self._events: list[PersonaEventRecord] = []
        self._order = {}

    def begin_cycle(self, cycle_number: int) -> None:
        self._check_cancel()
        self._cycle_number = cycle_number
        self._memo = {}
        self._events = []
        self._order = {}

    def finish_cycle(self) -> list[PersonaEventRecord]:
        return sorted(self._events, key=lambda event: self._order[
            (event.ticker, event.persona, event.model_identity, event.prompt_identity)])

    def predict(
        self, agent, ticker, as_of, mark, data_client,
    ) -> Signal:
        self._check_cancel()
        generator = self._prepare(agent, ticker, as_of, mark, data_client)
        try:
            work = next(generator)
        except StopIteration as done:
            return done.value
        try:
            generator.send(work())
        except StopIteration as done:
            return done.value
        raise RuntimeError("Unexpected second inference request")

    def prepare_cycle(self, requests, data_client):
        """Bounded preparation/inference; state transitions stay on this thread."""
        self._check_cancel()
        seen = set()
        pending = {}
        ready = {}
        submitted = next_apply = 0
        cancelled = False
        def collect():
            nonlocal next_apply
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            self._check_cancel()
            for future in completed:
                index, generator = pending.pop(future)
                ready[index] = (generator, future.result())
            while next_apply in ready:
                generator, result = ready.pop(next_apply)
                try:
                    generator.send(result)
                except StopIteration:
                    pass
                next_apply += 1
            if self.observer:
                self.observer.queue(len(pending))
        pool = ThreadPoolExecutor(max_workers=self.concurrency)
        try:
            for agent, ticker, as_of, mark in requests:
                self._check_cancel()
                key = (ticker, agent.name, agent.model_identity, agent.prompt_identity)
                if key in seen:
                    continue
                seen.add(key)
                generator = self._prepare(agent, ticker, as_of, mark, data_client)
                try:
                    work = next(generator)
                except StopIteration:
                    continue
                pending[pool.submit(self._run_work, work)] = (submitted, generator)
                submitted += 1
                if self.observer:
                    self.observer.queue(len(pending))
                if len(pending) >= 2 * self.concurrency:
                    collect()
            while pending:
                collect()
        except SimulationCancelled:
            cancelled = True
            for future in pending:
                future.cancel()
            raise
        finally:
            pool.shutdown(wait=True, cancel_futures=cancelled)

    def _run_work(self, work):
        self._check_cancel()
        return work()

    def _check_cancel(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise SimulationCancelled("simulation cancelled by user")

    def _prepare(
        self,
        agent: LLMAgent,
        ticker: str,
        as_of: str,
        mark: float,
        data_client: DataClient,
    ) -> Generator[Callable[[], Signal], Signal, Signal]:
        key = (ticker, agent.name, agent.model_identity, agent.prompt_identity)
        self._order.setdefault(key, len(self._order))
        if key in self._memo:
            return self._memo[key].model_copy(deep=True)

        state = self._states.setdefault(key, _PersonaState())
        try:
            snapshot = agent.build_snapshot(ticker, as_of, data_client)
        except InsufficientData as exc:
            # TODO(event-driven-persona): define an explicit startup eligibility
            # policy for newly listed and partial-history securities.  The current
            # bootstrap path requires a recent mark plus four visible quarterly
            # periods; until then LLM analysts abstain even though independent quant
            # models may still trade the ticker.  Decide whether future inputs such
            # as S-1 history can support a bounded-confidence initial opinion.
            signal = self._unavailable(agent, ticker, as_of, str(exc))
            event = self._event(
                key, state, signal, "unavailable", [], "abstained",
                failure=signal.failure,
            )
            return self._remember(key, signal, event)

        latest_filing = max(
            (period.filing_date for period in snapshot.periods if period.filing_date),
            default=None,
        )
        earnings_date, surprise_pct = self._latest_actionable_earnings(
            ticker, as_of, data_client,
        )
        age_days = self._age_days(state.source_signal_date, as_of)
        valuation_move = (
            ((mark / state.valuation_anchor) - 1.0) * 100.0
            if state.valuation_anchor not in (None, 0) else None
        )

        reasons: list[str] = []
        if state.signal is None:
            # TODO(event-driven-persona): distinguish a ticker becoming eligible from
            # a failed bootstrap attempt.  Today a cycle-1 refresh failure has no
            # effective signal, so cycle 2 is relabeled as universe_entry; that changes
            # the event fingerprint and can bypass the configured retry backoff.
            reasons.append("bootstrap" if self._cycle_number == 1 else "universe_entry")
            if earnings_date:
                reasons.append("actionable_earnings")
        else:
            # TODO(event-driven-persona): cached yfinance metrics currently become
            # visible on an estimated report_period + 45 days.  Use an authoritative,
            # source-aware filing/acceptance timestamp before interpreting every
            # snapshot hash change as an exact new_filing event.
            if state.snapshot_hash != snapshot.content_hash:
                reasons.append("new_filing")
            if earnings_date and earnings_date != state.latest_earnings_date:
                reasons.append("actionable_earnings")
            if (
                valuation_move is not None
                and abs(valuation_move) + 1e-9 >= self.policy.valuation_change_pct
            ):
                reasons.append("valuation_change")
            if age_days is not None and age_days >= self.policy.max_age_days:
                reasons.append("max_age")

        if not reasons:
            signal = self._reuse(state, ticker, as_of, "reused", [], age_days)
            event = self._event(key, state, signal, "reused", [], "not_attempted", age_days=age_days)
            return self._remember(key, signal, event)

        fingerprint = self._fingerprint(
            reasons, snapshot.content_hash, earnings_date, state, valuation_move,
        )
        same_pending = fingerprint == state.pending_event_fingerprint
        retry_due = state.next_retry_cycle is not None and self._cycle_number >= state.next_retry_cycle
        if same_pending and not retry_due:
            provenance = "expired" if self._expired(age_days) else (
                "reused" if state.signal is not None else "unavailable"
            )
            signal = (
                self._reuse(state, ticker, as_of, provenance, reasons, age_days)
                if state.signal is not None and provenance == "reused"
                else self._unavailable(
                    agent, ticker, as_of,
                    "persona refresh is unavailable while waiting for a new event or retry",
                    state.last_failure,
                    provenance,
                    reasons,
                    age_days,
                    state.source_signal_date,
                )
            )
            event = self._event(
                key, state, signal, provenance, reasons, "not_attempted",
                failure=state.last_failure, age_days=age_days,
            )
            return self._remember(key, signal, event)

        context = {
            "trigger_reasons": reasons,
            "current_close": round(mark, 6),
            "valuation_change_pct": round(valuation_move, 4) if valuation_move is not None else None,
            "latest_filing_date": latest_filing,
            "latest_actionable_earnings": (
                {"announcement_date": earnings_date, "surprise_pct": surprise_pct}
                if earnings_date else None
            ),
        }
        def infer():
            if self.observer is None:
                return agent.predict_snapshot(ticker, as_of, snapshot, context)
            with self.observer.call(ticker=ticker, persona=agent.name,
                                    model=agent.model_identity, trigger_reasons=reasons):
                return agent.predict_snapshot(ticker, as_of, snapshot, context)
        attempted = yield infer
        if attempted.status == "produced":
            attempted.metadata["persona_state"] = self._metadata(
                "refreshed", reasons, as_of, 0, "produced", None,
            )
            state.signal = attempted.model_copy(deep=True)
            state.source_signal_date = as_of
            state.snapshot_hash = snapshot.content_hash
            state.prompt_key = attempted.metadata.get("prompt_key")
            state.valuation_anchor = mark
            state.latest_filing_date = latest_filing
            state.latest_earnings_date = earnings_date
            state.pending_event_fingerprint = None
            state.failure_count = 0
            state.next_retry_cycle = None
            state.last_failure = None
            event = self._event(
                key, state, attempted, "refreshed", reasons, "produced",
                age_days=0, fingerprint=fingerprint,
            )
            return self._remember(key, attempted, event)

        failure = attempted.failure or FailureDetail(
            category="internal", message="persona refresh failed", retryable=False,
        )
        state.failure_count = state.failure_count + 1 if same_pending else 1
        state.pending_event_fingerprint = fingerprint
        state.last_failure = failure
        if failure.retryable:
            delays = self.policy.retry_backoff_trading_days
            delay = delays[min(state.failure_count - 1, len(delays) - 1)]
            state.next_retry_cycle = self._cycle_number + delay
        else:
            state.next_retry_cycle = None

        valid_prior = state.signal is not None and not self._expired(age_days)
        provenance = "reused" if valid_prior else (
            "expired" if state.signal is not None else "unavailable"
        )
        signal = (
            self._reuse(
                state, ticker, as_of, provenance, reasons, age_days,
                attempt_failure=failure,
            )
            if valid_prior
            else self._unavailable(
                agent, ticker, as_of, "persona refresh failed and no valid prior opinion exists",
                failure, provenance, reasons, age_days,
                state.source_signal_date,
            )
        )
        event = self._event(
            key, state, signal, provenance, reasons, "failed",
            failure=failure, age_days=age_days, fingerprint=fingerprint,
        )
        return self._remember(key, signal, event)

    @staticmethod
    def _latest_actionable_earnings(
        ticker: str, as_of: str, data_client: DataClient,
    ) -> tuple[str | None, float | None]:
        records = data_client.get_earnings_history(ticker, limit=40, end_date=as_of)
        events = [
            (record.filing_date, earnings_surprise_percent(record))
            for record in records
            if record.filing_date and earnings_surprise_percent(record) not in (None, 0)
        ]
        return max(events, default=(None, None), key=lambda item: item[0] or "")

    def _reuse(
        self, state: _PersonaState, ticker: str, as_of: str, provenance: str,
        reasons: list[str], age_days: int | None,
        attempt_failure: FailureDetail | None = None,
    ) -> Signal:
        assert state.signal is not None
        signal = state.signal.model_copy(deep=True, update={"ticker": ticker, "date": as_of})
        signal.metadata["persona_state"] = self._metadata(
            provenance, reasons, state.source_signal_date, age_days,
            "failed" if attempt_failure else "not_attempted", attempt_failure,
        )
        return signal

    def _unavailable(
        self, agent: LLMAgent, ticker: str, as_of: str, reason: str,
        failure: FailureDetail | None = None, provenance: str = "unavailable",
        reasons: list[str] | None = None, age_days: int | None = None,
        source_date: str | None = None,
    ) -> Signal:
        detail = failure or FailureDetail(
            category="insufficient_data", message=reason, retryable=False,
        )
        return Signal(
            model_name=agent.name,
            ticker=ticker,
            date=as_of,
            value=0.0,
            status="abstained",
            failure=detail,
            reasoning=f"abstained: {reason}",
            metadata={
                "abstained": True,
                "failed": False,
                "cached": False,
                "persona_state": self._metadata(
                    provenance, reasons or [], source_date, age_days,
                    "failed" if failure else "abstained", failure,
                ),
            },
        )

    @staticmethod
    def _metadata(
        provenance: str, reasons: list[str], source_date: str | None,
        age_days: int | None, attempt_status: str,
        failure: FailureDetail | None,
    ) -> dict:
        return {
            "provenance": provenance,
            "trigger_reasons": reasons,
            "source_signal_date": source_date,
            "age_days": age_days,
            "attempt_status": attempt_status,
            "attempt_failure": failure.model_dump() if failure else None,
        }

    @staticmethod
    def _age_days(source_date: str | None, as_of: str) -> int | None:
        if source_date is None:
            return None
        return (date.fromisoformat(as_of) - date.fromisoformat(source_date)).days

    def _expired(self, age_days: int | None) -> bool:
        return age_days is not None and age_days >= self.policy.max_age_days

    @staticmethod
    def _fingerprint(
        reasons: list[str], snapshot_hash: str, earnings_date: str | None,
        state: _PersonaState, valuation_move: float | None,
    ) -> str:
        payload = {
            "reasons": sorted(reasons),
            "snapshot_hash": snapshot_hash,
            "earnings_date": earnings_date,
            "source_signal_date": state.source_signal_date,
            "valuation_anchor": state.valuation_anchor,
            "valuation_direction": (
                1 if valuation_move is not None and valuation_move >= 0 else -1
            ),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]

    def _event(
        self, key, state: _PersonaState, signal: Signal, provenance: str,
        reasons: list[str], attempt_status: str,
        failure: FailureDetail | None = None, age_days: int | None = None,
        fingerprint: str | None = None,
    ) -> PersonaEventRecord:
        ticker, persona, model_identity, prompt_identity = key
        return PersonaEventRecord(
            ticker=ticker,
            persona=persona,
            model_identity=model_identity,
            prompt_identity=prompt_identity,
            provenance=provenance,
            trigger_reasons=reasons,
            source_signal_date=state.source_signal_date,
            age_days=age_days,
            attempt_status=attempt_status,
            failure=failure.model_dump() if failure else None,
            prompt_key=state.prompt_key,
            snapshot_hash=state.snapshot_hash,
            valuation_anchor=state.valuation_anchor,
            latest_filing_date=state.latest_filing_date,
            latest_earnings_date=state.latest_earnings_date,
            event_fingerprint=fingerprint or state.pending_event_fingerprint,
            failure_count=state.failure_count,
            next_retry_cycle=state.next_retry_cycle,
            effective_signal=signal,
        )

    def _remember(
        self, key, signal: Signal, event: PersonaEventRecord,
    ) -> Signal:
        self._memo[key] = signal.model_copy(deep=True)
        self._events.append(event)
        if self.observer:
            self.observer.emit("persona_result", ticker=key[0], persona=key[1],
                               value=signal.value, status=signal.status,
                               source_signal_date=event.source_signal_date, age_days=event.age_days,
                               trigger_reasons=event.trigger_reasons,
                               provenance=event.provenance, attempt_status=event.attempt_status,
                               next_retry_cycle=event.next_retry_cycle,
                               failure_category=event.failure.get("category") if event.failure else None)
        return signal
