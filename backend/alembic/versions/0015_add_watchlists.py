"""Add smart watchlists tables.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlists",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("description", sa.String(240), nullable=False, server_default=""),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "watchlist_symbols",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("watchlist_id", UUID(as_uuid=True), sa.ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("asset_class", sa.String(12), nullable=False, server_default="equity"),
        sa.UniqueConstraint("watchlist_id", "symbol", name="uq_watchlist_symbol"),
    )
    op.create_index("ix_watchlist_symbols_watchlist_id", "watchlist_symbols", ["watchlist_id"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_symbols_watchlist_id", table_name="watchlist_symbols")
    op.drop_table("watchlist_symbols")
    op.drop_table("watchlists")
