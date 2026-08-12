"""SimBroker — deterministic simulated broker for backtests.

Fills every order completely, exactly at the order's reference price. That
determinism is the point: given the same orders, a backtest replays to the
same book. Slippage/costs are a declared future addition inside place_order,
where they change fills without touching the pipeline.

Margin is not modeled: cash may go negative and stays visible. With an
unlevered mandate (gross_target <= 1), sells-before-buys ordering, and
floor-toward-zero sizing, a long book won't get there — but nothing here
pretends to enforce it.
"""

from __future__ import annotations

from v2.brokers.models import Fill, Order, Position


class SimBroker:
    """In-memory broker: signed positions plus a cash balance."""

    def __init__(self, cash: float, fee_rate: float = 0.001) -> None:
        self._cash = cash
        self._shares: dict[str, int] = {}
        self._fee_rate = fee_rate
        self._last_trades: list[dict] = []

    def positions(self) -> dict[str, Position]:
        return {
            t: Position(ticker=t, shares=s)
            for t, s in self._shares.items()
            if s != 0
        }

    def cash(self) -> float:
        return self._cash

    def place_order(self, order: Order, cycle_date: str | None = None) -> Fill:
        if order.price <= 0:
            raise ValueError(
                f"cannot fill {order.ticker} at price {order.price} — "
                "the caller must price every order"
            )

        gross = order.quantity * order.price
        fee = gross * self._fee_rate

        if order.side == "buy":
            self._shares[order.ticker] = self._shares.get(order.ticker, 0) + order.quantity
            total_amount = gross + fee
            self._cash -= total_amount
        else:
            self._shares[order.ticker] = self._shares.get(order.ticker, 0) - order.quantity
            total_amount = gross - fee
            self._cash += total_amount

        if self._shares[order.ticker] == 0:
            del self._shares[order.ticker]

        fill = Fill(
            ticker=order.ticker,
            side=order.side,
            quantity=order.quantity,
            price=order.price,
            fee=fee,
            total_amount=total_amount,
        )
        self._last_trades.append({
            "ticker": order.ticker, "side": order.side.upper(),
            "quantity": order.quantity, "price": order.price, "fee": fee,
            "total_amount": total_amount, "cycle_date": cycle_date or "",
        })
        return fill
