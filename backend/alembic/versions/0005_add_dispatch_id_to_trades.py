"""Add dispatch_id to trades for idempotent fill recording.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trades",
        sa.Column(
            "dispatch_id",
            sa.String(100),
            nullable=True,
            comment="Broker dispatch correlation ID — UNIQUE ensures idempotent fill recording",
        ),
    )
    op.create_unique_constraint("uq_trades_dispatch_id", "trades", ["dispatch_id"])
    op.create_index("ix_trades_dispatch_id", "trades", ["dispatch_id"])


def downgrade() -> None:
    op.drop_index("ix_trades_dispatch_id", table_name="trades")
    op.drop_constraint("uq_trades_dispatch_id", "trades", type_="unique")
    op.drop_column("trades", "dispatch_id")
