"""Add index on journal_entries.created_at

Used for both the default entry ordering and the monthly-review date
filter (journal.py's _load_all()/generate_monthly_review()) with no index
today — the only column this table is actually queried by.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-15
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_journal_entries_created_at", "journal_entries", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_journal_entries_created_at", table_name="journal_entries")
