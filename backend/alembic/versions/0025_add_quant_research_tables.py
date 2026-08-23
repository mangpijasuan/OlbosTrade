"""Add quant research & strategy lab tables

Backs the Quant Research & Strategy Lab (Phase 1): versioned strategy
definitions and their backtest runs. Three tables, matching
app/models/quant_models.py exactly:

  quant_strategies        — mutable strategy definition, current_version
                             bumped on every edit.
  quant_strategy_versions — immutable per-version snapshot, so an older
                             backtest's referenced config is never
                             retroactively altered by a later edit.
  quant_backtest_runs     — one row per backtest execution, storing a
                             frozen strategy snapshot alongside the
                             resulting metrics/equity-curve/trade-log so
                             results stay reproducible independent of the
                             strategy's current state.

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quant_strategies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("current_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("config", postgresql.JSONB, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "quant_strategy_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("config", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "idx_quant_strategy_versions_strategy_id",
        "quant_strategy_versions", ["strategy_id"],
    )

    op.create_table(
        "quant_backtest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("strategy_version", sa.Integer, nullable=True),
        sa.Column("strategy_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("timeframe", sa.String(10), nullable=False, server_default="1d"),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("starting_capital", sa.Numeric(16, 4), nullable=False, server_default="100000"),
        sa.Column("parameters", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("metrics", postgresql.JSONB, nullable=True),
        sa.Column("equity_curve", postgresql.JSONB, nullable=True),
        sa.Column("trades", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_quant_backtest_runs_strategy_id",
        "quant_backtest_runs", ["strategy_id"],
    )
    # GET /api/quant/backtest/history orders by created_at desc.
    op.create_index(
        "idx_quant_backtest_runs_created_at",
        "quant_backtest_runs", ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_quant_backtest_runs_created_at", table_name="quant_backtest_runs")
    op.drop_index("idx_quant_backtest_runs_strategy_id", table_name="quant_backtest_runs")
    op.drop_table("quant_backtest_runs")
    op.drop_index("idx_quant_strategy_versions_strategy_id", table_name="quant_strategy_versions")
    op.drop_table("quant_strategy_versions")
    op.drop_table("quant_strategies")
