"""Seed strategy_profiles with the 4 live-executable strategies

strategy_profiles has existed since 0011 but nothing has ever populated
it — the Strategy Cards page (frontend/src/pages/Strategy.tsx) shows a
hardcoded static array instead. Seeds the same 4 strategies already used
by Trade.strategy / strategy_health.py's DEFAULT_BASELINES / the live
_execute_signal path — the strategies actually executable today, not the
larger aspirational catalog in the Trade Desk 2.0 master spec.

Deliberately NULL/empty for anything with no real per-strategy data to
cite (allocation_limit_pct, supported_symbols/regimes,
risk_profile_compatibility) rather than inventing plausible-looking
values. lifecycle_status is "paper" (not the model's "research_only"
default) since the whole app trades on paper capital only today and none
of these have cleared a promotion gate. autopilot_supported is False for
all 4, matching the model's own column default — iron_condor specifically
is restricted from autopilot in three separate live code paths
(GuardrailEngine.is_strategy_allowed in capital-preservation mode,
evaluate_options()'s outright ban, and mode/regime-conditional config in
trading_mode.py / regime_classifier.py), so asserting blanket eligibility
here would be exactly the kind of fabrication this seed is trying to
avoid.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-16
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STRATEGY_IDS = [
    "bull_put_spread",
    "bear_call_spread",
    "iron_condor",
    "bull_call_debit_spread",
]

_PROFILES = [
    {
        "strategy_id": "bull_put_spread",
        "name": "Bull Put Spread",
        "asset_class": "options",
        "lifecycle_status": "paper",
        "main_risk_warning": None,
    },
    {
        "strategy_id": "bear_call_spread",
        "name": "Bear Call Spread",
        "asset_class": "options",
        "lifecycle_status": "paper",
        "main_risk_warning": None,
    },
    {
        "strategy_id": "iron_condor",
        "name": "Iron Condor",
        "asset_class": "options",
        "lifecycle_status": "paper",
        "main_risk_warning": (
            "Suspended in capital-preservation mode and blocked outright by "
            "the evaluate-options gate regardless of execution mode — not "
            "currently eligible for autopilot."
        ),
    },
    {
        "strategy_id": "bull_call_debit_spread",
        "name": "Bull Call Debit Spread",
        "asset_class": "options",
        "lifecycle_status": "paper",
        "main_risk_warning": (
            "Debit strategy — full premium at risk. Baseline expects a "
            "~45% win rate, materially lower than the ~80% baseline for "
            "the credit spreads."
        ),
    },
]


def upgrade() -> None:
    strategy_profiles = sa.table(
        "strategy_profiles",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("strategy_id", sa.String),
        sa.column("name", sa.String),
        sa.column("version", sa.String),
        sa.column("asset_class", sa.String),
        sa.column("supported_symbols", postgresql.JSONB),
        sa.column("supported_regimes", postgresql.JSONB),
        sa.column("supported_volatility_regimes", postgresql.JSONB),
        sa.column("risk_profile_compatibility", postgresql.JSONB),
        sa.column("manual_eligible", sa.Boolean),
        sa.column("copilot_eligible", sa.Boolean),
        sa.column("autopilot_supported", sa.Boolean),
        sa.column("lifecycle_status", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("main_risk_warning", sa.Text),
    )

    conn = op.get_bind()
    for profile in _PROFILES:
        # Idempotent — strategy_id is unique-indexed; skip rows that already
        # exist rather than erroring on a re-run or a manually-seeded row.
        existing = conn.execute(
            sa.text("SELECT 1 FROM strategy_profiles WHERE strategy_id = :sid"),
            {"sid": profile["strategy_id"]},
        ).first()
        if existing:
            continue
        conn.execute(
            strategy_profiles.insert().values(
                id=uuid.uuid4(),
                strategy_id=profile["strategy_id"],
                name=profile["name"],
                version="1.0.0",
                asset_class=profile["asset_class"],
                supported_symbols=[],
                supported_regimes=[],
                supported_volatility_regimes=[],
                risk_profile_compatibility=[],
                manual_eligible=True,
                copilot_eligible=True,
                autopilot_supported=False,
                lifecycle_status=profile["lifecycle_status"],
                enabled=True,
                main_risk_warning=profile["main_risk_warning"],
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    for strategy_id in _STRATEGY_IDS:
        conn.execute(
            sa.text("DELETE FROM strategy_profiles WHERE strategy_id = :sid"),
            {"sid": strategy_id},
        )
