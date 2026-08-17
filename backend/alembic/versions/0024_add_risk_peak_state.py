"""Add risk_peak_state table

Portfolio-level Drawdown Control needs one number to survive restarts —
the all-time peak portfolio value — to compute peak-to-trough drawdown.
The existing portfolio_snapshots table could in principle supply this
via MAX(total_value), but its writer (save_portfolio_snapshot) is dead
code with zero callers anywhere in the app, so that table is empty in
practice. Rather than reviving an unrelated dead code path, this adds a
minimal singleton row (id=1) updated in place — a different update
shape than portfolio_snapshots (point-in-time) or guardrail_events
(append-only), so it gets its own table.

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "risk_peak_state",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("peak_value", sa.Numeric(14, 4), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("risk_peak_state")
