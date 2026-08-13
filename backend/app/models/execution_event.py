"""
SQLAlchemy model for execution_events — the persisted Copilot approval queue,
execution log, and execution-mode change history.

Previously these lived in trade_desk.py as in-process containers
(_pending_approvals dict, _execution_log list) and execution_mode.py persisted
mode to a /tmp JSON file inside the container — all three silently reset on
every deploy/restart (the same class of bug as the bracket-order and
pending-order-timeout restart bugs fixed earlier). One append-only table
replaces all three; kind distinguishes the three uses.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ExecutionEvent(Base):
    __tablename__ = "execution_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # "pending_approval" | "execution" | "mode_change" | "trading_mode_change"
    kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    signal_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ticker: Mapped[str | None] = mapped_column(String(16), nullable=True)
    asset_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # pending_approval: "pending" | "approved" | "rejected". execution: the
    # result string (e.g. "submitted"/"blocked"/"skipped"). mode_change: unused.
    # trading_mode_change: the new mode value ("conservative"/"balanced"/etc).
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
