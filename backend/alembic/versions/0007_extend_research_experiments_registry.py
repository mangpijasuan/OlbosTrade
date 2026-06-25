"""Extend research_experiments into a Strategy Registry (Phase 2).

Adds walk-forward metrics + registry metadata columns. All additive and
nullable — fully backward compatible.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("research_experiments", sa.Column("walk_forward_metrics", JSONB, nullable=True))
    op.add_column("research_experiments", sa.Column("version", sa.String(20), nullable=True))
    op.add_column("research_experiments", sa.Column("author", sa.String(80), nullable=True))
    op.add_column("research_experiments", sa.Column("asset_class", sa.String(30), nullable=True))
    op.add_column("research_experiments", sa.Column("market_type", sa.String(30), nullable=True))
    op.add_column("research_experiments", sa.Column("supported_regimes", JSONB, nullable=True))
    op.add_column("research_experiments", sa.Column("risk_profile", sa.String(20), nullable=True))


def downgrade() -> None:
    for col in ("risk_profile", "supported_regimes", "market_type",
                "asset_class", "author", "version", "walk_forward_metrics"):
        op.drop_column("research_experiments", col)
