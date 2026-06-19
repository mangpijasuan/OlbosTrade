"""Add trades.dispatch_id (unique) for fill-recording idempotency

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-19

The order gate passed a dispatch_id to TradeRecorder.record_fill but it was
dropped on the floor — so a fill could be recorded twice across a restart (the
in-process _inflight guard does not persist). Persist it and enforce uniqueness;
NULL is permitted many times so equity fallbacks without a broker order id don't
collide.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "trades",
        sa.Column("dispatch_id", sa.String(length=64), nullable=True),
    )
    # Unique so the same broker fill can only ever produce one trade row.
    # Postgres treats NULLs as distinct, so rows without a dispatch_id are fine.
    op.create_index(
        "idx_trades_dispatch_id", "trades", ["dispatch_id"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_trades_dispatch_id", table_name="trades")
    op.drop_column("trades", "dispatch_id")
