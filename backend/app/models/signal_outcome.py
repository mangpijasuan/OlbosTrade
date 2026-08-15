"""
SQLAlchemy model for the signal_outcomes table.

Records every routable equity signal the scanner generates — not just the
ones that get traded — and tracks what actually happened to price
afterward. Trades alone are far too small a sample (15 ever recorded) and
are selection-biased toward whatever already passed the confidence filter;
tracking every signal's real forward outcome is what lets hit-rate and
days-to-target actually be measured, and eventually gives an ML model
honest labels to learn from instead of backtest replay.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SignalOutcome(Base):
    __tablename__ = "signal_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # The in-memory signal's own id (app.api.routes.equity._recent_signals),
    # kept only for cross-reference — not a foreign key, since that store is
    # wiped on restart and this row must outlive it.
    signal_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    ticker:     Mapped[str] = mapped_column(String(10), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False, default="equity")
    action:     Mapped[str] = mapped_column(String(10), nullable=False, comment="BUY | SELL")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)

    entry_price:     Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    stop_price:      Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    target_price:    Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    target_move_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
        comment="pending | target_hit | stop_hit | expired",
    )
    resolved_at:     Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price:      Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    days_to_resolve: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Best/worst move seen toward the target while the signal was pending —
    # the equity Trade row equivalent of mfe/mae, computed as % of entry
    # price so it's comparable across tickers.
    max_favorable_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    max_adverse_pct:   Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)

    # Indicator snapshot at signal generation — the feature set a future ML
    # pass would train on. Stored as plain columns (not JSON) so they're
    # directly queryable/aggregatable without a JSON extraction step.
    rsi:          Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    macd:         Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    bb_pct_b:     Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    volume_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    atr:          Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)

    checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_signal_outcomes_status", "status"),
        Index("idx_signal_outcomes_ticker", "ticker"),
        Index("idx_signal_outcomes_generated_at", "generated_at"),
    )
