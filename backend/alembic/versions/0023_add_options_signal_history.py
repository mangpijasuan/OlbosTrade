"""Add options_signal_history table

Options signals have only ever lived in an in-memory Python list
(_recent_options_signals), wiped on every backend restart — equity signals,
by contrast, get permanently persisted via signal_outcomes. This closes
that gap for options with a signal log (no forward-outcome resolution yet;
spreads have no entry/stop/target shape to walk daily bars against the way
equity signals do — that's separate, larger, future scope).

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-16
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "options_signal_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("signal_id", sa.String(36), nullable=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("strategy", sa.String(60), nullable=False),
        sa.Column("action", sa.String(12), nullable=False,
                  comment="BUY_SPREAD | SELL_SPREAD"),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("pop", sa.Numeric(5, 4), nullable=True),
        sa.Column("kelly_fraction", sa.Numeric(8, 4), nullable=True),
        sa.Column("signal_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("iv_rank", sa.Numeric(6, 2), nullable=False),
        sa.Column("regime", sa.String(40), nullable=False),
        sa.Column("option_type", sa.String(6), nullable=False, comment="put | call"),
        sa.Column("short_strike", sa.Numeric(12, 4), nullable=False),
        sa.Column("long_strike", sa.Numeric(12, 4), nullable=False),
        sa.Column("expiration", sa.Date, nullable=False),
        sa.Column("dte", sa.Integer, nullable=False),
        sa.Column("net_credit", sa.Numeric(12, 4), nullable=False),
        sa.Column("max_loss", sa.Numeric(12, 4), nullable=False),
        sa.Column("breakeven", sa.Numeric(12, 4), nullable=False),
        sa.Column("sigma", sa.Numeric(8, 4), nullable=False),
        sa.Column("vix_used", sa.Numeric(6, 2), nullable=False),
        sa.Column("credit_source", sa.String(20), nullable=False),
        sa.Column("evidence", postgresql.JSONB, nullable=True),
        sa.Column("intelligence", postgresql.JSONB, nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_options_signal_history_ticker", "options_signal_history", ["ticker"])
    op.create_index("idx_options_signal_history_generated_at", "options_signal_history", ["generated_at"])
    op.create_index("idx_options_signal_history_strategy", "options_signal_history", ["strategy"])


def downgrade() -> None:
    op.drop_index("idx_options_signal_history_strategy", table_name="options_signal_history")
    op.drop_index("idx_options_signal_history_generated_at", table_name="options_signal_history")
    op.drop_index("idx_options_signal_history_ticker", table_name="options_signal_history")
    op.drop_table("options_signal_history")
