"""Add regime + signal_engine_version columns

Both trades and signal_outcomes already receive a regime value as an
argument at write time (trade_recorder.record_fill()'s callers all pass
signal.get("regime", "unknown"); both scan loops in main.py compute
signal["regime"] before building the signal dict) — it was just never
persisted, only threaded into JournalEntry.market_context free text. This
adds a real, queryable column so a regime dimension can be added to the
existing confidence-bucket performance ledgers (analytics.py's
/signal-score-impact, signal_outcome_tracker's compute_signal_outcome_stats)
without a join. signal_engine_version is a lightweight provenance stamp
for equity signals — options trades already get strategy_snapshot_id via
strategy_config_service; equity signals get nothing today, and a full
snapshot/versioning system isn't warranted while equity scoring has never
had more than one version (see equity_signal_engine.EQUITY_SCORING_VERSION).

Nullable, no backfill — historical rows predate regime capture and
backfilling from free-text JournalEntry.market_context is fragile/low-value.

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trades",
        sa.Column(
            "regime",
            sa.String(30),
            nullable=True,
            comment="Market regime at entry (e.g. low_vol_trending) — same value already threaded into JournalEntry.market_context",
        )
    )
    op.add_column("signal_outcomes",
        sa.Column(
            "regime",
            sa.String(30),
            nullable=True,
            comment="Market regime at signal generation time",
        )
    )
    op.add_column("signal_outcomes",
        sa.Column(
            "signal_engine_version",
            sa.String(20),
            nullable=True,
            comment="equity_signal_engine.EQUITY_SCORING_VERSION at signal generation time",
        )
    )


def downgrade() -> None:
    op.drop_column("signal_outcomes", "signal_engine_version")
    op.drop_column("signal_outcomes", "regime")
    op.drop_column("trades", "regime")
