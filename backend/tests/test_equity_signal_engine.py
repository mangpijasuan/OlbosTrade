"""
Tests for EquitySignalParams — the tunable-weights refactor of
score_equity_signal()/compute_equity_trade_plan() (Track 2D, equity side).

Confirms the default-preserving contract (passing no `params`, or an
explicit EquitySignalParams(), produce byte-identical output — every live
call site relies on this) and that a non-default params object actually
changes the decision, proving the fields are really threaded through.

No SQLAlchemy import here, so unlike backtester.py-touching tests this
module runs locally on py3.9 with no wall to work around.
"""

from __future__ import annotations

from app.services.equity_signal_engine import (
    EquitySignalParams,
    score_equity_signal,
    compute_equity_trade_plan,
)


# ── score_equity_signal() ────────────────────────────────────────────────

def _bull_leaning_ind() -> dict:
    """rsi oversold (bull) + below ema200/vwap (bear) — a mixed-but-net-bull
    case that still clears the default 0.06 margin threshold."""
    return {"rsi": 32, "above_ema200": False, "above_vwap": False}


def _balanced_ind() -> dict:
    """above_ema200/above_vwap always tilt bull or bear by a fixed amount
    (the bull/bear branches for each are complementary — one of them
    always fires) so a literal zero-signal HOLD is unreachable. This dict
    nets to a near-zero margin instead: above_ema200 (bull +0.5) +
    above_vwap (bull +0.6) = 1.1 bull vs. stoch_overbought (bear +1.0) =
    1.0 bear. margin = 0.1/2.1 ≈ 0.048, under the default 0.06 floor."""
    return {"rsi": 50, "macd": 0, "macd_signal": 0, "bb_pct_b": 0.5,
             "volume_ratio": 1.0, "stoch_k": 85,
             "above_ema200": True, "above_vwap": True}


def test_score_equity_signal_no_params_matches_explicit_default():
    for ind in (_bull_leaning_ind(), _balanced_ind()):
        no_params = score_equity_signal(ind)
        explicit_default = score_equity_signal(ind, params=EquitySignalParams())
        assert no_params == explicit_default


def test_balanced_indicators_hold_under_margin_floor():
    action, confidence, reasons = score_equity_signal(_balanced_ind())
    assert action == "HOLD"
    assert reasons["above_ema200"] == 0.5
    assert reasons["above_vwap"] == 0.6
    assert reasons["stoch_overbought"] == -1.0


def test_default_rsi_oversold_threshold_fires_buy():
    ind = _bull_leaning_ind()
    action, confidence, reasons = score_equity_signal(ind)
    assert action == "BUY"
    assert reasons["rsi_oversold"] == 1.5


def test_tighter_rsi_oversold_threshold_flips_the_decision():
    """rsi=32 clears the default threshold (35) but not a tightened one
    (30) — proves the threshold is really read from params, not hardcoded.
    With the rsi contribution removed, the below_ema200/below_vwap bear
    points dominate and the action flips from BUY to SELL."""
    ind = _bull_leaning_ind()
    tight = EquitySignalParams(rsi_oversold_threshold=30.0)

    default_action, _, _ = score_equity_signal(ind)
    tight_action, _, tight_reasons = score_equity_signal(ind, params=tight)

    assert default_action == "BUY"
    assert tight_action == "SELL"
    assert "rsi_oversold" not in tight_reasons


def test_raising_min_margin_to_fire_suppresses_a_borderline_signal():
    ind = _bull_leaning_ind()
    default_action, _, _ = score_equity_signal(ind)
    strict_action, _, _ = score_equity_signal(
        ind, params=EquitySignalParams(min_margin_to_fire=0.99)
    )

    assert default_action == "BUY"
    assert strict_action == "HOLD"


# ── compute_equity_trade_plan() ──────────────────────────────────────────

def _buy_ind(entry: float = 100.0, atr: float = 5.0) -> dict:
    return {"close": entry, "atr": atr}


def test_compute_equity_trade_plan_no_params_matches_explicit_default():
    ind = _buy_ind()
    no_params = compute_equity_trade_plan(ind, "BUY", portfolio_value=25_000.0)
    explicit_default = compute_equity_trade_plan(
        ind, "BUY", portfolio_value=25_000.0, params=EquitySignalParams(),
    )
    assert no_params == explicit_default


def test_hold_action_returns_minimal_dict_regardless_of_params():
    ind = _buy_ind()
    result = compute_equity_trade_plan(
        ind, "HOLD", portfolio_value=25_000.0, params=EquitySignalParams(target_atr_multiplier=99.0),
    )
    assert result == {"entry_price": 100.0, "action": "HOLD"}


def test_default_atr_multipliers_produce_todays_stop_and_target():
    ind = _buy_ind(entry=100.0, atr=5.0)
    plan = compute_equity_trade_plan(ind, "BUY", portfolio_value=25_000.0)
    assert plan["stop_price"] == 90.0    # 100 - 5*2.0
    assert plan["target_price"] == 120.0  # 100 + 5*4.0


def test_custom_target_atr_multiplier_changes_the_target():
    ind = _buy_ind(entry=100.0, atr=5.0)
    plan = compute_equity_trade_plan(
        ind, "BUY", portfolio_value=25_000.0,
        params=EquitySignalParams(target_atr_multiplier=2.0),
    )
    assert plan["target_price"] == 110.0  # 100 + 5*2.0
    assert plan["stop_price"] == 90.0     # stop_atr_multiplier untouched


def test_custom_risk_pct_per_trade_changes_share_count():
    """max_position_pct=1.0 removes the position-size cap so risk_pct_per_trade
    (not the cap) is the binding constraint on shares — the default 0.08 cap
    would otherwise clip both the default and doubled-risk plan to the same
    20 shares, masking the very change this test is meant to prove."""
    ind = _buy_ind(entry=100.0, atr=5.0)
    default_plan = compute_equity_trade_plan(
        ind, "BUY", portfolio_value=25_000.0, max_position_pct=1.0,
    )
    doubled_risk_plan = compute_equity_trade_plan(
        ind, "BUY", portfolio_value=25_000.0, max_position_pct=1.0,
        params=EquitySignalParams(risk_pct_per_trade=0.04),
    )
    assert doubled_risk_plan["shares"] > default_plan["shares"]
