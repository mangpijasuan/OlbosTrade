"""
SQLAlchemy model for Research Lab experiments — the strategy promotion funnel.

Stores the hypothesis, the Symphony strategy spec, and the evidence accumulated
at each stage (backtest metrics, paper performance, derived baseline). Stage
transitions and gates live in app.services.research_lab; this is just storage.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ResearchExperiment(Base):
    __tablename__ = "research_experiments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    hypothesis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Lifecycle stage: draft | backtested | paper | promoted | archived
    stage: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", index=True
    )
    spec: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    backtest_metrics: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    paper_perf: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    baseline: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    def as_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "strategy": self.strategy,
            "hypothesis": self.hypothesis,
            "stage": self.stage,
            "spec": self.spec,
            "backtest_metrics": self.backtest_metrics,
            "paper_perf": self.paper_perf,
            "baseline": self.baseline,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
