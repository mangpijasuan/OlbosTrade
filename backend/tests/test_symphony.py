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


def test_weight_specified_and_mismatch():
    data = {"A": _series([1, 2]), "B": _series([1, 2])}
    out = evaluate({"type": "weight_specified", "weights": [0.7, 0.3], "children": [
        {"type": "asset", "ticker": "A"}, {"type": "asset", "ticker": "B"}]}, data)
    assert out == {"A": 0.7, "B": 0.3}
    with pytest.raises(StrategyError):
        evaluate({"type": "weight_specified", "weights": [0.7], "children": [
            {"type": "asset", "ticker": "A"}, {"type": "asset", "ticker": "B"}]}, data)


def test_inverse_vol_all_zero_falls_back_to_equal():
    # Flat series → zero volatility → equal-weight fallback
    data = {"A": _series([10, 10, 10, 10]), "B": _series([10, 10, 10, 10])}
    out = evaluate({"type": "weight_inverse_vol", "window": 3, "children": [
        {"type": "asset", "ticker": "A"}, {"type": "asset", "ticker": "B"}]}, data)
    assert out == {"A": 0.5, "B": 0.5}


def test_filter_bottom_select():
    data = {"A": _series([100, 101, 102]), "B": _series([100, 80, 60])}
    tree = {"type": "filter", "select": "bottom", "n": 1,
            "by": {"fn": "cumulative_return", "window": 2},
            "children": [{"type": "asset", "ticker": "A"}, {"type": "asset", "ticker": "B"}]}
    assert evaluate(tree, data) == {"B": 1.0}


def test_condition_operators_and_unknown():
    data = {"X": _series([1, 2, 3, 4])}
    base = {"lhs": {"fn": "price", "ticker": "X"}, "rhs": 4}
    from app.services.symphony import _eval_condition
    assert _eval_condition({**base, "op": ">="}, data) is True
    assert _eval_condition({**base, "op": "<="}, data) is True
    assert _eval_condition({**base, "op": "=="}, data) is True
    assert _eval_condition({**base, "op": "!="}, data) is False
    assert _eval_condition({**base, "op": "<"}, data) is False
    with pytest.raises(StrategyError):
        _eval_condition({**base, "op": "??"}, data)
    with pytest.raises(StrategyError):
        _eval_condition({"lhs": base["lhs"]}, data)  # missing op/rhs


def test_indicator_errors():
    from app.services.symphony import _eval_indicator
    data = {"X": _series([1, 2, 3])}
    with pytest.raises(StrategyError):
        _eval_indicator({"fn": "nope", "ticker": "X"}, data)         # unknown fn
    with pytest.raises(StrategyError):
        _eval_indicator({"fn": "rsi", "ticker": "MISSING"}, data)    # no data
    with pytest.raises(StrategyError):
        _eval_indicator({"fn": "rsi", "ticker": "E"}, {"E": _series([])})  # empty


def test_all_indicators_compute():
    from app.services.symphony import _eval_indicator
    s = _series([float(x) for x in range(1, 60)])
    data = {"X": s}
    for fn in ("rsi", "sma", "ema", "price", "cumulative_return", "volatility", "max_drawdown"):
        val = _eval_indicator({"fn": fn, "ticker": "X", "window": 14}, data)
        assert isinstance(val, float)


def test_if_without_else_returns_empty():
    data = {"X": _series([5, 4, 3])}  # falling → price < sma → else (absent)
    tree = {"type": "if",
            "condition": {"lhs": {"fn": "price", "ticker": "X"}, "op": ">",
                          "rhs": {"fn": "sma", "ticker": "X", "window": 2}},
            "then": {"type": "asset", "ticker": "X"}}
    assert evaluate(tree, data) == {}


def test_bad_nodes_raise():
    with pytest.raises(StrategyError):
        evaluate("not-a-node", {})
    with pytest.raises(StrategyError):
        evaluate({"type": "asset"}, {})                  # no ticker
    with pytest.raises(StrategyError):
        evaluate({"type": "weight_equal", "children": []}, {})
    with pytest.raises(StrategyError):
        evaluate({"type": "filter", "children": [{"type": "asset", "ticker": "A"}]}, {})


