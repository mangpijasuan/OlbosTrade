"""
SQLAlchemy model for the options_flow table.

Stores every classified options print (trade) captured by the IBKR options
flow ingest service: premium, size, trade type (sweep/block/single), sentiment,
Greeks, DTE, relative volume, and sweep flags.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OptionsFlow(Base):
    __tablename__ = "options_flow"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    strike: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    expiry: Mapped[date] = mapped_column(Date, nullable=False)
    right: Mapped[str] = mapped_column(String(1), nullable=False, comment="C or P")
    exchange: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    premium: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)

    trade_type: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="sweep | block | single"
    )
    sentiment: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="bullish | bearish | neutral"
    )

    iv: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 6), nullable=True)
    delta: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    dte: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    relative_volume: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(6, 2), nullable=True
    )

    sweep_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    large_sweep: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    __table_args__ = (
        Index("idx_options_flow_ticker_ts", "ticker", "timestamp"),
        Index(
            "idx_options_flow_contract_ts",
            "ticker",
            "expiry",
            "strike",
            "right",
            "timestamp",
        ),
    )
