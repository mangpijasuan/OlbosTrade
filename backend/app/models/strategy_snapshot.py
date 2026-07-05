"""
Versioned strategy configuration snapshot model.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StrategySnapshot(Base):
    __tablename__ = "strategy_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    snapshot_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    strategy_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    preset_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_presets.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_profile: Mapped[str] = mapped_column(String(40), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(40), nullable=False, default="paper_validated")
    validation_status: Mapped[str] = mapped_column(String(40), nullable=False, default="inherited")
    config_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    inherited_from_verified_preset: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="OlbosQuant")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
