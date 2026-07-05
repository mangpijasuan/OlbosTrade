"""
SQLAlchemy models for Smart Alerts and the Notification Center.

AlertRule stores a user's rule (predicates as JSON, mode, cooldown). Notification
stores delivered in-app notifications. Neither model touches execution — an
alert firing creates a notification/candidate record, never an order.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    predicates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    mode: Mapped[str] = mapped_column(String(12), nullable=False, default="manual")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cooldown_min: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)     # alert | daily_brief | risk | order | data
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(String(600), nullable=False, default="")
    severity: Mapped[str] = mapped_column(String(12), nullable=False, default="info")  # info|warning|critical
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
