"""
SQLAlchemy models for backtest_runs, market_snapshots, and signal_scores.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    starting_capital: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    parameters: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    results: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    metrics: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    iv_rank: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    iv_percentile: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    vix: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    rsi_14: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    adx_14: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    sma_20: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    options_chain: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)


class SignalScore(Base):
    __tablename__ = "signal_scores"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    underlying: Mapped[str] = mapped_column(String(10), nullable=False)
    features: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    shap_values: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
