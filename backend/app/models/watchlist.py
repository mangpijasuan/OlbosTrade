"""
SQLAlchemy models for Smart Watchlists.

A Watchlist groups symbols the user tracks; symbols carry an asset class so a
single list can mix equities, ETFs, options underlyings, and (later) crypto.
System-seeded default lists have is_system=True and are not user-deletable.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    symbols: Mapped[list["WatchlistSymbol"]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan", lazy="selectin"
    )


class WatchlistSymbol(Base):
    __tablename__ = "watchlist_symbols"
    __table_args__ = (UniqueConstraint("watchlist_id", "symbol", name="uq_watchlist_symbol"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    watchlist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(12), nullable=False, default="equity")

    watchlist: Mapped["Watchlist"] = relationship(back_populates="symbols")