def test_normalize_empty():
    assert normalize({}) == {}
    assert normalize({"A": 0.0}) == {}


def test_rebalance_due_cadences():
    from app.services.symphony import _rebalance_due
    d1 = pd.Timestamp("2024-01-01")
    assert _rebalance_due(d1, None, "weekly") is True          # first time
    d2 = pd.Timestamp("2024-02-01")
    assert _rebalance_due(d2, d1, "monthly") is True
    assert _rebalance_due(pd.Timestamp("2024-01-02"), d1, "monthly") is False
    assert _rebalance_due(pd.Timestamp("2024-01-02"), d1, "daily") is True
    assert _rebalance_due(pd.Timestamp("2024-01-15"), d1, "weekly") is True
    assert _rebalance_due(pd.Timestamp("2024-01-02"), d1, "whatever") is True


def test_metrics_single_value():
    from app.services.symphony import _metrics
    m = _metrics([100.0])
    assert m["sharpe"] == 0.0 and m["max_drawdown_pct"] == 0.0


def test_backtest_too_short_raises():
    idx = pd.date_range("2024-01-01", periods=1, freq="B")
    closes = pd.DataFrame({"SPY": pd.Series([100.0], index=idx)})
    with pytest.raises(StrategyError):
        run_backtest({"type": "asset", "ticker": "SPY"}, closes,
                     idx[0].date(), idx[-1].date())


def test_examples_are_valid_trees():
    for ex in example_strategies():
        assert "tree" in ex and "name" in ex
        assert collect_tickers(ex["tree"])  # references at least one ticker


def test_cum_return_window_clamp_and_price_default():
    from app.services.symphony import _eval_indicator
    short = {"X": _series([100.0, 110.0])}
    # window larger than series → clamps; still returns a float
    assert isinstance(_eval_indicator({"fn": "cumulative_return", "ticker": "X", "window": 50}, short), float)
    # single-point series → cum_return 0.0
    one = {"X": _series([100.0])}
    assert _eval_indicator({"fn": "cumulative_return", "ticker": "X", "window": 5}, one) == 0.0


def test_filter_with_missing_child_data_still_picks():
    # B has no data → scored -inf → A is chosen as top-1
    data = {"A": _series([100, 110, 120])}
    tree = {"type": "filter", "select": "top", "n": 1,
            "by": {"fn": "cumulative_return", "window": 2},
            "children": [{"type": "asset", "ticker": "A"}, {"type": "asset", "ticker": "B"}]}
    assert evaluate(tree, data) == {"A": 1.0}


def test_collect_tickers_includes_condition_and_filter_by():
    tree = {"type": "if",
            "condition": {"lhs": {"fn": "rsi", "ticker": "QQQ", "window": 5},
                          "op": ">", "rhs": {"fn": "sma", "ticker": "IWM", "window": 5}},
            "then": {"type": "asset", "ticker": "AAA"},
            "else": {"type": "asset", "ticker": "BBB"}}
    assert collect_tickers(tree) == {"QQQ", "IWM", "AAA", "BBB"}


def test_backtest_keeps_weights_when_eval_fails():
    # A condition references ZZZ (absent from the price frame) → every rebalance
    # raises StrategyError (caught), weights stay empty, equity stays flat.
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    closes = pd.DataFrame({"SPY": pd.Series([100.0 + i for i in range(30)], index=idx)})
    tree = {"type": "if",
            "condition": {"lhs": {"fn": "rsi", "ticker": "ZZZ", "window": 5},
                          "op": ">", "rhs": 50},
            "then": {"type": "asset", "ticker": "SPY"},
            "else": {"type": "asset", "ticker": "SPY"}}
    res = run_backtest(tree, closes, idx[0].date(), idx[-1].date(),
                       cadence="daily", starting_capital=5000.0)
    assert res["final_weights"] == {}
    assert res["equity_curve"][-1]["value"] == 5000.0   # never deployed → flat


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
