"""
SQLAlchemy model for journal_entries.
Tracks pre/post trade psychology, tags, and loss analysis.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trade_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trades.id", ondelete="SET NULL"), nullable=True
    )

    # Pre-trade psychology
    pre_trade_thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_level: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="1–5 scale"
    )
    market_context: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Post-trade review
    post_trade_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    followed_rules: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    exit_felt_right: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Tagging
    tags: Mapped[list | None] = mapped_column(
        JSONB, nullable=True,
        comment="high-iv | low-iv | trending | range-bound | earnings-nearby | "
                "vix-spike | fed-day | oversold | overbought | gap-up | gap-down"
    )

    # Loss analysis
    loss_category: Mapped[str | None] = mapped_column(
        String(30), nullable=True,
        comment="bad-signal | good-signal-luck | rule-breach | black-swan"
    )
    mistake_tags: Mapped[list | None] = mapped_column(
        JSONB, nullable=True,
        comment="overrode-exit | ignored-kill-switch | sized-too-big | "
                "chased-entry | held-too-long"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )
