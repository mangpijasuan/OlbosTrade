"""Add signal_outcomes table

Persists every routable equity signal (not just executed trades) so hit
rate and days-to-target can actually be measured against real forward
price action. Prerequisite for any future ML pass trained on live signal
outcomes rather than backtest replay.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-14
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signal_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("signal_id", sa.String(36), nullable=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("asset_type", sa.String(20), nullable=False, server_default="equity"),
        sa.Column("action", sa.String(10), nullable=False,
                  comment="BUY | SELL"),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("entry_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("stop_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("target_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("target_move_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending",
                  comment="pending | target_hit | stop_hit | expired"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("days_to_resolve", sa.Integer, nullable=True),
        sa.Column("max_favorable_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("max_adverse_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("rsi", sa.Numeric(6, 2), nullable=True),
        sa.Column("macd", sa.Numeric(10, 4), nullable=True),
        sa.Column("bb_pct_b", sa.Numeric(6, 4), nullable=True),
        sa.Column("volume_ratio", sa.Numeric(8, 4), nullable=True),
        sa.Column("atr", sa.Numeric(12, 4), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_signal_outcomes_status", "signal_outcomes", ["status"])
    op.create_index("idx_signal_outcomes_ticker", "signal_outcomes", ["ticker"])
    op.create_index("idx_signal_outcomes_generated_at", "signal_outcomes", ["generated_at"])


def downgrade() -> None:
    op.drop_index("idx_signal_outcomes_generated_at", table_name="signal_outcomes")
    op.drop_index("idx_signal_outcomes_ticker", table_name="signal_outcomes")
    op.drop_index("idx_signal_outcomes_status", table_name="signal_outcomes")
    op.drop_table("signal_outcomes")
