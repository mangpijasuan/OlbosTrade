"""Tests for the shared Opportunity Score (opportunity_score.py) — a 0-100
display wrapper over trade_frequency_controller.weighted_score(), used by
Equity Signals, Options Signals, and Alpha Edge."""

from __future__ import annotations

from app.services.opportunity_score import compute_opportunity_score
from app.services.trade_frequency_controller import weighted_score


def _equity(conf, rr=2.0, vol_ratio=1.0):
    return {"ticker": "AAPL", "action": "BUY", "confidence": conf,
            "trade_plan": {"risk_reward": rr},
            "indicators": {"volume_ratio": vol_ratio}}


def _options(score, credit=150.0, max_loss=350.0):
    return {"ticker": "SPY", "asset_type": "options", "signal_score": score,
            "spread": {"net_credit": credit, "max_loss": max_loss}}


def test_score_is_0_100_scaled_weighted_score():
    sig = _equity(0.82, rr=2.5, vol_ratio=1.4)
    result = compute_opportunity_score(sig)
    assert result["score"] == int(round(weighted_score(sig) * 100))


def test_score_in_valid_range_for_equity_and_options():
    for sig in (_equity(0.5, rr=1.0, vol_ratio=0.5), _options(0.7)):
        result = compute_opportunity_score(sig)
        assert 0 <= result["score"] <= 100


def test_components_present_and_normalized():
    result = compute_opportunity_score(_equity(0.9, rr=3.0, vol_ratio=2.0))
    components = result["components"]
    assert set(components) == {"confidence", "ev", "reward_risk", "liquidity", "regime"}
    for v in components.values():
        assert 0.0 <= v <= 1.0


def test_higher_quality_signal_scores_higher():
    weak = compute_opportunity_score(_equity(0.5, rr=1.0, vol_ratio=0.5))
    strong = compute_opportunity_score(_equity(0.95, rr=3.0, vol_ratio=2.0))
    assert strong["score"] > weak["score"]


def test_missing_fields_degrade_gracefully_not_crash():
    result = compute_opportunity_score({"ticker": "XYZ"})
    assert 0 <= result["score"] <= 100
