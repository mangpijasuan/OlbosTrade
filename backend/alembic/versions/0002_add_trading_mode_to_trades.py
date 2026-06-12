"""Add trading_mode_at_entry to trades table

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-11
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trades",
        sa.Column(
            "trading_mode_at_entry",
            sa.String(30),
            nullable=True,
            server_default="balanced",
            comment="Mode active when trade opened: conservative|balanced|aggressive|scalper"
        )
    )
    # Index for fast mode-based analytics queries
    op.create_index(
        "idx_trades_mode",
        "trades",
        ["trading_mode_at_entry"]
    )


def downgrade() -> None:
    op.drop_index("idx_trades_mode", table_name="trades")
    op.drop_column("trades", "trading_mode_at_entry")
