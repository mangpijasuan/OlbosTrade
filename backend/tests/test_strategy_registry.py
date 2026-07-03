from datetime import date
from decimal import Decimal

from app.models.strategy_profile import StrategyProfile
from app.services.strategy_registry import compute_autopilot_eligibility, serialize_strategy_profile


def make_profile(**overrides) -> StrategyProfile:
    defaults = dict(
        strategy_id="bear_call_spread",
        name="Bear Call Spread",
        version="1.0.0",
        asset_class="options",
        supported_symbols=["SPY"],
        supported_regimes=["normal_mean_revert"],
        supported_volatility_regimes=["moderate"],
        risk_profile_compatibility=["balanced"],
        manual_eligible=True,
        copilot_eligible=True,
        autopilot_supported=True,
        lifecycle_status="autopilot_eligible",
        health_score=Decimal("82"),
        last_validation_date=date(2026, 6, 29),
        allocation_limit_pct=Decimal("0.08"),
        enabled=True,
        main_risk_warning="warning",
        validation_notes="notes",
    )
    defaults.update(overrides)
    return StrategyProfile(**defaults)


def test_autopilot_eligible_profile_passes():
    allowed, reason = compute_autopilot_eligibility(make_profile())
    assert allowed is True
    assert reason is None


def test_disabled_strategy_blocks_autopilot():
    allowed, reason = compute_autopilot_eligibility(make_profile(enabled=False))
    assert allowed is False
    assert reason == "strategy_disabled"


def test_non_eligible_lifecycle_blocks_autopilot():
    allowed, reason = compute_autopilot_eligibility(
        make_profile(lifecycle_status="paper_validated")
    )
    assert allowed is False
    assert reason == "lifecycle_status:paper_validated"


def test_low_health_blocks_autopilot():
    allowed, reason = compute_autopilot_eligibility(
        make_profile(health_score=Decimal("62"))
    )
    assert allowed is False
    assert reason == "health_score_below_threshold"


def test_serialized_profile_contains_effective_eligibility():
    payload = serialize_strategy_profile(make_profile(lifecycle_status="paper_validated"))
    assert payload["eligibility"]["manual"] is True
    assert payload["eligibility"]["copilot"] is True
    assert payload["eligibility"]["autopilot"] is False
    assert payload["autopilot_block_reason"] == "lifecycle_status:paper_validated"
