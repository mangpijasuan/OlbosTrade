"""Add missing trade columns: quantity, trading_mode_at_entry, commission_paid, fill prices.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-22
"""

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


# (column_name, column_definition) — trading_mode_at_entry is intentionally
# omitted here because it was already added in migration 0002.
_COLUMNS = [
    ("quantity", sa.Column("quantity", sa.Integer, nullable=True, server_default="1")),
    ("commission_paid", sa.Column("commission_paid", sa.Numeric(10, 4), nullable=True)),
    ("fill_price_short", sa.Column("fill_price_short", sa.Numeric(10, 4), nullable=True)),
    ("fill_price_long", sa.Column("fill_price_long", sa.Numeric(10, 4), nullable=True)),
]


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns("trades")}


def upgrade() -> None:
    existing = _existing_columns()
    for name, column in _COLUMNS:
        if name not in existing:
            op.add_column("trades", column)


def downgrade() -> None:
    existing = _existing_columns()
    for name, _ in reversed(_COLUMNS):
        if name in existing:
            op.drop_column("trades", name)
