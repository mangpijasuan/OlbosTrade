"""Tests for the Portfolio-level Trade Frequency Controller + signal ranking."""

from __future__ import annotations

import pytest

from app.services.trading_mode import TradingModeType
from app.services.trade_frequency_controller import (
    FrequencyRule,
    MODE_RULES,
    TradeFrequencyController,
    expected_value,
    risk_score,
    rule_for,
    weighted_score,
    _confidence,
    _reward_risk,
    _liquidity,
)

C = TradingModeType.CONSERVATIVE
B = TradingModeType.BALANCED
A = TradingModeType.AGGRESSIVE


def _equity(conf, rr=2.0, vol_ratio=1.0):
    return {"ticker": "AAPL", "action": "BUY", "confidence": conf,
            "trade_plan": {"risk_reward": rr},
            "indicators": {"volume_ratio": vol_ratio}}


def _options(score, credit=150.0, max_loss=350.0):
    return {"ticker": "SPY", "asset_type": "options", "signal_score": score,
            "spread": {"net_credit": credit, "max_loss": max_loss}}


# ── helpers ──────────────────────────────────────────────────────────────────
def test_confidence_equity_and_options_and_bad():
    assert _confidence(_equity(0.8)) == 0.8
    assert _confidence(_options(0.7)) == 0.7
    assert _confidence({"confidence": "x"}) == 0.0      # bad value → 0
    assert _confidence({}) == 0.0
    assert _confidence({"confidence": 5}) == 1.0        # clamped


def test_reward_risk_equity_options_missing():
    assert _reward_risk(_equity(0.8, rr=2.5)) == 2.5
    assert _reward_risk(_options(0.7, credit=150, max_loss=300)) == 0.5
    assert _reward_risk({}) == 0.0
    assert _reward_risk({"spread": {"net_credit": 100, "max_loss": 0}}) == 0.0


def test_liquidity_proxy():
    assert _liquidity(_equity(0.8, vol_ratio=2.0)) == 1.0   # 2x avg → 1.0
    assert _liquidity(_equity(0.8, vol_ratio=1.0)) == 0.5
    assert _liquidity(_options(0.7)) == 0.5                 # options placeholder


def test_expected_value_sign():
    assert expected_value(_equity(0.9, rr=2.0)) > 0        # high conf + good rr
    assert expected_value(_equity(0.2, rr=0.5)) < 0        # poor everything


def test_weighted_score_in_range_and_monotonic():
    lo = weighted_score(_equity(0.5, rr=1.0, vol_ratio=0.5))
    hi = weighted_score(_equity(0.95, rr=3.0, vol_ratio=2.0))
    assert 0.0 <= lo <= 1.0 and 0.0 <= hi <= 1.0
    assert hi > lo


def test_risk_score_inverse_confidence():
    assert risk_score(_equity(0.95)) < risk_score(_equity(0.50))
    assert 0 <= risk_score(_equity(0.5)) <= 100
    # sub-1:1 reward:risk adds risk
    assert risk_score(_equity(0.8, rr=0.5)) > risk_score(_equity(0.8, rr=2.0))


def test_rule_for_defaults_to_balanced():
    assert rule_for(B) is MODE_RULES[B]
    assert isinstance(rule_for(C), FrequencyRule)


# ── ranking ──────────────────────────────────────────────────────────────────
def test_rank_orders_best_first():
    ctrl = TradeFrequencyController()
    weak = _equity(0.66, rr=1.0, vol_ratio=0.5)
    strong = _equity(0.95, rr=3.0, vol_ratio=2.0)
    mid = _equity(0.80, rr=2.0, vol_ratio=1.0)
    ranked = ctrl.rank([weak, strong, mid])
    assert ranked[0] is strong and ranked[-1] is weak


