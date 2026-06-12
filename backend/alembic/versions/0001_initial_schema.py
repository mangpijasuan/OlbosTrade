"""Initial schema — all 8 tables

Revision ID: 0001
Revises: 
Create Date: 2026-06-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── trades ────────────────────────────────────────────────────────────
    op.create_table(
        "trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("underlying", sa.String(10), nullable=False),
        sa.Column("spread_type", sa.String(50), nullable=False),
        sa.Column("short_strike", sa.Numeric(10, 2), nullable=False),
        sa.Column("long_strike", sa.Numeric(10, 2), nullable=False),
        sa.Column("short_strike_2", sa.Numeric(10, 2), nullable=True),
        sa.Column("long_strike_2", sa.Numeric(10, 2), nullable=True),
        sa.Column("expiration", sa.Date, nullable=False),
        sa.Column("entry_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("credit_received", sa.Numeric(10, 4), nullable=True),
        sa.Column("cost_to_close", sa.Numeric(10, 4), nullable=True),
        sa.Column("pnl", sa.Numeric(12, 4), nullable=True),
        sa.Column("pnl_pct", sa.Numeric(8, 6), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("exit_reason", sa.String(50), nullable=True),
        sa.Column("signal_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("commission_paid", sa.Numeric(10, 4), nullable=True),
        sa.Column("fill_price_short", sa.Numeric(10, 4), nullable=True),
        sa.Column("fill_price_long", sa.Numeric(10, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── positions ─────────────────────────────────────────────────────────
    op.create_table(
        "positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trade_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("trades.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("current_value", sa.Numeric(12, 4), nullable=True),
        sa.Column("delta", sa.Numeric(10, 6), nullable=True),
        sa.Column("gamma", sa.Numeric(10, 6), nullable=True),
        sa.Column("theta", sa.Numeric(10, 6), nullable=True),
        sa.Column("vega", sa.Numeric(10, 6), nullable=True),
        sa.Column("unrealized_pnl", sa.Numeric(12, 4), nullable=True),
        sa.Column("days_in_trade", sa.Integer, nullable=True),
        sa.Column("risk_approved", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("risk_flags", postgresql.JSONB, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── portfolio_snapshots ───────────────────────────────────────────────
    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("total_value", sa.Numeric(14, 4), nullable=False),
        sa.Column("cash", sa.Numeric(14, 4), nullable=False),
        sa.Column("net_delta", sa.Numeric(10, 6), nullable=True),
        sa.Column("net_theta", sa.Numeric(10, 6), nullable=True),
        sa.Column("net_vega", sa.Numeric(10, 6), nullable=True),
        sa.Column("open_position_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("daily_pnl", sa.Numeric(12, 4), nullable=True),
        sa.Column("weekly_pnl", sa.Numeric(12, 4), nullable=True),
        sa.Column("monthly_pnl", sa.Numeric(12, 4), nullable=True),
        sa.Column("trading_mode", sa.String(30), nullable=False, server_default="normal"),
        sa.Column("consecutive_losses", sa.Integer, nullable=False, server_default="0"),
        sa.Column("trades_today", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cooling_off_until", sa.DateTime(timezone=True), nullable=True),
    )

    # ── market_snapshots ──────────────────────────────────────────────────
    op.create_table(
        "market_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(10), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("price", sa.Numeric(12, 4), nullable=True),
        sa.Column("iv_rank", sa.Numeric(6, 4), nullable=True),
        sa.Column("iv_percentile", sa.Numeric(6, 4), nullable=True),
        sa.Column("vix", sa.Numeric(8, 4), nullable=True),
        sa.Column("rsi_14", sa.Numeric(6, 4), nullable=True),
        sa.Column("adx_14", sa.Numeric(6, 4), nullable=True),
        sa.Column("sma_20", sa.Numeric(12, 4), nullable=True),
        sa.Column("options_chain", postgresql.JSONB, nullable=True),
    )

    # ── backtest_runs ─────────────────────────────────────────────────────
    op.create_table(
        "backtest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("starting_capital", sa.Numeric(14, 4), nullable=False),
        sa.Column("parameters", postgresql.JSONB, nullable=True),
        sa.Column("results", postgresql.JSONB, nullable=True),
        sa.Column("metrics", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── signal_scores ─────────────────────────────────────────────────────
    op.create_table(
        "signal_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("underlying", sa.String(10), nullable=False),
        sa.Column("features", postgresql.JSONB, nullable=True),
        sa.Column("score", sa.Numeric(5, 4), nullable=False),
        sa.Column("approved", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("shap_values", postgresql.JSONB, nullable=True),
    )

    # ── journal_entries ───────────────────────────────────────────────────
    op.create_table(
        "journal_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trade_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("trades.id", ondelete="SET NULL"), nullable=True),
        sa.Column("pre_trade_thesis", sa.Text, nullable=True),
        sa.Column("confidence_level", sa.Integer, nullable=True),
        sa.Column("market_context", sa.Text, nullable=True),
        sa.Column("post_trade_notes", sa.Text, nullable=True),
        sa.Column("followed_rules", sa.Boolean, nullable=True),
        sa.Column("exit_felt_right", sa.Boolean, nullable=True),
        sa.Column("tags", postgresql.JSONB, nullable=True),
        sa.Column("loss_category", sa.String(30), nullable=True),
        sa.Column("mistake_tags", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── guardrail_events ──────────────────────────────────────────────────
    op.create_table(
        "guardrail_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("trigger_value", sa.Numeric(14, 6), nullable=True),
        sa.Column("limit_value", sa.Numeric(14, 6), nullable=True),
        sa.Column("trading_suspended_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("portfolio_value", sa.Numeric(14, 4), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("guardrail_events")
    op.drop_table("journal_entries")
    op.drop_table("signal_scores")
    op.drop_table("backtest_runs")
    op.drop_table("market_snapshots")
    op.drop_table("portfolio_snapshots")
    op.drop_table("positions")
    op.drop_table("trades")
