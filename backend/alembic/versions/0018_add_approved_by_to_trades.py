"""Add approved_by to trades table

trading_mode_at_entry was originally meant to hold the risk-style mode
(conservative|balanced|aggressive|scalper, per its 0002 migration comment)
but had been getting fed the execution approver ("manual"/"autopilot")
instead — a naming collision that left ModeAnalyticsEngine and the Trade
Desk mode badge fed garbage data. This adds a dedicated column for the
approver so trading_mode_at_entry can be restored to its original purpose
without losing the approval-source info other UI (Trade Replay) depends on.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-14
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trades",
        sa.Column(
            "approved_by",
            sa.String(20),
            nullable=True,
            comment="Who/what approved this trade: manual|autopilot|user|copilot|scan_panel"
        )
    )


def downgrade() -> None:
    op.drop_column("trades", "approved_by")