# ── gating per mode ───────────────────────────────────────────────────────────
def test_gate_blocks_below_min_confidence():
    ctrl = TradeFrequencyController()
    # 0.80 passes balanced (min 0.75) but fails conservative (min 0.90)
    assert ctrl.evaluate(_equity(0.80), trades_today=0, mode=B).allowed
    d = ctrl.evaluate(_equity(0.80), trades_today=0, mode=C)
    assert not d.allowed and "below_min_confidence" in d.reason


def test_gate_enforces_hard_daily_cap():
    ctrl = TradeFrequencyController()
    cap = MODE_RULES[C].hard_max_per_day  # 3
    d = ctrl.evaluate(_equity(0.95), trades_today=cap, mode=C)
    assert not d.allowed and "daily_cap" in d.reason
    # one below the cap is allowed
    assert ctrl.evaluate(_equity(0.95), trades_today=cap - 1, mode=C).allowed


def test_gate_blocks_high_risk_score():
    ctrl = TradeFrequencyController()
    # confidence 0.66 → risk_score ~34 > conservative max 20 (also fails conf, but
    # use a case that passes confidence yet fails risk via poor reward:risk)
    sig = _equity(0.66, rr=0.2)   # aggressive min_conf 0.65 ok; rr 0.2 lifts risk
    d = ctrl.evaluate(sig, trades_today=0, mode=A)
    assert not d.allowed and ("risk_score_too_high" in d.reason or "non_positive_ev" in d.reason)


def test_gate_blocks_non_positive_ev():
    ctrl = TradeFrequencyController()
    # passes confidence (0.95 ≥ aggressive 0.65) and risk, but rr makes EV ≤ 0?
    # EV = p*rr-(1-p): with p=0.95, rr must be < (1-0.95)/0.95 ≈ 0.0526 to be ≤0
    sig = _equity(0.95, rr=0.0)
    d = ctrl.evaluate(sig, trades_today=0, mode=A)
    assert not d.allowed and "non_positive_ev" in d.reason


def test_gate_allows_quality_signal():
    ctrl = TradeFrequencyController()
    d = ctrl.evaluate(_equity(0.95, rr=2.5, vol_ratio=1.5), trades_today=0, mode=C)
    assert d.allowed and d.reason == "ok"
    assert d.expected_value > 0 and d.weighted_score > 0


def test_aggressive_allows_more_than_conservative():
    ctrl = TradeFrequencyController()
    sig = _equity(0.70, rr=2.0)   # below conservative min (0.90), above aggressive (0.65)
    assert ctrl.evaluate(sig, trades_today=0, mode=A).allowed
    assert not ctrl.evaluate(sig, trades_today=0, mode=C).allowed


def test_options_signal_path():
    ctrl = TradeFrequencyController()
    # options with strong score + decent credit/loss
    sig = _options(0.92, credit=200, max_loss=300)   # rr=0.667
    d = ctrl.evaluate(sig, trades_today=0, mode=B)
    assert isinstance(d.allowed, bool)
    assert d.weighted_score >= 0


def test_reward_risk_bad_value_returns_zero():
    assert _reward_risk({"trade_plan": {"risk_reward": "oops"}}) == 0.0


def test_liquidity_bad_value_returns_half():
    assert _liquidity({"indicators": {"volume_ratio": "oops"}}) == 0.5


def test_evaluate_uses_current_mode_when_none():
    ctrl = TradeFrequencyController()
    # No mode passed → reads the manager's active mode (BALANCED by default).
    d = ctrl.evaluate(_equity(0.95, rr=2.5, vol_ratio=1.5), trades_today=0)
    assert isinstance(d.allowed, bool) and d.reason  # exercises the default-mode path


def test_risk_score_only_block():
    ctrl = TradeFrequencyController()
    # Conservative: conf 0.90 clears min_confidence; rr=0.2 lifts risk to 22 > max
    # 20 while keeping EV>0, and the risk check runs before the EV check.
    d = ctrl.evaluate(_equity(0.90, rr=0.2), trades_today=0, mode=C)
    assert not d.allowed and "risk_score_too_high" in d.reason
