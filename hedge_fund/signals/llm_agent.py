"""LLMAgent — base class for LLM investor agents (the second AlphaModel flavor).

An LLMAgent reasons over a point-in-time FundamentalsSnapshot in a persona's
voice and emits the same Signal every quant model does. The base class owns
all the machinery; a persona is just a name + a system prompt:

    class BuffettAgent(LLMAgent):
        @property
        def name(self) -> str:
            return "buffett"

        def get_system_prompt(self) -> str:
            return "You are Warren Buffett..."

Failure contract:
- Data-layer errors PROPAGATE (fail loud — a broken snapshot must never
  silently become a neutral view).
- Missing point-in-time inputs ABSTAIN.
- LLM call/parse failures produce a typed FAILED signal.
- Every LLM decision persists its exact prompt + response (via PromptCache),
  and an unchanged snapshot never pays for a second LLM call.
"""

from __future__ import annotations

import logging
import hashlib
import json

from hedge_fund.data.protocol import DataClient
from hedge_fund.failures import classify_llm_failure
from hedge_fund.features.snapshot import FundamentalsSnapshot, InsufficientData, build_snapshot
from hedge_fund.llm import LLMClient, PromptCache, extract_json, make_llm, prompt_key
from hedge_fund.models import Signal
from hedge_fund.signals.base import AlphaModel

logger = logging.getLogger(__name__)

# What the model must return; folded into Signal.value below.
_SIGNAL_TO_SIGN = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}


class LLMAgent(AlphaModel):
    """Base for persona agents. Subclasses define `name` and `get_system_prompt`."""

    def __init__(
        self,
        llm: LLMClient | None = None,
        cache: PromptCache | None = None,
    ) -> None:
        self._llm = llm if llm is not None else make_llm()
        self._cache = cache if cache is not None else PromptCache()

    # ------------------------------------------------------------------
    # AlphaModel interface
    # ------------------------------------------------------------------

    def predict(self, ticker: str, date: str, data_client: DataClient) -> Signal:
        try:
            snapshot = self.build_snapshot(ticker, date, data_client)
        except InsufficientData as exc:
            return self._abstain(ticker, date, f"insufficient data: {exc}")
        # Any other data-layer exception (e.g. FDClientError) propagates.

        return self.predict_snapshot(ticker, date, snapshot)

    @property
    def model_identity(self) -> str:
        provider = getattr(self._llm, "provider", "unknown")
        return getattr(self._llm, "identity", f"{provider}:{self._llm.model}")

    @property
    def prompt_identity(self) -> str:
        payload = f"{self.name}|{type(self).__qualname__}|{self.get_system_prompt()}"
        return hashlib.sha256(payload.encode()).hexdigest()[:24]

    def predict_snapshot(
        self,
        ticker: str,
        date: str,
        snapshot: FundamentalsSnapshot,
        event_context: dict | None = None,
    ) -> Signal:
        """Analyze a prepared snapshot, optionally with point-in-time event context."""
        system = self.get_system_prompt()
        user = self.build_user_prompt(snapshot, event_context)
        provider = getattr(self._llm, "provider", "unknown")
        identity = self.model_identity
        key = prompt_key(self.name, identity, system, user)

        cached = self._cache.get(key)
        if cached is not None and "parsed" in cached:
            return self._to_signal(ticker, date, cached["parsed"], key, snapshot, cached=True)

        try:
            response = self._llm.complete(system, user)
        except Exception as exc:
            failure = classify_llm_failure(exc)
            logger.warning(
                "%s LLM call failed for %s@%s (%s)",
                self.name, ticker, date, failure.category,
            )
            return self._failed(ticker, date, failure)

        record = {
            "agent": self.name,
            "provider": provider,
            "model": self._llm.model,
            "model_identity": identity,
            "ticker": ticker,
            "as_of": date,
            "snapshot_hash": snapshot.content_hash,
            "system": system,
            "user": user,
            "response": response,
        }

        try:
            parsed = self._parse(response)
        except Exception as exc:
            # Persist the raw response even when unparseable — the debug trail.
            self._cache.put(key, {**record, "parse_error": str(exc)})
            logger.warning("%s parse failed for %s@%s: %s", self.name, ticker, date, exc)
            return self._failed_response(ticker, date)

        self._cache.put(key, {**record, "parsed": parsed})
        return self._to_signal(ticker, date, parsed, key, snapshot, cached=False)

    # ------------------------------------------------------------------
    # Subclass surface
    # ------------------------------------------------------------------

    def get_system_prompt(self) -> str:
        """The persona — every subclass must define its voice."""
        raise NotImplementedError(f"{type(self).__name__} must define get_system_prompt()")

    def build_snapshot(self, ticker: str, date: str, data_client: DataClient) -> FundamentalsSnapshot:
        """What this persona is allowed to know. Default: the shared
        point-in-time fundamentals snapshot — right for value/quality
        personas. Override for personas that reason over different data
        (macro, news); when a second snapshot TYPE exists, extract the
        implicit interface (ticker/as_of/content_hash/render) into a
        Protocol — not before."""
        return build_snapshot(ticker, date, data_client)

    def build_user_prompt(
        self, snapshot: FundamentalsSnapshot, event_context: dict | None = None,
    ) -> str:
        """Default user prompt: the rendered snapshot. Override to enrich."""
        prompt = snapshot.render()
        if not event_context:
            return prompt
        context = json.dumps(event_context, sort_keys=True, separators=(",", ":"))
        return f"{prompt}\n\nPoint-in-time event context:\n{context}"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse(self, response: str) -> dict:
        """Extract + validate {signal, confidence, reasoning}."""
        data = extract_json(response)
        signal = str(data.get("signal", "")).lower()
        if signal not in _SIGNAL_TO_SIGN:
            raise ValueError(f"invalid signal {data.get('signal')!r}")
        confidence = float(data.get("confidence", 0))
        if not 0 <= confidence <= 100:
            raise ValueError(f"confidence out of range: {confidence}")
        return {
            "signal": signal,
            "confidence": confidence,
            "reasoning": str(data.get("reasoning", "")),
        }

    def _to_signal(
        self,
        ticker: str,
        date: str,
        parsed: dict,
        key: str,
        snapshot: FundamentalsSnapshot,
        cached: bool,
    ) -> Signal:
        value = _SIGNAL_TO_SIGN[parsed["signal"]] * parsed["confidence"] / 100.0
        return Signal(
            model_name=self.name,
            ticker=ticker,
            date=date,
            value=value,
            status="produced",
            reasoning=parsed["reasoning"],
            metadata={
                "signal": parsed["signal"],
                "confidence": parsed["confidence"],
                "model": self._llm.model,
                "prompt_key": key,
                "snapshot_hash": snapshot.content_hash,
                "cached": cached,
                "abstained": False,
                "failed": False,
            },
        )

    def _abstain(self, ticker: str, date: str, reason: str) -> Signal:
        return Signal(
            model_name=self.name,
            ticker=ticker,
            date=date,
            value=0.0,
            status="abstained",
            failure={
                "category": "insufficient_data",
                "message": reason,
                "retryable": False,
            },
            reasoning=f"abstained: {reason}",
            metadata={
                "abstained": True,
                "failed": False,
                "abstain_reason": reason,
                "cached": False,
            },
        )

    def _failed(self, ticker: str, date: str, failure) -> Signal:
        return Signal(
            model_name=self.name,
            ticker=ticker,
            date=date,
            value=0.0,
            status="failed",
            failure=failure,
            reasoning=f"failed: {failure.message}",
            metadata={
                "abstained": False,
                "failed": True,
                "failure_category": failure.category,
                "cached": False,
            },
        )

    def _failed_response(self, ticker: str, date: str) -> Signal:
        from hedge_fund.models import FailureDetail

        return self._failed(
            ticker,
            date,
            FailureDetail(
                category="invalid_response",
                message="LLM response could not be parsed as a valid signal",
                retryable=True,
            ),
        )
