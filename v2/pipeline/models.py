"""Pipeline records — the serialized truth of every cycle.

A CycleRecord captures one tick of the fund end to end: what the analysts
saw, what they said, how views became weights, what risk clamped, what was
ordered and filled, and what the book looks like after. The ledger persists
these; `fund why AAPL` will answer from them alone.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from v2.brokers.models import Fill, Order
from v2.fund.spec import FundSpec
from v2.models import Signal
from v2.risk.limits import ClampEvent


class TickerSkip(BaseModel):
    """A universe name that could not be traded this cycle, and why."""

    ticker: str
    reason: str


class StrategyRecord(BaseModel):
    """One strategy's slice of a cycle: its analysts' views and its sleeve."""

    name: str
    slice: float                        # normalized capital slice of the fund
    signals: list[Signal]               # this strategy's analysts x tradeable tickers
    convictions: dict[str, float]       # blended views, pre-scaling
    weights: dict[str, float]           # the sleeve, before netting across strategies


class PersonaEventRecord(BaseModel):
    """One effective persona decision and the event attempt behind it."""

    ticker: str
    persona: str
    model_identity: str
    prompt_identity: str
    provenance: Literal["refreshed", "reused", "expired", "unavailable"]
    trigger_reasons: list[str] = Field(default_factory=list)
    source_signal_date: str | None = None
    age_days: int | None = None
    attempt_status: Literal["not_attempted", "produced", "failed", "abstained"]
    failure: dict | None = None
    prompt_key: str | None = None
    snapshot_hash: str | None = None
    valuation_anchor: float | None = None
    latest_filing_date: str | None = None
    latest_earnings_date: str | None = None
    event_fingerprint: str | None = None
    failure_count: int = 0
    next_retry_cycle: int | None = None
    effective_signal: Signal | None = None


class CycleRecord(BaseModel):
    """One tick of the fund, fully serialized — every stage's inputs and
    outputs. `model_dump_json()` round-trips; nothing about a decision
    lives anywhere else."""

    fund: str
    as_of: str
    execution_date: str | None = None
    spec: FundSpec                      # self-contained audit copy
    universe: list[str]                 # effective run-time universe for this cycle
    marks: dict[str, float]             # ticker -> T close used for signal sizing
    execution_prices: dict[str, float]  # ticker -> exact price eligible for execution
    valuation_prices: dict[str, float]  # ticker -> close used for ending NAV
    skipped: list[TickerSkip]
    strategies: list[StrategyRecord]    # every sleeve, incl. each thesis
    persona_events: list[PersonaEventRecord] = Field(default_factory=list)
    target_weights: dict[str, float]    # the NETTED book, pre-risk
    clamps: list[ClampEvent]
    final_weights: dict[str, float]     # post-risk
    equity_before: float
    cash_before: float
    orders: list[Order]
    fills: list[Fill]
    positions: dict[str, int]           # signed shares after fills
    cash: float
    nav: float                          # cash + sum(shares * mark)
