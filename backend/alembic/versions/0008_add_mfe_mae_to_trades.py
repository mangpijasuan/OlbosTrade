"""Add MFE/MAE excursion tracking to trades.

Maximum Favorable Excursion (best unrealized P&L seen while open) and Maximum
Adverse Excursion (worst unrealized P&L seen while open). Used to refine
take-profit / stop-loss levels — i.e. how much was left on the table, and how
much heat each trade took before resolving.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-27
"""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trades",
        sa.Column("mfe", sa.Numeric(12, 4), nullable=True,
                  comment="Maximum Favorable Excursion — best unrealized P&L while open ($)"),
    )
    op.add_column(
        "trades",
        sa.Column("mae", sa.Numeric(12, 4), nullable=True,
                  comment="Maximum Adverse Excursion — worst unrealized P&L while open ($)"),
    )


def downgrade() -> None:
    op.drop_column("trades", "mae")
    op.drop_column("trades", "mfe")
