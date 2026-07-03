from datetime import datetime, timezone

from app.models.strategy_preset import StrategyPreset
from app.models.strategy_snapshot import StrategySnapshot
from app.services.strategy_config_service import (
    compare_snapshots,
    serialize_preset,
    serialize_snapshot,
)


def make_preset(**overrides) -> StrategyPreset:
    defaults = dict(
        preset_id="options_income_bear_call_v1",
        strategy_id="bear_call_spread",
        category="Options Income",
        preset_name="Bear Call Spread",
        version="1.0.0",
        market_regime_requirements=["normal_mean_revert"],
        volatility_requirements=["moderate"],
        timeframe="21-35 DTE",
        entry_rules={"short_delta_max": 0.28},
        exit_rules={"profit_target_pct": 0.5},
        risk_rules={"defined_risk_only": True},
        position_sizing_policy={"risk_per_trade_pct": 0.02},
        confidence_threshold=0.67,
        event_risk_restrictions=["avoid_fomc_window"],
        max_allocation_pct=0.08,
        risk_profile_compatibility=["balanced"],
        validation_status="live_validated",
        paper_validated=True,
        live_validated=True,
        author="OlbosQuant",
        approval_owner="Risk Committee",
        approval_notes="baseline",
        enabled=True,
    )
    defaults.update(overrides)
    return StrategyPreset(**defaults)


def make_snapshot(**overrides) -> StrategySnapshot:
    defaults = dict(
        snapshot_id="bear_call_spread.baseline.v1",
        strategy_id="bear_call_spread",
        version="1.0.0",
        label="Bear Call Baseline",
        notes="seeded",
        risk_profile="balanced",
        lifecycle_status="autopilot_eligible",
        validation_status="live_validated",
        config_payload={"confidence_threshold": 0.67, "timeframe": "21-35 DTE"},
        is_active=True,
        inherited_from_verified_preset=True,
        created_by="OlbosQuant",
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return StrategySnapshot(**defaults)


def test_serialize_preset_exposes_validation_fields():
    payload = serialize_preset(make_preset())
    assert payload["preset_id"] == "options_income_bear_call_v1"
    assert payload["validation_status"] == "live_validated"
    assert payload["live_validated"] is True


def test_serialize_snapshot_marks_active_state():
    payload = serialize_snapshot(make_snapshot())
    assert payload["snapshot_id"] == "bear_call_spread.baseline.v1"
    assert payload["is_active"] is True
    assert payload["inherited_from_verified_preset"] is True


def test_compare_snapshots_reports_payload_and_meta_changes():
    left = make_snapshot(
        label="Baseline",
        risk_profile="balanced",
        config_payload={"confidence_threshold": 0.67, "timeframe": "21-35 DTE"},
    )
    right = make_snapshot(
        snapshot_id="bear_call_spread.custom.v1",
        label="Custom",
        risk_profile="aggressive",
        config_payload={"confidence_threshold": 0.72, "timeframe": "14-21 DTE"},
        is_active=False,
    )
    diff = compare_snapshots(left, right)
    assert diff["config_diff"]["confidence_threshold"]["left"] == 0.67
    assert diff["config_diff"]["confidence_threshold"]["right"] == 0.72
    assert diff["meta_diff"]["risk_profile"]["left"] == "balanced"
    assert diff["meta_diff"]["label"]["right"] == "Custom"
