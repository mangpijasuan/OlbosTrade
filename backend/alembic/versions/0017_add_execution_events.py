"""Add execution_events table.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("signal_id", sa.String(64), nullable=True),
        sa.Column("ticker", sa.String(16), nullable=True),
        sa.Column("asset_type", sa.String(16), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_execution_events_kind", "execution_events", ["kind"])
    op.create_index("ix_execution_events_signal_id", "execution_events", ["signal_id"])
    op.create_index("ix_execution_events_created_at", "execution_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_execution_events_created_at", table_name="execution_events")
    op.drop_index("ix_execution_events_signal_id", table_name="execution_events")
    op.drop_index("ix_execution_events_kind", table_name="execution_events")
    op.drop_table("execution_events")
