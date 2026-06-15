"""Add equity signals, portfolio Greeks snapshots, and unified trade fields

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Extend trades table ───────────────────────────────────────────────
    op.add_column("trades", sa.Column(
        "instrument_type", sa.String(10), nullable=False,
        server_default="option",
        comment="equity | option"
    ))
    op.add_column("trades", sa.Column("broker_used", sa.String(20), nullable=True))
    op.add_column("trades", sa.Column("signal_confidence", sa.Float, nullable=True))
    op.add_column("trades", sa.Column("orderflow_score", sa.Float, nullable=True))
    op.add_column("trades", sa.Column("iv_overlay_boost", sa.Float, nullable=True))
    op.add_column("trades", sa.Column("regime_at_entry", sa.String(30), nullable=True))
    op.add_column("trades", sa.Column("kelly_fraction_used", sa.Float, nullable=True))

    op.create_index("idx_trades_instrument_type", "trades", ["instrument_type"])
    op.create_index("idx_trades_broker_used",     "trades", ["broker_used"])

    # ── equity_signals table ──────────────────────────────────────────────
    op.create_table(
        "equity_signals",
        sa.Column("id",               postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker",           sa.String(10),  nullable=False),
        sa.Column("generated_at",     sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("timeframe",        sa.String(20),  nullable=True, server_default="1Day"),
        sa.Column("action",           sa.String(10),  nullable=False),   # BUY | SELL | HOLD
        sa.Column("confidence",       sa.Float,        nullable=True),
        sa.Column("rsi",              sa.Float,        nullable=True),
        sa.Column("macd",             sa.Float,        nullable=True),
        sa.Column("bb_pct_b",         sa.Float,        nullable=True),
        sa.Column("atr",              sa.Float,        nullable=True),
        sa.Column("volume_ratio",     sa.Float,        nullable=True),
        sa.Column("entry_price",      sa.Numeric(12, 4), nullable=True),
        sa.Column("stop_price",       sa.Numeric(12, 4), nullable=True),
        sa.Column("target_price",     sa.Numeric(12, 4), nullable=True),
        sa.Column("position_size",    sa.Numeric(14, 4), nullable=True),
        sa.Column("risk_reward",      sa.Float,        nullable=True),
        sa.Column("sentiment_score",  sa.Float,        nullable=True),
        sa.Column("orderflow_score",  sa.Float,        nullable=True),
        sa.Column("iv_overlay_boost", sa.Float,        nullable=True),
        sa.Column("earnings_gated",   sa.Boolean,      nullable=False, server_default="false"),
        sa.Column("regime_at_signal", sa.String(30),   nullable=True),
        sa.Column("approved_at",      sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at",      sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",       sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_equity_signals_ticker", "equity_signals", ["ticker"])

    # ── portfolio_greeks_snapshots table ──────────────────────────────────
    op.create_table(
        "portfolio_greeks_snapshots",
        sa.Column("id",                      postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("recorded_at",             sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("net_delta",               sa.Float, nullable=True),
        sa.Column("net_vega",                sa.Float, nullable=True),
        sa.Column("net_theta",               sa.Float, nullable=True),
        sa.Column("equity_position_count",   sa.Integer, nullable=False, server_default="0"),
        sa.Column("options_position_count",  sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_position_count",    sa.Integer, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("portfolio_greeks_snapshots")
    op.drop_table("equity_signals")

    op.drop_index("idx_trades_broker_used",     table_name="trades")
    op.drop_index("idx_trades_instrument_type", table_name="trades")

    for col in [
        "kelly_fraction_used", "regime_at_entry", "iv_overlay_boost",
        "orderflow_score", "signal_confidence", "broker_used", "instrument_type",
    ]:
        op.drop_column("trades", col)
