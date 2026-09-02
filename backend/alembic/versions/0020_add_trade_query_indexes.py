"""Add indexes on trades.status, entry_date, exit_date

status is filtered in ~25 query sites across main.py, trade_desk.py,
risk.py, analytics.py, paper_trade.py and services/ (portfolio state,
guardrails, reconciliation) with no index — every one of those was a
sequential scan. entry_date/exit_date are filtered/ordered by in several
of the same sites (date-range reporting, open/closed splits). The trades
table is still small in paper trading, so this hasn't been a visible
problem yet, but it's a correctness-adjacent hazard: query plans degrade
silently as the table grows, with no test or alert that would catch it.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-15
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_trades_status", "trades", ["status"])
    op.create_index("ix_trades_entry_date", "trades", ["entry_date"])
    op.create_index("ix_trades_exit_date", "trades", ["exit_date"])


def downgrade() -> None:
    op.drop_index("ix_trades_exit_date", table_name="trades")
    op.drop_index("ix_trades_entry_date", table_name="trades")
    op.drop_index("ix_trades_status", table_name="trades")
