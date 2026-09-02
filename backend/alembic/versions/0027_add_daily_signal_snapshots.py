"""Add daily_signal_snapshots — a frozen daily top-3 record.

Captures the top 3 BUY and top 3 SELL by opportunity_score at 10:00 ET each
trading day, and never rewrites them.

The freeze is the point. The scanner re-records the same (ticker, action, day)
roughly 45 times as it re-scores through a session, so ranking retrospectively
would pick each signal's best-scoring moment — including signals that only
surfaced after the move. That produces a flattering record rather than a track
record. A fixed capture time makes the row mean "this is what was on screen
when you could have acted".

The unique constraint on (trade_date, action, rank) is what enforces
immutability at the schema level rather than trusting the writer.

Revision ID: 0027
Revises: 0026
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_signal_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("action", sa.String(length=4), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=10), nullable=False),
        sa.Column("signal_outcome_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("signal_id", sa.String(length=64), nullable=True),
        sa.Column("opportunity_score", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("entry_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("stop_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("target_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("regime", sa.String(length=30), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("trade_date", "action", "rank",
                            name="uq_daily_snapshot_slot"),
    )
    op.create_index("ix_daily_signal_snapshots_trade_date",
                    "daily_signal_snapshots", ["trade_date"])
    op.create_index("ix_daily_signal_snapshots_signal_outcome_id",
                    "daily_signal_snapshots", ["signal_outcome_id"])
    op.create_index("ix_daily_snapshot_date_action",
                    "daily_signal_snapshots", ["trade_date", "action"])


def downgrade() -> None:
    op.drop_index("ix_daily_snapshot_date_action", table_name="daily_signal_snapshots")
    op.drop_index("ix_daily_signal_snapshots_signal_outcome_id",
                  table_name="daily_signal_snapshots")
    op.drop_index("ix_daily_signal_snapshots_trade_date",
                  table_name="daily_signal_snapshots")
    op.drop_table("daily_signal_snapshots")
