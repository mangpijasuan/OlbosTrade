"""
SQLAlchemy model for the daily_signal_snapshots table.

A frozen, once-per-day record of what the desk was actually saying at a fixed
decision time — the top 3 BUY and top 3 SELL by opportunity_score, captured at
10:00 ET and never rewritten.

**Why it exists as its own table rather than a query over signal_outcomes.**
The scanner re-records the same (ticker, action, day) roughly 45 times as it
re-scores through the session. Ranking retrospectively would pick whichever
version of each signal happened to score highest, including signals that only
surfaced late in the day after the move had already happened. The resulting
record would flatter the desk — the same shape of dishonesty as measuring
portfolio heat off notional, or showing a model's POP without the empirical
hit rate beside it.

Freezing at a fixed time is what makes this a track record instead of
hindsight: it captures what was on screen when the operator could have acted.

Immutable by contract. `capture_daily_snapshot()` refuses to write a second
time for a date that already has rows, and nothing updates them afterward.
Resolution is joined on later from signal_outcomes rather than copied in, so
this table never needs a second write.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DailySignalSnapshot(Base):
    __tablename__ = "daily_signal_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # The ET trading date this snapshot belongs to. Stored as a plain date so
    # a day is a day regardless of the server's timezone.
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(4), nullable=False, comment="BUY | SELL")
    rank: Mapped[int] = mapped_column(Integer, nullable=False, comment="1..3 within action")

    ticker: Mapped[str] = mapped_column(String(10), nullable=False)

    # Cross-reference to the signal_outcomes row this was ranked from, so
    # resolution (target_hit / stop_hit / expired) can be joined without
    # copying a mutable status into this immutable table.
    signal_outcome_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    signal_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # The ranking metric, stored so the ordering stays auditable even if
    # opportunity_score's definition changes later.
    opportunity_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)

    # The plan as it stood at capture time.
    entry_price:  Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    stop_price:   Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    target_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)

    regime: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # When the signal first appeared, vs when this snapshot froze it. Both are
    # kept: the gap between them is how stale the ranking was at capture.
    generated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # One row per (date, side, rank) — the constraint that makes a second
        # capture for the same day impossible rather than merely discouraged.
        UniqueConstraint("trade_date", "action", "rank", name="uq_daily_snapshot_slot"),
        Index("ix_daily_snapshot_date_action", "trade_date", "action"),
    )
