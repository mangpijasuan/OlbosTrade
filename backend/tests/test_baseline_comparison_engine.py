"""
Coverage for the Strategy Comparison research tool (baseline_comparison_engine.py):
the shared position simulator, each baseline's signal-generation state machine,
the "Ours" delegation to the real production signal engine, and one
end-to-end comparison run against a synthetic price series (no network calls).
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from app.services.baseline_comparison_engine import (
    MODEL_NAMES,
    Trade,
    _buy_and_hold_actions,
    _cross_actions,
    _macd_cross_actions,
    _ours_actions,
    _rsi_threshold_actions,
    generate_comparison,
    simulate_positions,
)


def _assert_valid_state_machine(actions: list[str]) -> None:
    """A flat/long position can never buy twice without selling in between,
    nor sell while already flat -- true for every baseline's action sequence."""
    in_position = False
    for a in actions:
        assert a in ("BUY", "SELL", "HOLD")
        if a == "BUY":
            assert not in_position, "bought while already in a position"
            in_position = True
        elif a == "SELL":
            assert in_position, "sold while not in a position"
            in_position = False


# ── _buy_and_hold_actions ─────────────────────────────────────────────────────
def test_buy_and_hold_buys_exactly_at_start_idx():
    actions = _buy_and_hold_actions(10, start_idx=3)
    assert actions[3] == "BUY"
    assert actions[:3] == ["HOLD"] * 3
    assert actions[4:] == ["HOLD"] * 6


# ── _cross_actions (shared by SMA/MACD) ──────────────────────────────────────
def test_cross_actions_detects_upward_and_downward_cross():
    above = pd.Series([False, False, False, True, True, True, False, False])
    actions = _cross_actions(above, start_idx=0)
    assert actions[3] == "BUY"     # False -> True
    assert actions[6] == "SELL"    # True -> False
    _assert_valid_state_machine(actions)


def test_cross_actions_ignores_crosses_before_start_idx():
    # Cross at index 2 happens before start_idx=5 -- must not appear as an action.
    above = pd.Series([False, False, True, True, True, False, False, True])
    actions = _cross_actions(above, start_idx=5)
    assert actions[:5] == ["HOLD"] * 5
    assert "BUY" not in actions[:5]
    _assert_valid_state_machine(actions)


# ── _rsi_threshold_actions ────────────────────────────────────────────────────
def test_rsi_threshold_buys_oversold_sells_overbought():
    # Flat, then a sharp decline (oversold), then a sharp rally (overbought).
    flat = [100.0] * 20
    decline = list(np.linspace(100, 60, 15))
    rally = list(np.linspace(60, 140, 20))
    close = pd.Series(flat + decline + rally)
    actions = _rsi_threshold_actions(close, start_idx=0)
    assert "BUY" in actions
    assert "SELL" in actions
    _assert_valid_state_machine(actions)


def test_rsi_threshold_respects_start_idx():
    flat = [100.0] * 20
    decline = list(np.linspace(100, 60, 15))
    close = pd.Series(flat + decline)
    # Oversold condition happens near the end of `decline` -- starting the
    # window after that point should suppress the buy that would otherwise fire.
    actions = _rsi_threshold_actions(close, start_idx=len(close) - 1)
    assert actions[:-1] == ["HOLD"] * (len(close) - 1)


# ── _macd_cross_actions ───────────────────────────────────────────────────────
def test_macd_cross_actions_is_a_valid_state_machine():
    trend_up = list(np.linspace(100, 160, 40))
    trend_down = list(np.linspace(160, 100, 40))
    close = pd.Series(trend_up + trend_down)
    actions = _macd_cross_actions(close, start_idx=0)
    _assert_valid_state_machine(actions)
    assert "BUY" in actions or "SELL" in actions  # some cross must fire over up+down


# ── simulate_positions ────────────────────────────────────────────────────────
def test_simulate_positions_scripted_round_trip():
    dates = ["d0", "d1", "d2", "d3"]
    closes = [100.0, 110.0, 105.0, 120.0]
    actions = ["BUY", "HOLD", "SELL", "HOLD"]
    trades, equity_curve = simulate_positions(dates, closes, actions, starting_capital=1000.0)

    assert trades == [Trade(entry_date="d0", exit_date="d2", entry_price=100.0,
                             exit_price=105.0, pnl=50.0, hold_days=2)]
    assert equity_curve == [1000.0, 1100.0, 1050.0, 1050.0]


