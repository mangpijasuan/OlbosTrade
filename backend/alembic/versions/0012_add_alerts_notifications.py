"""Add alert_rules and notifications tables.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("predicates", JSONB, nullable=False, server_default="[]"),
        sa.Column("mode", sa.String(12), nullable=False, server_default="manual"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("cooldown_min", sa.Integer, nullable=False, server_default="60"),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.String(600), nullable=False, server_default=""),
        sa.Column("severity", sa.String(12), nullable=False, server_default="info"),
        sa.Column("read", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("rule_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notifications_read", "notifications", ["read"])


def downgrade() -> None:
    op.drop_index("ix_notifications_read", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("alert_rules")
