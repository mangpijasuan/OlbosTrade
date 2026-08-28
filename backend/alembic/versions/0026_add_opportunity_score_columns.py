"""Add opportunity-score capture to signal_outcomes.

Stores the composite ranking score plus the two components that carry
information the table does not already hold (liquidity, regime).

Deliberately omits the Alpha Edge entry score and the risk score: both are
exact monotone transforms of the existing `confidence` column, so they would
add no information and would leave any rank-based skill test returning the
same value it already does.

Nullable with no backfill — historical rows genuinely lack these values, and
inventing them would be worse than a NULL that reads as "not captured".

Revision ID: 0026
Revises: 0025
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("signal_outcomes", sa.Column("opportunity_score", sa.Integer(), nullable=True))
    op.add_column("signal_outcomes", sa.Column("oppty_liquidity", sa.Numeric(6, 4), nullable=True))
    op.add_column("signal_outcomes", sa.Column("oppty_regime", sa.Numeric(6, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("signal_outcomes", "oppty_regime")
    op.drop_column("signal_outcomes", "oppty_liquidity")
    op.drop_column("signal_outcomes", "opportunity_score")
