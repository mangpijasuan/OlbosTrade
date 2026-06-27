"""Add missing trades.quantity column (schema drift fix).

The Trade model has carried a `quantity` column for some time, but no migration
ever created it — so DBs built purely from migrations lack the column, and any
full `SELECT * FROM trades` (reconciler, history, fill poller) errors with
"column trades.quantity does not exist". This adds it idempotently.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-27
"""

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns(table)]
    return column in cols


def upgrade() -> None:
    # Idempotent: some environments may already have the column (added out-of-band).
    if not _has_column("trades", "quantity"):
        op.add_column(
            "trades",
            sa.Column("quantity", sa.Integer(), nullable=True, server_default="1",
                      comment="Contracts/shares for the position"),
        )


def downgrade() -> None:
    if _has_column("trades", "quantity"):
        op.drop_column("trades", "quantity")
