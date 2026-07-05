"""Add strategy profiles registry table.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("asset_class", sa.String(length=40), nullable=False),
        sa.Column("supported_symbols", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("supported_regimes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("supported_volatility_regimes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_profile_compatibility", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("manual_eligible", sa.Boolean(), nullable=False),
        sa.Column("copilot_eligible", sa.Boolean(), nullable=False),
        sa.Column("autopilot_supported", sa.Boolean(), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=40), nullable=False),
        sa.Column("health_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("last_validation_date", sa.Date(), nullable=True),
        sa.Column("allocation_limit_pct", sa.Numeric(6, 3), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("main_risk_warning", sa.Text(), nullable=True),
        sa.Column("validation_notes", sa.Text(), nullable=True),
        sa.Column("performance_link", sa.String(length=255), nullable=True),
        sa.Column("snapshots_link", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategy_profiles_strategy_id"), "strategy_profiles", ["strategy_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_strategy_profiles_strategy_id"), table_name="strategy_profiles")
    op.drop_table("strategy_profiles")
