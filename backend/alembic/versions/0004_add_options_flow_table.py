"""Add options_flow table for the Options Intelligence module

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "options_flow",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("strike", sa.Numeric(10, 2), nullable=False),
        sa.Column("expiry", sa.Date, nullable=False),
        sa.Column("right", sa.String(1), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("premium", sa.Numeric(14, 2), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("trade_type", sa.String(10), nullable=False),
        sa.Column("sentiment", sa.String(10), nullable=False),
        sa.Column("iv", sa.Numeric(8, 6), nullable=True),
        sa.Column("delta", sa.Numeric(6, 4), nullable=True),
        sa.Column("dte", sa.SmallInteger, nullable=True),
        sa.Column("relative_volume", sa.Numeric(6, 2), nullable=True),
        sa.Column("sweep_confirmed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("large_sweep", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index(
        "idx_options_flow_ticker_ts", "options_flow", ["ticker", "timestamp"]
    )
    op.create_index(
        "idx_options_flow_contract_ts",
        "options_flow",
        ["ticker", "expiry", "strike", "right", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("idx_options_flow_contract_ts", table_name="options_flow")
    op.drop_index("idx_options_flow_ticker_ts", table_name="options_flow")
    op.drop_table("options_flow")
