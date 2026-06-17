"""Add hot-path indexes and widen trades.pnl_pct

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Indexes on hot query paths (reconcile filters trades.status; journal/position
    # joins use trade_id) — previously unindexed.
    op.create_index("idx_trades_status", "trades", ["status"])
    op.create_index("idx_journal_entries_trade_id", "journal_entries", ["trade_id"])
    op.create_index("idx_positions_trade_id", "positions", ["trade_id"])

    # Widen pnl_pct so a true per-trade return (e.g. -1.5 = -150%) can't overflow
    # Numeric(8,6) (max |99.99|... but 6 dp leaves only 2 integer digits).
    op.alter_column(
        "trades", "pnl_pct",
        type_=sa.Numeric(10, 6),
        existing_type=sa.Numeric(8, 6),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "trades", "pnl_pct",
        type_=sa.Numeric(8, 6),
        existing_type=sa.Numeric(10, 6),
        existing_nullable=True,
    )
    op.drop_index("idx_positions_trade_id", table_name="positions")
    op.drop_index("idx_journal_entries_trade_id", table_name="journal_entries")
    op.drop_index("idx_trades_status", table_name="trades")
