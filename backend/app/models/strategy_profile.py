"""
Strategy registry model.

Stores the lifecycle, compatibility, and operator-facing metadata for each
strategy the platform knows about. This is the backbone for Strategy Cards and
Autopilot eligibility enforcement.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StrategyProfile(Base):
    __tablename__ = "strategy_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    asset_class: Mapped[str] = mapped_column(String(40), nullable=False)

    supported_symbols: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    supported_regimes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    supported_volatility_regimes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    risk_profile_compatibility: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    manual_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    copilot_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    autopilot_supported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    lifecycle_status: Mapped[str] = mapped_column(String(40), nullable=False, default="research_only")
    health_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    last_validation_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    allocation_limit_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 3), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    main_risk_warning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    validation_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    performance_link: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    snapshots_link: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )
