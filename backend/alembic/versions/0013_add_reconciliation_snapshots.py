"""Add reconciliation snapshots table.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reconciliation_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("clean", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("broker_name", sa.String(length=40), nullable=False),
        sa.Column("broker_position_count", sa.Integer(), nullable=False),
        sa.Column("db_open_trade_count", sa.Integer(), nullable=False),
        sa.Column("untracked_at_broker", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("phantom_in_db", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quantity_mismatches", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reconciliation_snapshots_checked_at",
        "reconciliation_snapshots",
        ["checked_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_reconciliation_snapshots_checked_at", table_name="reconciliation_snapshots")
    op.drop_table("reconciliation_snapshots")
