"""
SQLAlchemy model for the trades table.
Records every opened and closed options spread trade.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, Enum, Float, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="bull_put_spread | bear_call_spread | iron_condor | bull_call_debit_spread"
    )
    underlying: Mapped[str] = mapped_column(String(10), nullable=False)
    spread_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Strikes
    short_strike: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    long_strike: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    short_strike_2: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    long_strike_2: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)

    expiration: Mapped[date] = mapped_column(Date, nullable=False)
    entry_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # P&L
    credit_received: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    cost_to_close: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    pnl_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", index=True,
        comment="open | closed | expired"
    )
    exit_reason: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True,
        comment="profit_target | stop_loss | expiration | manual | dte_exit"
    )

    # Quantity and mode
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=1)
    trading_mode_at_entry: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # AI & execution
    signal_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    commission_paid: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    fill_price_short: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    fill_price_long: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)

    # Unified equity/options fields (added in migration 0003 — previously
    # present in the DB but missing from this model, so this data was
    # unreadable via the ORM and autogenerate wanted to drop the columns).
    instrument_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="option", server_default="option",
        comment="equity | option"
    )
    broker_used: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    signal_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    orderflow_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    iv_overlay_boost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    regime_at_entry: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    kelly_fraction_used: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )
