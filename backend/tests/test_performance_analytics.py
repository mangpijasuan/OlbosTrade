"""Tests for portfolio performance analytics (deterministic, no network)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.services.performance_analytics import (
    compute_performance, _curve_metrics, _to_date, _trade_drawdowns,
)


def _t(pnl, entry, exit_):
    return {"pnl": pnl, "entry_date": date.fromisoformat(entry),
            "exit_date": date.fromisoformat(exit_)}


def test_empty_returns_zeroed_with_warning():
    r = compute_performance([], 10000.0)
    assert r["total_trades"] == 0 and r["sample_size_warning"] is True
    assert r["sharpe"] == 0.0 and r["profit_factor"] == 0.0


def test_skips_none_pnl():
    r = compute_performance([{"pnl": None, "entry_date": None, "exit_date": None}], 10000.0)
    assert r["total_trades"] == 0


def test_basic_trade_stats():
    trades = [
        _t(100, "2024-01-01", "2024-01-05"),
        _t(-50, "2024-01-06", "2024-01-08"),
        _t(200, "2024-01-09", "2024-01-12"),
        _t(-25, "2024-01-13", "2024-01-15"),
    ]
    r = compute_performance(trades, 10000.0, min_sample=3)
    assert r["total_trades"] == 4
    assert r["wins"] == 2 and r["losses"] == 2
    assert r["win_rate"] == 0.5
    assert r["total_pnl"] == 225.0
    assert r["avg_win"] == 150.0          # (100+200)/2
    assert r["avg_loss"] == -37.5         # (-50-25)/2
    assert r["expectancy"] == round(225.0 / 4, 2)
    assert r["profit_factor"] == round(300 / 75, 2)   # 4.0
    assert r["payoff_ratio"] == round(150 / 37.5, 2)  # 4.0
    assert r["avg_hold_days"] > 0
    assert r["sample_size_warning"] is False


def test_profit_factor_zero_when_no_losses():
    trades = [_t(100, "2024-01-01", "2024-01-02"), _t(50, "2024-01-03", "2024-01-04")]
    r = compute_performance(trades, 10000.0)
    assert r["profit_factor"] == 0.0      # guarded (no gross loss)
    assert r["losses"] == 0 and r["win_rate"] == 1.0


def test_curve_metrics_present_with_dates():
    # Steady winners across distinct days → positive CAGR, low drawdown
    trades = [_t(100, "2024-01-01", f"2024-01-{d:02d}") for d in range(2, 20)]
    r = compute_performance(trades, 10000.0)
    assert r["cagr_pct"] != 0.0 or r["total_pnl"] > 0
    assert "sortino" in r and "calmar" in r


def test_curve_metrics_helper_short_series():
    m = _curve_metrics([100.0])
    assert m["sharpe"] == 0.0 and m["max_drawdown_pct"] == 0.0


def test_curve_metrics_helper_drawdown():
    m = _curve_metrics([100.0, 120.0, 60.0, 90.0])
    assert m["max_drawdown_pct"] > 0.0      # dropped from 120 to 60
    assert "calmar" in m and "sortino" in m


def test_to_date_handles_all_types():
    assert _to_date(None) is None
    assert _to_date(datetime(2024, 1, 2, 9, 30)) == date(2024, 1, 2)   # datetime → date
    assert _to_date(date(2024, 1, 2)) == date(2024, 1, 2)             # date passthrough
    assert _to_date("2024-01-02") == date(2024, 1, 2)                 # string parse
    assert _to_date(object()) is None                                 # unparseable → None


def test_mixed_date_types_and_missing_dates():
    trades = [
        {"pnl": 100.0, "entry_date": datetime(2024, 1, 1), "exit_date": datetime(2024, 1, 3)},
        {"pnl": -40.0, "entry_date": "2024-01-04", "exit_date": "2024-01-06"},
        {"pnl": 60.0, "entry_date": None, "exit_date": None},   # no dates → skipped in curve
    ]
    r = compute_performance(trades, 10000.0, min_sample=1)
    assert r["total_trades"] == 3
    assert r["total_pnl"] == 120.0
    assert r["avg_hold_days"] > 0   # from the two dated trades


def test_sample_size_warning_threshold():
    trades = [_t(10, "2024-01-01", "2024-01-02")]
    assert compute_performance(trades, 10000.0, min_sample=30)["sample_size_warning"] is True
    big = [_t(10, "2024-01-01", f"2024-02-{(i % 27) + 1:02d}") for i in range(35)]
    assert compute_performance(big, 10000.0, min_sample=30)["sample_size_warning"] is False


# ── rolling (trade-ordered) drawdowns ─────────────────────────────────────────
def test_trade_drawdowns_empty_is_zeroed():
    d = _trade_drawdowns([], 10000.0)
    assert d["current_drawdown_pct"] == 0.0
    assert d["max_drawdown_trades_pct"] == 0.0
    assert d["rolling_max_dd_30_pct"] == 0.0 and d["rolling_max_dd_90_pct"] == 0.0


def test_trade_drawdowns_basic_math():
    # +100 → 10100 peak, then -200 → 9900: drawdown = 200/10100 ≈ 1.98%
    d = _trade_drawdowns([100.0, -200.0], 10000.0)
    assert d["max_drawdown_trades_pct"] == pytest.approx(1.98, abs=0.05)
    assert d["current_drawdown_pct"] == pytest.approx(1.98, abs=0.05)  # still underwater


def test_trade_drawdowns_recovers_current_below_max():
    # dip then full recovery → current DD 0, but max DD records the dip
    d = _trade_drawdowns([100.0, -300.0, 400.0], 10000.0)
    assert d["max_drawdown_trades_pct"] > 0.0
    assert d["current_drawdown_pct"] == 0.0


def test_rolling_window_isolates_recent_losses():
    # 50 small winners then a sharp loser: the trailing-30 window peak resets, so
    # the rolling-30 DD reflects only the recent loser, not the whole history.
    pnls = [10.0] * 50 + [-500.0]
    d = _trade_drawdowns(pnls, 10000.0)
    assert d["rolling_max_dd_30_pct"] > 0.0
    assert d["rolling_max_dd_30_pct"] <= d["max_drawdown_trades_pct"] + 0.01


def test_compute_performance_includes_rolling_dd():
    trades = [_t(100, "2024-01-01", "2024-01-02"),
              _t(-300, "2024-01-03", "2024-01-04"),
              _t(50, "2024-01-05", "2024-01-06")]
    r = compute_performance(trades, 10000.0, min_sample=1)
    for k in ("current_drawdown_pct", "max_drawdown_trades_pct",
              "rolling_max_dd_30_pct", "rolling_max_dd_90_pct"):
        assert k in r
    assert r["max_drawdown_trades_pct"] > 0.0


def test_empty_performance_has_rolling_dd_keys():
    r = compute_performance([], 10000.0)
    assert r["rolling_max_dd_30_pct"] == 0.0
    assert r["current_drawdown_pct"] == 0.0


def test_rolling_dd_without_exit_dates():
    # No exit dates → calendar curve skipped, but trade-ordered rolling DD still
    # computes (chronological sort falls back to date.min for all).
    trades = [{"pnl": 100.0, "entry_date": None, "exit_date": None},
              {"pnl": -250.0, "entry_date": None, "exit_date": None}]
    r = compute_performance(trades, 10000.0, min_sample=1)
    assert r["max_drawdown_pct"] == 0.0          # calendar curve skipped
    assert r["max_drawdown_trades_pct"] > 0.0    # trade-ordered DD present
