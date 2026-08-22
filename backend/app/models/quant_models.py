"""
SQLAlchemy models for the Quant Research & Strategy Lab (Phase 1).

Tables:
  quant_strategies        — strategy definitions with versioning
  quant_strategy_versions — immutable snapshots (git-style)
  quant_backtest_runs     — backtest execution records
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class QuantStrategy(Base):
    """Top-level strategy definition. Mutable — each edit bumps current_version."""

    __tablename__ = "quant_strategies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Deterministic JSON: entry / filter / confirmation / regime / risk / exit / execution
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class QuantStrategyVersion(Base):
    """
    Immutable snapshot of a strategy at a given version.
    A backtest always references (strategy_id, version) so old results are
    never invalidated by a later strategy edit.
    """

    __tablename__ = "quant_strategy_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class QuantBacktestRun(Base):
    """
    Record of a single quant backtest execution.
    Stores the full frozen snapshot (strategy config, parameters, data source,
    execution assumptions) so results are always reproducible.
    """

    __tablename__ = "quant_backtest_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    strategy_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Frozen snapshot of strategy config at run time (immutable)
    strategy_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, default="1d")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    starting_capital: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False, default=100000)

    # Execution assumptions (frozen at run time)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Status: queued | running | completed | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Aggregate metrics (populated after completion)
    metrics: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Equity curve as list of {date, equity} (stored for charting)
    equity_curve: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    # Individual trade log
    trades: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
