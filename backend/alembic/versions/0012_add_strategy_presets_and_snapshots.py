"""Add strategy presets, snapshots, and trade snapshot linkage.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_presets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("preset_id", sa.String(length=120), nullable=False),
        sa.Column("strategy_id", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("preset_name", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("market_regime_requirements", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("volatility_requirements", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("timeframe", sa.String(length=40), nullable=False),
        sa.Column("entry_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("exit_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("position_sizing_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence_threshold", sa.Float(), nullable=False),
        sa.Column("event_risk_restrictions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("max_allocation_pct", sa.Float(), nullable=False),
        sa.Column("risk_profile_compatibility", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("validation_status", sa.String(length=40), nullable=False),
        sa.Column("paper_validated", sa.Boolean(), nullable=False),
        sa.Column("live_validated", sa.Boolean(), nullable=False),
        sa.Column("author", sa.String(length=120), nullable=False),
        sa.Column("approval_owner", sa.String(length=120), nullable=True),
        sa.Column("approval_notes", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.Date(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategy_presets_preset_id"), "strategy_presets", ["preset_id"], unique=True)
    op.create_index(op.f("ix_strategy_presets_strategy_id"), "strategy_presets", ["strategy_id"], unique=False)

    op.create_table(
        "strategy_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", sa.String(length=120), nullable=False),
        sa.Column("strategy_id", sa.String(length=100), nullable=False),
        sa.Column("preset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("risk_profile", sa.String(length=40), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=40), nullable=False),
        sa.Column("validation_status", sa.String(length=40), nullable=False),
        sa.Column("config_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("inherited_from_verified_preset", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["preset_id"], ["strategy_presets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategy_snapshots_snapshot_id"), "strategy_snapshots", ["snapshot_id"], unique=True)
    op.create_index(op.f("ix_strategy_snapshots_strategy_id"), "strategy_snapshots", ["strategy_id"], unique=False)

    op.add_column("trades", sa.Column("strategy_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_trades_strategy_snapshot_id",
        "trades",
        "strategy_snapshots",
        ["strategy_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_trades_strategy_snapshot_id", "trades", type_="foreignkey")
    op.drop_column("trades", "strategy_snapshot_id")
    op.drop_index(op.f("ix_strategy_snapshots_strategy_id"), table_name="strategy_snapshots")
    op.drop_index(op.f("ix_strategy_snapshots_snapshot_id"), table_name="strategy_snapshots")
    op.drop_table("strategy_snapshots")
    op.drop_index(op.f("ix_strategy_presets_strategy_id"), table_name="strategy_presets")
    op.drop_index(op.f("ix_strategy_presets_preset_id"), table_name="strategy_presets")
    op.drop_table("strategy_presets")