def test_simulate_positions_force_closes_open_position_at_end():
    # Buy & Hold shape: never sells -- must still produce a realized trade at
    # the last bar, or calculate_all_metrics would see zero trades and report
    # a flat 0% return despite the equity curve having moved.
    dates = ["d0", "d1", "d2"]
    closes = [100.0, 110.0, 120.0]
    actions = ["BUY", "HOLD", "HOLD"]
    trades, equity_curve = simulate_positions(dates, closes, actions, starting_capital=1000.0)

    assert len(trades) == 1
    assert trades[0].exit_date == "d2"
    assert trades[0].pnl == pytest.approx(200.0)
    assert equity_curve == [1000.0, 1100.0, 1200.0]


def test_simulate_positions_no_actions_is_flat_equity():
    dates = ["d0", "d1"]
    closes = [50.0, 55.0]
    trades, equity_curve = simulate_positions(dates, closes, ["HOLD", "HOLD"], starting_capital=500.0)
    assert trades == []
    assert equity_curve == [500.0, 500.0]


# ── _ours_actions delegation ──────────────────────────────────────────────────
def test_ours_actions_delegates_to_score_equity_signal_per_bar():
    df = pd.DataFrame({
        "open": np.linspace(100, 140, 40), "high": np.linspace(101, 141, 40),
        "low": np.linspace(99, 139, 40), "close": np.linspace(100, 140, 40),
        "volume": [1_000] * 40,
    })
    start_idx, end_idx = 35, 39   # 5 bars

    with patch("app.services.equity_signal_engine.compute_indicators", return_value={"rsi": 50}) as mock_ind, \
         patch("app.services.equity_signal_engine.score_equity_signal",
               return_value=("BUY", 0.8, {})) as mock_score:
        actions = _ours_actions(df, start_idx, end_idx)

    assert actions == ["BUY"] * 5
    assert mock_score.call_count == 5
    # Expanding window: window length grows by 1 each call (36, 37, 38, 39, 40).
    window_lengths = [len(call.args[0]) for call in mock_ind.call_args_list]
    assert window_lengths == [36, 37, 38, 39, 40]


def test_ours_actions_holds_when_indicators_unavailable():
    df = pd.DataFrame({
        "open": [1.0] * 10, "high": [1.0] * 10, "low": [1.0] * 10,
        "close": [1.0] * 10, "volume": [1] * 10,
    })
    # len(df) < 30 at every step in this tiny frame -> compute_indicators is
    # never even reached, should just fall back to HOLD for every bar.
    actions = _ours_actions(df, start_idx=5, end_idx=9)
    assert actions == ["HOLD"] * 5


# ── generate_comparison end-to-end (no network) ──────────────────────────────
def _synthetic_history(n: int = 300) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=n)
    # Up-down-up cycle so every baseline has something to react to.
    trend = np.concatenate([
        np.linspace(100, 160, n // 3),
        np.linspace(160, 110, n // 3),
        np.linspace(110, 180, n - 2 * (n // 3)),
    ])
    noise = np.sin(np.linspace(0, 40, n)) * 2
    close = trend + noise
    df = pd.DataFrame({
        "open": close, "high": close + 1, "low": close - 1,
        "close": close, "volume": np.full(n, 1_000_000.0),
    }, index=dates)
    return df


def test_generate_comparison_end_to_end_all_models_present():
    synthetic = _synthetic_history(300)
    start = synthetic.index[250].date().isoformat()
    end = synthetic.index[299].date().isoformat()

    with patch("app.services.baseline_comparison_engine._load_daily_bars", return_value=synthetic):
        result = generate_comparison("TEST", start, end, starting_capital=10_000.0)

    assert result["symbol"] == "TEST"
    assert len(result["models"]) == len(MODEL_NAMES)
    names = {m["name"] for m in result["models"]}
    assert names == set(MODEL_NAMES)

    for model in result["models"]:
        m = model["metrics"]
        for key in ("cumulative_return_pct", "annual_return_pct", "sharpe_ratio", "max_drawdown_pct"):
            assert key in m and np.isfinite(m[key])
        assert len(model["equity_curve"]) == len(result["bars"])


def test_generate_comparison_rejects_short_date_range():
    synthetic = _synthetic_history(300)
    start = synthetic.index[250].date().isoformat()
    end = synthetic.index[255].date().isoformat()   # only ~5 trading days

    with patch("app.services.baseline_comparison_engine._load_daily_bars", return_value=synthetic):
        with pytest.raises(ValueError, match="30 trading days"):
            generate_comparison("TEST", start, end)


def test_generate_comparison_rejects_invalid_symbol():
    with pytest.raises(ValueError, match="invalid symbol"):
        generate_comparison("!!!", "2024-01-01", "2024-06-01")
