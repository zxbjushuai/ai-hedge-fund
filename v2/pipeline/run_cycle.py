"""run_cycle — one tick of the fund, the same code path in every mode.

    point-in-time data -> analysts -> blend -> risk -> execution -> record

This is the fund's heartbeat. A backtest is run_cycle in a loop over history
with a SimBroker; paper trading is the same loop on a live clock with a
PaperBroker; live is the same loop with a real broker. Only the clock and the
broker change — the pipeline never does.

run_cycle is the pipeline's only impure piece: it talks to the data client
and the broker. Every stage it delegates to (blend_signals, apply_limits,
build_orders) is a pure function. Determinism: given the same spec, date,
broker state, and data responses, the returned record is byte-identical —
with the one caveat that a cold LLM cache makes an agent's first live call
nondeterministic; the prompt cache makes every replay exact.

Notable behavior, chosen deliberately:
- Targets are the complete statement of the desired book. If every analyst
  abstains or goes neutral, the targets are all zero and the fund closes to
  flat. The record distinguishes `abstained` and `failed`, so an outer loop (the
  Day-5 daemon) can decide to skip a tick instead — that guard belongs
  outside the pipeline.
- A universe ticker with no price and no position is skipped (recorded, its
  analysts never called): unlisted/delisted names are normal in history.
  A HELD ticker with no price raises — a fund that cannot price its own
  book has an infrastructure problem, and its NAV would be a lie.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import timedelta
import math
from typing import TYPE_CHECKING

from v2.brokers.models import Fill
from v2.brokers.protocol import Broker
from v2.data.protocol import DataClient
from v2.fund.spec import Fund, normalize_universe
from v2.models import Signal
from v2.pipeline.execution import build_orders
from v2.pipeline.models import CycleRecord, StrategyRecord, TickerSkip
from v2.portfolio.construction import blend_signals
from v2.risk.limits import apply_limits
from v2.signals import LLMAgent

if TYPE_CHECKING:
    from v2.simulation.persona_state import PersonaSignalEngine

# How far back to look for the most recent close: covers weekends, holiday
# clusters, and short trading halts without reaching into stale history.
_MARK_LOOKBACK_DAYS = 7


def run_cycle(
    fund: Fund,
    as_of: str,
    broker: Broker,
    data_client: DataClient,
    execution_prices: dict[str, float] | None = None,
    valuation_prices: dict[str, float] | None = None,
    execution_date: str | None = None,
    universe: list[str] | None = None,
    persona_engine: PersonaSignalEngine | None = None,
    sizing_split_ratios: dict[str, float] | None = None,
) -> CycleRecord:
    """Run one tick of *fund* as of *as_of* (YYYY-MM-DD) and return the record."""
    spec = fund.spec
    effective_universe = normalize_universe(
        universe if universe is not None else (spec.universe or [])
    )
    held = broker.positions()

    marks, skipped = _mark_prices(
        sorted(set(effective_universe) | set(held)), as_of, held, data_client,
    )

    # Holdings may already reflect execution-day splits. Translate only sizing
    # marks to those share units; analysts must still see the historical T prices.
    sizing_marks = dict(marks)
    for ticker, ratio in (sizing_split_ratios or {}).items():
        if not math.isfinite(ratio) or ratio <= 0:
            raise ValueError(f"invalid sizing split ratio for {ticker}")
        if ticker in sizing_marks:
            sizing_marks[ticker] /= ratio
    cash_before = broker.cash()
    equity_before = cash_before + sum(
        p.shares * sizing_marks[t] for t, p in held.items()
    )
    if equity_before <= 0:
        raise ValueError(
            f"{spec.name}: equity is {equity_before:.2f} as of {as_of} — "
            "cannot size positions against a non-positive book"
        )

    tradeable = [t for t in effective_universe if t in marks]

    # Each strategy runs its own analysts and blends its own sleeve; the fund
    # nets the sleeves by capital slice. A persona staffed into two strategies
    # is asked twice, but the second ask is a prompt-cache hit, not spend.
    total_slice = sum(s.weight for s, _ in fund.strategies)
    strategy_records: list[StrategyRecord] = []
    netted: dict[str, float] = {t: 0.0 for t in tradeable}
    for strategy, staff in fund.strategies:
        signals: list[Signal] = []
        for ticker in tradeable:
            for model in staff:
                if persona_engine is not None and isinstance(model, LLMAgent):
                    signals.append(persona_engine.predict(
                        model, ticker, as_of, marks[ticker], data_client,
                    ))
                else:
                    signals.append(model.predict(ticker, as_of, data_client))
        blend = blend_signals(
            signals, strategy.model_weights, strategy.blend.gross_target,
            market_neutral=strategy.blend.market_neutral,
        )
        slice_ = strategy.weight / total_slice
        for ticker, weight in blend.weights.items():
            netted[ticker] += slice_ * weight
        strategy_records.append(StrategyRecord(
            name=strategy.name,
            slice=slice_,
            signals=signals,
            convictions=blend.convictions,
            weights=blend.weights,
        ))

    risk = apply_limits(netted, spec.risk)

    order_marks = marks if execution_prices is None else execution_prices
    order_tickers = set(risk.weights) | set(held)
    missing_execution = sorted(order_tickers - set(order_marks))
    for ticker in missing_execution:
        skipped.append(TickerSkip(
            ticker=ticker,
            reason=(
                f"no execution open on {execution_date or as_of}; "
                "order skipped and existing position unchanged"
            ),
        ))
    executable_weights = {
        ticker: weight for ticker, weight in risk.weights.items()
        if ticker in order_marks
    }
    executable_positions = {
        ticker: position for ticker, position in held.items()
        if ticker in order_marks
    }
    orders = build_orders(
        executable_weights, executable_positions, order_marks, equity_before,
    )
    fills: list[Fill] = [broker.place_order(o, cycle_date=execution_date or as_of) for o in orders]

    positions_after = {t: p.shares for t, p in broker.positions().items()}
    cash_after = broker.cash()
    nav_marks = marks if valuation_prices is None else valuation_prices
    missing = sorted(set(positions_after) - set(nav_marks))
    if missing:
        raise ValueError(f"cannot value positions without closing prices: {missing}")
    nav = cash_after + sum(s * nav_marks[t] for t, s in positions_after.items())

    return CycleRecord(
        fund=spec.name,
        as_of=as_of,
        execution_date=execution_date,
        spec=spec,
        universe=effective_universe,
        marks=marks,
        sizing_marks=sizing_marks,
        execution_prices=order_marks,
        valuation_prices=nav_marks,
        skipped=skipped,
        strategies=strategy_records,
        persona_events=(persona_engine.finish_cycle() if persona_engine else []),
        target_weights=netted,
        clamps=risk.clamps,
        final_weights=risk.weights,
        equity_before=equity_before,
        cash_before=cash_before,
        orders=orders,
        fills=fills,
        positions=positions_after,
        cash=cash_after,
        nav=nav,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _mark_prices(
    tickers: list[str],
    as_of: str,
    held: dict,
    data_client: DataClient,
) -> tuple[dict[str, float], list[TickerSkip]]:
    """Last close on or before *as_of* for each ticker, within the lookback.

    No bar and not held -> TickerSkip (the caller then never runs analysts
    on it). No bar but HELD -> raise: the book cannot be honestly valued.
    """
    start = (_date.fromisoformat(as_of) - timedelta(days=_MARK_LOOKBACK_DAYS)).isoformat()
    marks: dict[str, float] = {}
    skipped: list[TickerSkip] = []

    for ticker in tickers:
        prices = data_client.get_prices(ticker, start, as_of)
        bars = [p for p in prices if p.time[:10] <= as_of]
        if bars:
            marks[ticker] = max(bars, key=lambda p: p.time).close
        elif ticker in held:
            raise ValueError(
                f"held position {ticker} has no price within "
                f"{_MARK_LOOKBACK_DAYS} days of {as_of} — cannot value the book"
            )
        else:
            skipped.append(TickerSkip(
                ticker=ticker,
                reason=f"no close within {_MARK_LOOKBACK_DAYS} days of {as_of}",
            ))

    return marks, skipped
