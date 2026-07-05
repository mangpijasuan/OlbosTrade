"""Add trade excursion metrics.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("mfe_pnl", sa.Numeric(12, 4), nullable=True))
    op.add_column("trades", sa.Column("mae_pnl", sa.Numeric(12, 4), nullable=True))
    op.add_column("trades", sa.Column("pnl_capture_pct", sa.Numeric(8, 6), nullable=True))


def downgrade() -> None:
    op.drop_column("trades", "pnl_capture_pct")
    op.drop_column("trades", "mae_pnl")
    op.drop_column("trades", "mfe_pnl")
