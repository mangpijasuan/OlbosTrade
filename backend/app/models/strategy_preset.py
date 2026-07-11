"""
Verified strategy preset model.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StrategyPreset(Base):
    __tablename__ = "strategy_presets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    preset_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    strategy_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    preset_name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")

    market_regime_requirements: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    volatility_requirements: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    timeframe: Mapped[str] = mapped_column(String(40), nullable=False)
    entry_rules: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    exit_rules: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    risk_rules: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    position_sizing_policy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confidence_threshold: Mapped[float] = mapped_column(nullable=False, default=0.65)
    event_risk_restrictions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    max_allocation_pct: Mapped[float] = mapped_column(nullable=False, default=0.05)
    risk_profile_compatibility: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    validation_status: Mapped[str] = mapped_column(String(40), nullable=False, default="paper_validated")
    paper_validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    live_validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    author: Mapped[str] = mapped_column(String(120), nullable=False, default="OlbosTrade")
    approval_owner: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    approval_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approved_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
