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

    # Market regime at signal generation time — enables a regime-bucketed
    # performance ledger alongside the existing confidence buckets.
    regime: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # equity_signal_engine.EQUITY_SCORING_VERSION at generation time — a
    # lightweight provenance stamp; equity scoring has never had more than
    # one version, so a full snapshot/versioning table isn't warranted yet.
    signal_engine_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # ── Opportunity-score capture ───────────────────────────────────────────
    # The composite that ranks signals (trade_frequency_controller.weighted_score),
    # stored with the two components that carry information this table does not
    # already hold.
    #
    # Deliberately NOT stored: the Alpha Edge entry score and the risk score.
    # Both are exact monotone transforms of `confidence` above —
    # alpha_edge_entry_score is round(confidence * 100) (alpha_edge_engine
    # compute_equity_scores), and risk_score is (1 - confidence) * 100 with a
    # reward:risk nudge that cannot fire for equity (plans are fixed at 2:1).
    # Persisting either would add a column that re-expresses one already here,
    # and would leave any rank-based skill test (AUC is invariant to monotone
    # transforms) returning exactly the same number it does today.
    #
    # Of the composite's five weights, confidence (0.35), EV (0.25 — p*rr-(1-p),
    # with rr fixed) and reward_risk (0.15 — constant for equity) are likewise
    # confidence-determined. Only liquidity and regime vary independently, so
    # they are broken out: a future analysis can ask which component carries
    # signal rather than testing a blend that is three-quarters already-measured.
    opportunity_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    oppty_liquidity: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    oppty_regime: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)

    __table_args__ = (
        Index("idx_signal_outcomes_status", "status"),
        Index("idx_signal_outcomes_ticker", "ticker"),
        Index("idx_signal_outcomes_generated_at", "generated_at"),
    )
