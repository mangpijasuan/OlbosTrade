"""
SQLAlchemy model for portfolio_greeks_snapshots (created in migration 0003).

Previously this table existed in the DB but had no ORM model.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PortfolioGreeksSnapshot(Base):
    __tablename__ = "portfolio_greeks_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    net_delta: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    net_vega: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    net_theta: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    equity_position_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    options_position_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_position_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
