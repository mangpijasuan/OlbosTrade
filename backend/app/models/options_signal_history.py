"""
SQLAlchemy model for the options_signal_history table.

Persists every qualifying options spread signal the scanner generates —
mirrors signal_outcome.py's equity precedent, but options spreads have no
entry/stop/target shape to track a forward outcome against (they have
strikes/credit/breakeven instead), so this is a signal log only: no
status/resolved_at/exit_price columns. Forward P&L resolution for options
is a separate, larger gap than this slice covers.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OptionsSignalHistory(Base):
    __tablename__ = "options_signal_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # The in-memory signal's own id (app.api.routes.options._recent_options_signals),
    # kept only for cross-reference — not a foreign key, since that store is
    # wiped on restart and this row must outlive it.
    signal_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    ticker:     Mapped[str] = mapped_column(String(10), nullable=False)
    strategy:   Mapped[str] = mapped_column(String(60), nullable=False)
    action:     Mapped[str] = mapped_column(String(12), nullable=False, comment="BUY_SPREAD | SELL_SPREAD")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)

    # None for debit spreads and when analyze_spread() fails — see
    # app.main's options scan (credit_per_share isn't meaningful for a
    # debit spread, so intelligence is skipped rather than fed a floored
    # value and returning a fabricated POP/Kelly).
    pop:            Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    kelly_fraction: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)

    signal_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    quantity:     Mapped[int] = mapped_column(Integer, nullable=False)
    iv_rank:      Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    regime:       Mapped[str] = mapped_column(String(40), nullable=False)

    # The spread IS the trade shape here — no entry/stop/target exists for options.
    option_type:  Mapped[str] = mapped_column(String(6), nullable=False, comment="put | call")
    short_strike: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    long_strike:  Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    expiration:   Mapped[date] = mapped_column(Date, nullable=False)
    dte:          Mapped[int] = mapped_column(Integer, nullable=False)
    # Signed: positive = net credit received, negative = net debit paid —
    # same convention as the broker layer and P&L recording use.
    net_credit:   Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    max_loss:     Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    breakeven:    Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)

    sigma:         Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    vix_used:      Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    credit_source: Mapped[str] = mapped_column(String(20), nullable=False)

    # SHAP evidence + full options-intelligence payload, stored whole rather
    # than flattened into speculative columns nothing reads yet.
    evidence:     Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    intelligence: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_options_signal_history_ticker", "ticker"),
        Index("idx_options_signal_history_generated_at", "generated_at"),
        Index("idx_options_signal_history_strategy", "strategy"),
    )
