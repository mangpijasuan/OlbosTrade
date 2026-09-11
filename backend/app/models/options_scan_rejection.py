"""
SQLAlchemy model for options_scan_rejections.

Why a separate table rather than a status column on options_signal_history:
that table is spread-shaped — short_strike, long_strike, net_credit, max_loss
and breakeven are all NOT NULL. A rejection has none of them. Writing zeros to
satisfy the schema would fabricate a spread that was never priced, which is the
one thing this codebase consistently refuses to do (see 0028's "reconstructing
one from today's ATR multipliers would invent a level the desk never actually
placed", and record_options_signal's honest-None handling for debit spreads).

One row per (ticker, strategy, reason, UTC day), with `occurrences` counting
repeats. The options scan re-evaluates ~102 symbols every 30 minutes, so a
symbol that keeps failing the same check would otherwise write ~13 identical
rows a day — the same duplication that made signal_outcomes unreadable. The
counter keeps the frequency information without the rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OptionsScanRejection(Base):
    __tablename__ = "options_scan_rejections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    # Null when the scan failed before a strategy was ever selected (e.g.
    # insufficient price history) — that absence is itself a finding, so it is
    # recorded rather than defaulted to a strategy that was never considered.
    strategy: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)

    # Regime at scan time. A rejection profile is only interpretable against
    # which strategies the regime allowed at that moment.
    regime: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # SHAP top_positive_factors / top_negative_factors, present only on the
    # AI-scorer rejection path. Every other reason has nothing to attach.
    evidence: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_options_scan_rejections_first_seen", "first_seen_at"),
        Index("idx_options_scan_rejections_reason", "reason"),
        Index("idx_options_scan_rejections_ticker", "ticker"),
    )
