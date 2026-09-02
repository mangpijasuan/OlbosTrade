"""
portfolio_snapshots — point-in-time account state snapshots.
guardrail_events   — log of every guardrail trigger.
risk_peak_state    — singleton row tracking the all-time portfolio peak.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    total_value: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)

    # Portfolio Greeks
    net_delta: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6), nullable=True)
    net_theta: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6), nullable=True)
    net_vega: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6), nullable=True)

    open_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # P&L windows
    daily_pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    weekly_pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    monthly_pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)

    # Guardrail state
    trading_mode: Mapped[str] = mapped_column(
        String(30), nullable=False, default="normal",
        comment="normal | capital_preservation | suspended"
    )
    consecutive_losses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trades_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cooling_off_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GuardrailEvent(Base):
    __tablename__ = "guardrail_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="daily_loss_limit | weekly_loss_limit | monthly_loss_limit | "
                "consecutive_losses | cooling_off | capital_preservation | trade_cap"
    )
    trigger_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6), nullable=True)
    limit_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6), nullable=True)
    trading_suspended_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    portfolio_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class RiskPeakState(Base):
    """Singleton row (id=1) tracking the portfolio's all-time peak value
    for the Drawdown Control guardrail. Updated in place — unlike
    PortfolioSnapshot/GuardrailEvent this never accumulates history rows.
    Deliberately not built on portfolio_snapshots (its writer is dead
    code, never called anywhere in the app — out of scope here)."""
    __tablename__ = "risk_peak_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    peak_value: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
