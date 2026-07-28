"""Tests for the Portfolio-level Trade Frequency Controller + signal ranking."""

from __future__ import annotations

import pytest

from app.services.trading_mode import TradingModeType
from app.services.trade_frequency_controller import (
    FrequencyRule,
    MODE_RULES,
    STRATEGY_MIN_POP,
    TradeFrequencyController,
    expected_value,
    risk_score,
    rule_for,
    weighted_score,
    _confidence,
    _regime_score,
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
    # 0.80 passes aggressive (min 0.70) but fails balanced (min 0.90) —
    # 2026-07-28 rebalance: Balanced now runs the old Conservative profile,
    # Aggressive now runs the old Balanced's (loosened further).
    assert ctrl.evaluate(_equity(0.80), trades_today=0, mode=A).allowed
    d = ctrl.evaluate(_equity(0.80), trades_today=0, mode=B)
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
    # confidence 0.75 clears aggressive's min_confidence (0.70, since the
    # 2026-07-28 rebalance), but poor reward:risk (0.2) still lifts risk
    # score / drags EV negative.
    sig = _equity(0.75, rr=0.2)
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
    # 0.75: below conservative's min (0.90, unchanged), above aggressive's
    # (0.70 since the 2026-07-28 rebalance) with a clear margin rather than
    # sitting exactly on the boundary.
    sig = _equity(0.75, rr=2.0)
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


# ── regime-alignment scoring ──────────────────────────────────────────────────
def test_regime_score_override_and_bounds():
    assert _regime_score({"regime_score": 0.8}) == 0.8
    assert _regime_score({"regime_score": 5}) == 1.0      # clamped
    assert _regime_score({"regime_score": "oops"}) == 0.5  # bad → lookup → no data
    assert _regime_score({}) == 0.5                        # no regime/strategy


def test_regime_score_alignment_lookup():
    # normal_mean_revert sanctions credit spreads + iron condor
    aligned = {"regime": "normal_mean_revert", "strategy": "bull_put_spread"}
    opposed = {"regime": "normal_mean_revert", "strategy": "bull_call_debit_spread"}
    assert _regime_score(aligned) == 1.0
    assert _regime_score(opposed) == 0.3
    # crisis sanctions nothing
    assert _regime_score({"regime": "crisis", "strategy": "bull_put_spread"}) == 0.0
    # unknown regime string → neutral 0.5
    assert _regime_score({"regime": "nonsense", "strategy": "bull_put_spread"}) == 0.5


def test_weighted_score_rewards_regime_alignment():
    base = dict(ticker="SPY", asset_type="options", signal_score=0.8,
                spread={"net_credit": 200, "max_loss": 300})
    aligned = {**base, "regime": "normal_mean_revert", "strategy": "bull_put_spread"}
    opposed = {**base, "regime": "crisis", "strategy": "bull_put_spread"}
    assert weighted_score(aligned) > weighted_score(opposed)


# ── probability-of-profit (POP) gates ─────────────────────────────────────────
def _opt_pop(pop, strategy="bull_put_spread", credit=200.0, max_loss=300.0):
    return {"ticker": "SPY", "asset_type": "options", "strategy": strategy,
            "signal_score": pop, "pop": pop,
            "spread": {"net_credit": credit, "max_loss": max_loss}}


def test_pop_gate_blocks_low_pop_bull_put_in_aggressive():
    ctrl = TradeFrequencyController()
    # Decouple confidence from POP (mirrors test_pop_gate_conservative_mode_floor):
    # confidence 0.90 clears Aggressive's min_confidence (0.70, since the
    # 2026-07-28 rebalance), but POP 0.68 falls under the bull-put strategy
    # floor (0.70) — isolates the strategy-level floor from the mode gate.
    sig = {"ticker": "SPY", "asset_type": "options", "strategy": "bull_put_spread",
           "confidence": 0.90, "pop": 0.68,
           "spread": {"net_credit": 200, "max_loss": 300}}
    d = ctrl.evaluate(sig, trades_today=0, mode=A)
    assert not d.allowed and "pop_below_floor" in d.reason and "0.70" in d.reason


def test_pop_gate_allows_high_pop():
    ctrl = TradeFrequencyController()
    d = ctrl.evaluate(_opt_pop(0.80), trades_today=0, mode=A)
    assert d.allowed and d.reason == "ok"


def test_pop_gate_conservative_mode_floor():
    ctrl = TradeFrequencyController()
    # Decouple confidence from POP: confidence 0.95 clears Conservative's 0.90
    # gate, but POP 0.72 falls under the Conservative mode floor (0.75). Debit
    # spread carries no strategy floor, so only the mode floor applies.
    sig = {"ticker": "SPY", "asset_type": "options", "strategy": "bull_call_debit_spread",
           "confidence": 0.95, "pop": 0.72,
           "spread": {"net_credit": 200, "max_loss": 300}}
    d = ctrl.evaluate(sig, trades_today=0, mode=C)
    assert not d.allowed and "pop_below_floor" in d.reason and "0.75" in d.reason


def test_pop_gate_skipped_for_equity():
    ctrl = TradeFrequencyController()
    # Equity signals have no 'pop' → POP gate never fires.
    assert TradeFrequencyController._pop(_equity(0.95)) is None
    d = ctrl.evaluate(_equity(0.95, rr=2.5, vol_ratio=1.5), trades_today=0, mode=A)
    assert d.allowed


def test_pop_helper_handles_bad_value():
    assert TradeFrequencyController._pop({"pop": "oops"}) is None
    assert TradeFrequencyController._pop({"pop": 5}) == 1.0   # clamped


def test_strategy_min_pop_map_covers_credit_spreads():
    assert STRATEGY_MIN_POP["bull_put_spread"] == 0.70
    assert STRATEGY_MIN_POP["bear_call_spread"] == 0.70
    assert STRATEGY_MIN_POP["iron_condor"] == 0.70


def test_execution_test_mode_bypasses_all_gates(monkeypatch):
    """With execution_test_mode on, even a junk low-confidence signal is allowed."""
    import app.core.config as cfg
    ctrl = TradeFrequencyController()
    junk = _equity(0.01)   # far below any mode's min_confidence
    # Normally blocked in Conservative (min_confidence 0.90)
    assert ctrl.evaluate(junk, trades_today=0, mode=C).allowed is False
    monkeypatch.setattr(cfg.settings, "execution_test_mode", True)
    d = ctrl.evaluate(junk, trades_today=999, mode=C)   # also over daily cap
    assert d.allowed is True and d.reason == "execution_test_mode"
