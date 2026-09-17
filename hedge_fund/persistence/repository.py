"""Repository — CRUD operations for the fund ledger."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from hedge_fund.persistence.models import NavSnapshot, PositionSnapshot, TradeLog


class LedgerRepository:
    """High-level data access for fund accounting."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    def save_trade(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        fee: float,
        total_amount: float,
        cycle_date: str,
    ) -> TradeLog:
        trade = TradeLog(
            ticker=ticker,
            side=side,
            quantity=quantity,
            price=price,
            fee=fee,
            total_amount=total_amount,
            cycle_date=cycle_date,
        )
        self._session.add(trade)
        self._session.commit()
        return trade

    def get_trades(
        self,
        ticker: str | None = None,
        cycle_date: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TradeLog]:
        stmt = select(TradeLog).order_by(TradeLog.created_at.desc())
        if ticker:
            stmt = stmt.where(TradeLog.ticker == ticker)
        if cycle_date:
            stmt = stmt.where(TradeLog.cycle_date == cycle_date)
        return list(self._session.execute(stmt.limit(limit).offset(offset)).scalars())

    def get_all_trades(self) -> list[TradeLog]:
        return list(
            self._session.execute(
                select(TradeLog).order_by(TradeLog.created_at.desc())
            ).scalars()
        )

    # ------------------------------------------------------------------
    # Positions (derived from trade_log)
    # ------------------------------------------------------------------

    def get_current_positions(self) -> dict[str, dict]:
        """Derive current positions by aggregating trade_log.

        Returns a dict of ticker -> {shares, avg_cost}.
        Positions with zero net shares are excluded.
        """
        _net = func.sum(
            case(
                (TradeLog.side == "BUY", TradeLog.quantity),
                else_=-TradeLog.quantity,
            )
        )
        _cost = func.sum(
            case(
                (TradeLog.side == "BUY", TradeLog.total_amount),
                else_=0.0,
            )
        )
        _buys = func.sum(
            case(
                (TradeLog.side == "BUY", TradeLog.quantity),
                else_=0,
            )
        )
        stmt = (
            select(TradeLog.ticker, _net.label("net_shares"), _cost.label("total_cost"), _buys.label("total_buys"))
            .group_by(TradeLog.ticker)
            .having(_net != 0)
        )
        rows = self._session.execute(stmt).all()
        result = {}
        for row in rows:
            ticker, net_shares, total_cost, total_buys = row
            avg_cost = total_cost / total_buys if total_buys > 0 else 0.0
            result[ticker] = {"shares": int(net_shares), "avg_cost": avg_cost}
        return result

    def get_current_cash(self, initial_capital: float = 0.0) -> float:
        """Derive current cash balance from trade_log.

        total_amount is always positive; direction comes from side:
          - BUY: cash decreases by total_amount
          - SELL: cash increases by total_amount
        """
        stmt = select(TradeLog)
        trades = self._session.execute(stmt).scalars().all()
        spent = sum(t.total_amount for t in trades if t.side == "BUY")
        received = sum(t.total_amount for t in trades if t.side == "SELL")
        return initial_capital - spent + received

    # ------------------------------------------------------------------
    # NAV snapshots
    # ------------------------------------------------------------------

    def save_nav_snapshot(
        self,
        cycle_date: str,
        nav: float,
        cash: float,
        equity: float,
        positions: dict[str, dict],
        marks: dict[str, float],
    ) -> NavSnapshot:
        snapshot = NavSnapshot(
            cycle_date=cycle_date,
            nav=nav,
            cash=cash,
            equity=equity,
        )
        self._session.add(snapshot)
        self._session.flush()

        for ticker, pos in positions.items():
            shares = pos["shares"]
            self._session.add(
                PositionSnapshot(
                    nav_snapshot_id=snapshot.id,
                    ticker=ticker,
                    shares=shares,
                    market_price=marks.get(ticker, 0.0),
                    market_value=shares * marks.get(ticker, 0.0),
                )
            )

        self._session.commit()
        return snapshot

    def get_nav_history(self, limit: int = 365) -> list[NavSnapshot]:
        stmt = (
            select(NavSnapshot)
            .order_by(NavSnapshot.cycle_date.desc())
            .limit(limit)
        )
        return list(self._session.execute(stmt).scalars())

    def get_nav_snapshot_by_date(self, cycle_date: str) -> NavSnapshot | None:
        stmt = select(NavSnapshot).where(NavSnapshot.cycle_date == cycle_date)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_position_snapshots(self, nav_snapshot_id: int) -> list[PositionSnapshot]:
        stmt = select(PositionSnapshot).where(
            PositionSnapshot.nav_snapshot_id == nav_snapshot_id
        )
        return list(self._session.execute(stmt).scalars())

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self) -> dict:
        """Return a dashboard-ready summary of the fund."""
        positions = self.get_current_positions()
        nav_history = self.get_nav_history(limit=2)
        all_trades = self.get_all_trades()

        current_nav = nav_history[-1].nav if nav_history else 0.0
        current_cash = nav_history[-1].cash if nav_history else 0.0
        prev_nav = nav_history[-2].nav if len(nav_history) >= 2 else None

        total_spent = sum(t.total_amount for t in all_trades if t.side == "BUY")
        total_received = sum(t.total_amount for t in all_trades if t.side == "SELL")
        realized_pnl = total_received - total_spent

        return {
            "nav": current_nav,
            "cash": current_cash,
            "equity": current_nav - current_cash,
            "prev_nav": prev_nav,
            "pnl_total": realized_pnl + (current_nav - (prev_nav or current_nav)),
            "position_count": len(positions),
            "trade_count": len(all_trades),
            "positions": positions,
        }
