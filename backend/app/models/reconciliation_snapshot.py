"""
Persisted reconciliation snapshots.

Stores the latest broker-vs-DB drift status so the terminal can surface
operational truth instead of relying on log inspection alone.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ReconciliationSnapshot(Base):
    __tablename__ = "reconciliation_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="clean | warning | error"
    )
    clean: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, default="system",
        comment="cycle_preflight | operator | startup | api"
    )
    broker_name: Mapped[str] = mapped_column(String(40), nullable=False)
    broker_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    db_open_trade_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    untracked_at_broker: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    phantom_in_db: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    quantity_mismatches: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )
