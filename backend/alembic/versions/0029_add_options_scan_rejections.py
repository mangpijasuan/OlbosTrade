"""add options_scan_rejections

Options spread scanning has covered the full ~102-symbol watchlist every 30
minutes since 5809f03 (2026-08-01), and produced zero closed options trades in
the four weeks to the 2026-08-28 assessment. Rejection reasons were already
recorded by _record_options_rejection(), but only into _recent_options_signals
— an in-memory list truncated at 200 entries that dies on every restart. So the
question "why did nothing fire" has never had data behind it.

This table gives those reasons a history. One row per (ticker, strategy,
reason, UTC day) with an occurrences counter: the scan re-evaluates every
symbol ~13 times a day, and writing a row per evaluation would reproduce
exactly the duplication that made signal_outcomes unreadable.

Separate table rather than a status column on options_signal_history because
that table is spread-shaped (short_strike/long_strike/net_credit/max_loss/
breakeven are NOT NULL) and a rejection has none of those values. Zeros would
fabricate a spread that was never priced.

Revision ID: 0029
Revises: 0028
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "options_scan_rejections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("strategy", sa.String(60), nullable=True),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("regime", sa.String(30), nullable=True),
        sa.Column("evidence", postgresql.JSONB, nullable=True),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_options_scan_rejections_first_seen",
                    "options_scan_rejections", ["first_seen_at"])
    op.create_index("idx_options_scan_rejections_reason",
                    "options_scan_rejections", ["reason"])
    op.create_index("idx_options_scan_rejections_ticker",
                    "options_scan_rejections", ["ticker"])


def downgrade() -> None:
    op.drop_index("idx_options_scan_rejections_ticker", table_name="options_scan_rejections")
    op.drop_index("idx_options_scan_rejections_reason", table_name="options_scan_rejections")
    op.drop_index("idx_options_scan_rejections_first_seen", table_name="options_scan_rejections")
    op.drop_table("options_scan_rejections")
