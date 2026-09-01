"""add target_price to trades

The take-profit level was always computed at entry and sent to the broker as
the bracket's profit leg, but never persisted. That made a target fill
unprovable after the fact: the reconciler sees a position gone and an
execution price, with nothing on the row to compare the price against.

Nullable, no backfill. Historical rows genuinely do not have this — every
trade closed before this migration was recorded without a target, and
reconstructing one from today's ATR multipliers would invent a level the
desk never actually placed. Same convention as 0025's regime column.

Revision ID: 0028
Revises: 0027
"""
from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trades",
        sa.Column("target_price", sa.Numeric(10, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trades", "target_price")
