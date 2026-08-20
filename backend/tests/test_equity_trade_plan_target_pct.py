"""
compute_equity_trade_plan's target_move_pct field — lets a caller judge a
signal's projected size (e.g. "only show setups targeting 5%+") without
recomputing (target_price - entry_price) / entry_price everywhere the trade
plan is displayed (Desk signals, Chart's Signal Detail drawer, etc).
"""

from __future__ import annotations

from app.services.equity_signal_engine import compute_equity_trade_plan


def _ind(close: float, atr: float) -> dict:
    return {"close": close, "atr": atr}


def test_buy_target_move_pct_matches_four_atr_over_entry():
    # entry=100, atr=5 -> target = 100 + 4*5 = 120 -> 20% move
    plan = compute_equity_trade_plan(_ind(100.0, 5.0), "BUY", portfolio_value=100_000.0)
    assert plan["target_price"] == 120.0
    assert plan["target_move_pct"] == 20.0


def test_sell_target_move_pct_matches_four_atr_over_entry():
    # entry=100, atr=5 -> target = 100 - 4*5 = 80 -> 20% move (always positive)
    plan = compute_equity_trade_plan(_ind(100.0, 5.0), "SELL", portfolio_value=100_000.0)
    assert plan["target_price"] == 80.0
    assert plan["target_move_pct"] == 20.0


def test_low_volatility_name_has_a_small_target_move_pct():
    # A low-ATR/high-price name (e.g. SPY) should show a modest projected move,
    # not the same double-digit % as a high-ATR name.
    plan = compute_equity_trade_plan(_ind(775.0, 8.5), "BUY", portfolio_value=100_000.0)
    assert plan["target_move_pct"] == round(4 * 8.5 / 775.0 * 100, 2)
    assert plan["target_move_pct"] < 5.0


def test_hold_action_returns_no_target_move_pct():
    plan = compute_equity_trade_plan(_ind(100.0, 5.0), "HOLD", portfolio_value=100_000.0)
    assert "target_move_pct" not in plan
    assert plan == {"entry_price": 100.0, "action": "HOLD"}


def test_tiny_portfolio_may_size_to_zero_shares():
    """Do not force max(1) — OMS skips zero-size instead of a 1-share floor."""
    # $50 portfolio, $100 stock, $10 risk/share → base shares floor to 0
    plan = compute_equity_trade_plan(_ind(100.0, 5.0), "BUY", portfolio_value=50.0)
    assert plan["shares"] == 0
