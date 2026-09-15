"""SQLAlchemy ORM models for the fund ledger."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TradeLog(Base):
    """Every buy/sell order that was executed. Append-only.

    Current holdings are computed via aggregation:
        SELECT ticker, SUM(CASE side WHEN 'BUY' THEN quantity ELSE -quantity END) AS net
        FROM trade_log GROUP BY ticker HAVING net != 0
    """

    __tablename__ = "trade_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    cycle_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    created_at: Mapped[str] = mapped_column(
        String(26), nullable=False, default=lambda: datetime.now(timezone.utc).isoformat()
    )

    __table_args__ = (
        CheckConstraint("side IN ('BUY', 'SELL')", name="ck_trade_log_side"),
    )


class NavSnapshot(Base):
    """Portfolio NAV recorded at the end of each cycle. Used for P&L chart."""

    __tablename__ = "nav_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cycle_date: Mapped[str] = mapped_column(String(10), nullable=False, unique=True, index=True)
    nav: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[str] = mapped_column(
        String(26), nullable=False, default=lambda: datetime.now(timezone.utc).isoformat()
    )

    positions: Mapped[list["PositionSnapshot"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class PositionSnapshot(Base):
    """Holdings detail for a single ticker at a specific cycle end."""

    __tablename__ = "position_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nav_snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("nav_snapshot.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    market_price: Mapped[float] = mapped_column(Float, nullable=False)
    market_value: Mapped[float] = mapped_column(Float, nullable=False)

    snapshot: Mapped[NavSnapshot] = relationship(back_populates="positions")

    __table_args__ = (
        UniqueConstraint("nav_snapshot_id", "ticker", name="uq_position_snapshot"),
    )


# ---------------------------------------------------------------------------
# Data cache for backtest / simulation
# ---------------------------------------------------------------------------


class PriceCache(Base):
    """Daily OHLCV for a single ticker, fetched from yfinance / FD API."""

    __tablename__ = "price_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(
        String(26), nullable=False, default=lambda: datetime.now(timezone.utc).isoformat()
    )

    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_price_cache"),
    )


class MetricsCache(Base):
    """Historical financial metrics (one row per quarterly filing)."""

    __tablename__ = "metrics_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    report_period: Mapped[str] = mapped_column(String(10), nullable=False)
    filing_date: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    filing_date_source: Mapped[str] = mapped_column(String(32), nullable=False, default="estimated_45d")
    data: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(
        String(26), nullable=False, default=lambda: datetime.now(timezone.utc).isoformat()
    )

    __table_args__ = (
        UniqueConstraint("ticker", "report_period", name="uq_metrics_cache"),
    )


class EarningsCache(Base):
    """Point-in-time earnings announcement and EPS surprise."""

    __tablename__ = "earnings_cache"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    report_period: Mapped[str] = mapped_column(String(10), nullable=False)
    announcement_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    actual_eps: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_eps: Mapped[float | None] = mapped_column(Float, nullable=True)
    surprise_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="yahoo")
    created_at: Mapped[str] = mapped_column(String(26), nullable=False, default=lambda: datetime.now(timezone.utc).isoformat())
    __table_args__ = (
        UniqueConstraint("ticker", "announcement_date", name="uq_earnings_cache"),
    )


# ---------------------------------------------------------------------------
# Simulation run records
# ---------------------------------------------------------------------------


class SimRun(Base):
    """Metadata for a single backtest simulation run."""

    __tablename__ = "sim_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    tickers: Mapped[str] = mapped_column(Text, nullable=False)
    benchmark: Mapped[str | None] = mapped_column(String(10), nullable=True, default=None)
    llm_provider: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    llm_protocol: Mapped[str | None] = mapped_column(String(40), nullable=True, default=None)
    llm_model: Mapped[str | None] = mapped_column(String(200), nullable=True, default=None)
    llm_connection_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    llm_connection_name: Mapped[str | None] = mapped_column(String(100), nullable=True, default=None)
    llm_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    start_date: Mapped[str] = mapped_column(String(10), nullable=False)
    end_date: Mapped[str] = mapped_column(String(10), nullable=False)
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    current_day: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    final_nav: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(26), nullable=True)
    warnings: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    models: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    persona_refresh_policy: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[str] = mapped_column(
        String(26), nullable=False, default=lambda: datetime.now(timezone.utc).isoformat()
    )


class SimTradeLog(Base):
    """Trade records generated during a simulation run."""

    __tablename__ = "sim_trade_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sim_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sim_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    cycle_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    created_at: Mapped[str] = mapped_column(
        String(26), nullable=False, default=lambda: datetime.now(timezone.utc).isoformat()
    )

    __table_args__ = (
        CheckConstraint("side IN ('BUY', 'SELL')", name="ck_sim_trade_log_side"),
    )


class SimNavSnapshot(Base):
    """NAV snapshot for a single day within a simulation run."""

    __tablename__ = "sim_nav_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sim_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sim_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cycle_date: Mapped[str] = mapped_column(String(10), nullable=False)
    nav: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    benchmark_nav: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    created_at: Mapped[str] = mapped_column(
        String(26), nullable=False, default=lambda: datetime.now(timezone.utc).isoformat()
    )

    __table_args__ = (
        UniqueConstraint("sim_run_id", "cycle_date", name="uq_sim_nav_snapshot"),
    )


class SimCycleRecord(Base):
    """Complete serialized decision record, or a categorized failed attempt."""

    __tablename__ = "sim_cycle_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sim_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sim_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cycle_number: Mapped[int] = mapped_column(Integer, nullable=False)
    signal_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    execution_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    universe: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cash: Mapped[float | None] = mapped_column(Float, nullable=True)
    nav: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[str] = mapped_column(
        String(26), nullable=False, default=lambda: datetime.now(timezone.utc).isoformat()
    )

    __table_args__ = (
        UniqueConstraint("sim_run_id", "cycle_number", name="uq_sim_cycle_number"),
        CheckConstraint("status IN ('completed', 'failed')", name="ck_sim_cycle_status"),
    )


class SimCycleTickerIndex(Base):
    """Compact ticker index for cycle filtering; details remain in payload."""

    __tablename__ = "sim_cycle_ticker_index"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sim_cycle_record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sim_cycle_record.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sim_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sim_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    produced_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    neutral_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    abstained_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refresh_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fill_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("sim_cycle_record_id", "ticker", name="uq_sim_cycle_ticker"),
    )


class SimPersonaState(Base):
    """Latest effective persona opinion, isolated to one simulation timeline."""

    __tablename__ = "sim_persona_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sim_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sim_run.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    persona: Mapped[str] = mapped_column(String(80), nullable=False)
    model_identity: Mapped[str] = mapped_column(String(300), nullable=False)
    prompt_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    signal_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_signal_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    valuation_anchor: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_filing_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    latest_earnings_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    pending_event_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_cycle: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_failure_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_failure_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[str] = mapped_column(
        String(26), nullable=False, default=lambda: datetime.now(timezone.utc).isoformat(),
    )

    __table_args__ = (
        UniqueConstraint(
            "sim_run_id", "ticker", "persona", "model_identity", "prompt_identity",
            name="uq_sim_persona_state_identity",
        ),
    )
