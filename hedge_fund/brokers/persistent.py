"""PersistentBroker — SQLite-backed broker for long-running simulated trading.

Stores every fill in the trade_log table so positions and P&L survive restarts.
Implements the Broker protocol exactly like SimBroker, but derives state from
the database instead of in-memory dicts.
"""

from __future__ import annotations

from hedge_fund.brokers.models import Fill, Order, Position
from hedge_fund.persistence.database import get_session, init_db
from hedge_fund.persistence.repository import LedgerRepository


class PersistentBroker:
    """A broker that persists trades to SQLite.

    Usage::

        broker = PersistentBroker(cash=100_000, db_path="fund.db")
        broker.place_order(Order(ticker="AAPL", side="buy", quantity=10, price=150.0))
        positions = broker.positions()  # derived from trade_log
    """

    def __init__(
        self,
        cash: float,
        db_path: str = "fund.db",
        fee_rate: float = 0.001,
    ) -> None:
        self._fee_rate = fee_rate
        self._initial_cash = cash
        self._db_path = db_path
        self._last_trades: list[dict] = []
        init_db(db_path)

    # ------------------------------------------------------------------
    # Broker protocol
    # ------------------------------------------------------------------

    def positions(self) -> dict[str, Position]:
        """Current signed share counts derived from trade_log."""
        with get_session(self._db_path) as session:
            repo = LedgerRepository(session)
            pos_dict = repo.get_current_positions()
            return {
                ticker: Position(ticker=ticker, shares=data["shares"])
                for ticker, data in pos_dict.items()
            }

    def cash(self) -> float:
        """Current cash balance: initial capital minus net trade spend."""
        with get_session(self._db_path) as session:
            repo = LedgerRepository(session)
            trades = repo.get_all_trades()
            spent = sum(t.total_amount for t in trades if t.side == "BUY")
            received = sum(t.total_amount for t in trades if t.side == "SELL")
            return self._initial_cash - spent + received

    def place_order(self, order: Order, cycle_date: str | None = None) -> Fill:
        """Execute an order, deduct fee, and persist to trade_log."""
        gross = order.quantity * order.price
        fee = gross * self._fee_rate

        if cycle_date is None:
            from datetime import date as _date
            cycle_date = _date.today().isoformat()

        with get_session(self._db_path) as session:
            repo = LedgerRepository(session)
            if order.side == "buy":
                total_amount = gross + fee
            else:
                total_amount = gross - fee

            trade = repo.save_trade(
                ticker=order.ticker,
                side=order.side.upper(),
                quantity=order.quantity,
                price=order.price,
                fee=fee,
                total_amount=total_amount,
                cycle_date=cycle_date,
            )

            self._last_trades.append({
                "ticker": trade.ticker,
                "side": trade.side,
                "quantity": trade.quantity,
                "price": trade.price,
                "fee": trade.fee,
                "total_amount": trade.total_amount,
                "cycle_date": trade.cycle_date,
            })

            return Fill(
                ticker=order.ticker,
                side=order.side,
                quantity=order.quantity,
                price=order.price,
                fee=fee,
                total_amount=total_amount,
            )

    # ------------------------------------------------------------------
    # Ledger helpers
    # ------------------------------------------------------------------

    def get_repository(self) -> LedgerRepository:
        """Return a LedgerRepository for a new session. Caller must close session."""
        session = get_session(self._db_path)
        return LedgerRepository(session)

    def save_nav_snapshot(
        self,
        nav: float,
        marks: dict[str, float],
        cycle_date: str | None = None,
    ) -> None:
        """Persist current NAV and position snapshot to the database."""
        if cycle_date is None:
            from datetime import date as _date
            cycle_date = _date.today().isoformat()

        with get_session(self._db_path) as session:
            repo = LedgerRepository(session)
            repo.save_nav_snapshot(
                cycle_date=cycle_date,
                nav=nav,
                cash=self.cash(),
                equity=nav - self.cash(),
                positions=repo.get_current_positions(),
                marks=marks,
            )
