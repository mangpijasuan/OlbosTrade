"""Tests for the composable strategy engine (symphony) — deterministic, no network."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.symphony import (
    StrategyError,
    collect_tickers,
    evaluate,
    normalize,
    run_backtest,
    example_strategies,
)


def _series(values):
    idx = pd.date_range("2023-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype=float)


def test_asset_node_full_weight():
    out = evaluate({"type": "asset", "ticker": "SPY"}, {"SPY": _series([1, 2, 3])})
    assert out == {"SPY": 1.0}


def test_equal_weight():
    data = {"A": _series([1, 2]), "B": _series([1, 2])}
    out = evaluate({"type": "weight_equal", "children": [
        {"type": "asset", "ticker": "A"}, {"type": "asset", "ticker": "B"}]}, data)
    assert out == {"A": 0.5, "B": 0.5}


def test_if_branches_on_price_vs_sma():
    # SPY rising → last price above SMA-3 → 'then' (SPY); else TLT
    data = {"SPY": _series([10, 11, 12, 20]), "TLT": _series([5, 5, 5, 5])}
    tree = {"type": "if",
            "condition": {"lhs": {"fn": "price", "ticker": "SPY"}, "op": ">",
                          "rhs": {"fn": "sma", "ticker": "SPY", "window": 3}},
            "then": {"type": "asset", "ticker": "SPY"},
            "else": {"type": "asset", "ticker": "TLT"}}
    assert evaluate(tree, data) == {"SPY": 1.0}
    # Falling SPY → below SMA → TLT
    data2 = {"SPY": _series([20, 18, 16, 10]), "TLT": _series([5, 5, 5, 5])}
    assert evaluate(tree, data2) == {"TLT": 1.0}


def test_filter_top_by_return():
    # B has the highest cumulative return → top-1 picks B
    data = {
        "A": _series([100, 101, 102]),
        "B": _series([100, 120, 150]),
        "C": _series([100, 99, 98]),
    }
    tree = {"type": "filter", "select": "top", "n": 1,
            "by": {"fn": "cumulative_return", "window": 2},
            "children": [{"type": "asset", "ticker": t} for t in ("A", "B", "C")]}
    assert evaluate(tree, data) == {"B": 1.0}


def test_inverse_vol_favors_calm_asset():
    rng = np.random.default_rng(0)
    calm = _series(100 + np.cumsum(rng.normal(0, 0.1, 60)))
    wild = _series(100 + np.cumsum(rng.normal(0, 3.0, 60)))
    data = {"CALM": calm, "WILD": wild}
    out = evaluate({"type": "weight_inverse_vol", "window": 20, "children": [
        {"type": "asset", "ticker": "CALM"}, {"type": "asset", "ticker": "WILD"}]}, data)
    assert out["CALM"] > out["WILD"]


def test_normalize_drops_zero_and_scales():
    assert normalize({"A": 3.0, "B": 1.0, "C": 0.0}) == {"A": 0.75, "B": 0.25}


def test_collect_tickers_walks_tree():
    tree = example_strategies()[2]["tree"]  # RSI mean-reversion w/ BIL + SPY/TLT/GLD
    assert collect_tickers(tree) == {"SPY", "TLT", "GLD", "BIL"}


def test_unknown_node_raises():
    with pytest.raises(StrategyError):
        evaluate({"type": "nonsense"}, {})


def test_backtest_runs_and_reports_metrics():
    # Two assets; weekly rebalance over ~1 year of synthetic data
    n = 300
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    up = pd.Series(100 * (1.0005 ** np.arange(n)), index=idx)
    flat = pd.Series(100 * (1.0001 ** np.arange(n)), index=idx)
    closes = pd.DataFrame({"SPY": up, "TLT": flat})
    tree = {"type": "weight_equal", "children": [
        {"type": "asset", "ticker": "SPY"}, {"type": "asset", "ticker": "TLT"}]}
    res = run_backtest(tree, closes, idx[0].date(), idx[-1].date(),
                       cadence="weekly", starting_capital=10000.0)
    assert len(res["equity_curve"]) > 200
    assert res["rebalances"] > 10
    assert res["equity_curve"][-1]["value"] > 10000  # both assets drift up
    assert "sharpe" in res["metrics"] and "max_drawdown_pct" in res["metrics"]
    assert abs(sum(res["final_weights"].values()) - 1.0) < 1e-6
