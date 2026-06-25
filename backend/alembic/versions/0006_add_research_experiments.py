"""Add research_experiments table for the Research Lab promotion funnel.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_experiments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=True),
        sa.Column("stage", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("spec", JSONB, nullable=True),
        sa.Column("backtest_metrics", JSONB, nullable=True),
        sa.Column("paper_perf", JSONB, nullable=True),
        sa.Column("baseline", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_research_experiments_strategy", "research_experiments", ["strategy"])
    op.create_index("ix_research_experiments_stage", "research_experiments", ["stage"])


def downgrade() -> None:
    op.drop_index("ix_research_experiments_stage", table_name="research_experiments")
    op.drop_index("ix_research_experiments_strategy", table_name="research_experiments")
    op.drop_table("research_experiments")
