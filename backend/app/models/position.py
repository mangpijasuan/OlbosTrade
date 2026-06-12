"""
SQLAlchemy model for the positions table.
Tracks live Greeks and unrealized P&L for open trades.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trades.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open",
        comment="open | closed"
    )
    current_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)

    # Greeks
    delta: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6), nullable=True)
    gamma: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6), nullable=True)
    theta: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6), nullable=True)
    vega: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6), nullable=True)

    unrealized_pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    days_in_trade: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    risk_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    risk_flags: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )
