"""
SQLAlchemy model for equity_signals (created in migration 0003).

Previously this table existed in the DB but had no ORM model, so autogenerate
would propose dropping it and the rows were unreadable through the ORM.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EquitySignal(Base):
    __tablename__ = "equity_signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    timeframe: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, server_default="1Day")
    action: Mapped[str] = mapped_column(String(10), nullable=False, comment="BUY | SELL | HOLD")
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rsi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_pct_b: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    atr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    stop_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    target_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    position_size: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4), nullable=True)
    risk_reward: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    orderflow_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    iv_overlay_boost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    earnings_gated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    regime_at_signal: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
