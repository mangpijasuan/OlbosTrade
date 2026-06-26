"""Tests for the Dynamic Capital Allocation Engine."""

from __future__ import annotations

import pytest

from app.services.allocation_engine import (
    BLENDED, EQUAL, KELLY, METHODS, PERFORMANCE, RISK_PARITY, VOL_TARGET,
    AllocationConstraints, StrategyAlloc, allocate, drift,
    _apply_caps, _normalize, _portfolio_vol,
)


def _s(name, **kw):
    return StrategyAlloc(strategy=name, **kw)


# ── helpers ──────────────────────────────────────────────────────────────────────
def test_normalize_sums_to_one_and_zero_guard():
    assert sum(_normalize({"a": 2, "b": 2}).values()) == pytest.approx(1.0)
    assert _normalize({"a": 0, "b": 0}) == {"a": 0.0, "b": 0.0}


def test_apply_caps_redistributes():
    capped = _apply_caps({"a": 0.8, "b": 0.1, "c": 0.1}, 0.5)
    assert capped["a"] == pytest.approx(0.5)
    assert sum(capped.values()) == pytest.approx(1.0)        # excess redistributed
    assert capped["b"] > 0.1 and capped["c"] > 0.1


def test_apply_caps_all_at_cap_breaks():
    # three names, cap 0.33 → can't fit 1.0; loop terminates without infinite spin
    out = _apply_caps({"a": 0.5, "b": 0.5}, 0.33)
    assert all(v <= 0.34 for v in out.values())


def test_apply_caps_noop_when_cap_high():
    w = {"a": 0.6, "b": 0.4}
    assert _apply_caps(w, 1.0) == w


def test_portfolio_vol_zero_corr():
    items = [_s("a", volatility=0.2), _s("b", volatility=0.1)]
    pv = _portfolio_vol({"a": 0.5, "b": 0.5}, items)
    assert pv == pytest.approx(((0.1) ** 2 + (0.05) ** 2) ** 0.5)


# ── eligibility ───────────────────────────────────────────────────────────────────
def test_no_eligible_returns_all_cash():
    r = allocate([_s("a", tilt=0.0)], method=EQUAL)
    assert r.weights == {} and r.cash_weight == 1.0
    assert r.diagnostics["eligible"] == 0


def test_unknown_method_raises():
    with pytest.raises(ValueError):
        allocate([_s("a")], method="bogus")


def test_all_methods_run():
    items = [_s("a", score=80, volatility=0.2, expectancy=50, kelly_fraction=0.3),
             _s("b", score=60, volatility=0.1, expectancy=30, kelly_fraction=0.2)]
    for m in METHODS:
        r = allocate(items, method=m)
        assert abs(sum(r.weights.values()) + r.cash_weight - 1.0) < 1e-6


# ── method behaviour ──────────────────────────────────────────────────────────────
def test_equal_weight_splits_evenly():
    r = allocate([_s("a"), _s("b")], method=EQUAL,
                 constraints=AllocationConstraints(max_per_strategy=1.0))
    assert r.weights["a"] == pytest.approx(0.5)
    assert r.weights["b"] == pytest.approx(0.5)


def test_risk_parity_favors_low_vol():
    r = allocate([_s("low", volatility=0.05), _s("high", volatility=0.20)],
                 method=RISK_PARITY, constraints=AllocationConstraints(max_per_strategy=1.0))
    assert r.weights["low"] > r.weights["high"]


def test_risk_parity_all_zero_vol_falls_back_to_equal():
    r = allocate([_s("a", volatility=0.0), _s("b", volatility=0.0)],
                 method=RISK_PARITY, constraints=AllocationConstraints(max_per_strategy=1.0))
    assert r.weights["a"] == pytest.approx(r.weights["b"])


def test_performance_zeroes_negative_expectancy():
    r = allocate([_s("win", score=70, expectancy=40), _s("lose", score=70, expectancy=-5)],
                 method=PERFORMANCE, constraints=AllocationConstraints(max_per_strategy=1.0))
    assert r.weights["win"] > 0 and r.weights["lose"] == pytest.approx(0.0)


def test_performance_all_nonpositive_falls_back_equal():
    r = allocate([_s("a", expectancy=-1), _s("b", expectancy=0)],
                 method=PERFORMANCE, constraints=AllocationConstraints(max_per_strategy=1.0))
    assert r.weights["a"] == pytest.approx(r.weights["b"])


def test_kelly_weights_and_fallback():
    r = allocate([_s("a", kelly_fraction=0.4), _s("b", kelly_fraction=0.1)],
                 method=KELLY, constraints=AllocationConstraints(max_per_strategy=1.0))
    assert r.weights["a"] > r.weights["b"]
    eq = allocate([_s("a", kelly_fraction=0.0), _s("b", kelly_fraction=0.0)],
                  method=KELLY, constraints=AllocationConstraints(max_per_strategy=1.0))
    assert eq.weights["a"] == pytest.approx(eq.weights["b"])


def test_blended_mixes_views():
    r = allocate([_s("a", score=90, volatility=0.05, expectancy=60),
                  _s("b", score=40, volatility=0.20, expectancy=10)],
                 method=BLENDED, constraints=AllocationConstraints(max_per_strategy=1.0))
    assert r.weights["a"] > r.weights["b"]


# ── tilt + constraints ─────────────────────────────────────────────────────────────
def test_meta_tilt_scales_weights():
    full = allocate([_s("a", score=80, expectancy=50), _s("b", score=80, expectancy=50)],
                    method=PERFORMANCE, constraints=AllocationConstraints(max_per_strategy=1.0))
    tilted = allocate([_s("a", score=80, expectancy=50, tilt=1.0),
                       _s("b", score=80, expectancy=50, tilt=0.5)],
                      method=PERFORMANCE, constraints=AllocationConstraints(max_per_strategy=1.0))
    assert tilted.weights["a"] > tilted.weights["b"]
    assert full.weights["a"] == pytest.approx(full.weights["b"])


def test_per_strategy_cap_enforced():
    r = allocate([_s("a", score=99, expectancy=100), _s("b", score=1, expectancy=1),
                  _s("c", score=1, expectancy=1)],
                 method=PERFORMANCE, constraints=AllocationConstraints(max_per_strategy=0.4))
    assert r.weights["a"] <= 0.4 + 1e-9


def test_max_total_deployment_leaves_cash():
    r = allocate([_s("a", expectancy=50), _s("b", expectancy=50)], method=EQUAL,
                 constraints=AllocationConstraints(max_per_strategy=1.0, max_total_deployment=0.6))
    assert sum(r.weights.values()) == pytest.approx(0.6)
    assert r.cash_weight == pytest.approx(0.4)


def test_vol_target_scales_down_hot_book():
    # high-vol strategies → portfolio vol exceeds target → deployment scaled down
    r = allocate([_s("a", volatility=0.5), _s("b", volatility=0.5)], method=VOL_TARGET,
                 constraints=AllocationConstraints(max_per_strategy=1.0, target_volatility=0.10))
    assert sum(r.weights.values()) < 1.0
    assert r.cash_weight > 0


def test_vol_target_zero_vol_skips_scaling():
    # zero portfolio vol → no vol-based scaling, full deployment
    r = allocate([_s("a", volatility=0.0), _s("b", volatility=0.0)], method=VOL_TARGET,
                 constraints=AllocationConstraints(max_per_strategy=1.0, target_volatility=0.10))
    assert sum(r.weights.values()) == pytest.approx(1.0)


def test_tilt_collapse_fallback():
    # raw weights zero after tilt (performance all zero expectancy) but tilt>0 →
    # falls back to tilt-proportional weights, never crashes
    r = allocate([_s("a", expectancy=-1, tilt=1.0), _s("b", expectancy=-1, tilt=0.5)],
                 method=PERFORMANCE, constraints=AllocationConstraints(max_per_strategy=1.0))
    assert sum(r.weights.values()) > 0


def test_as_dict_rounds():
    r = allocate([_s("a", expectancy=50)], method=EQUAL)
    d = r.as_dict()
    assert "weights" in d and "cash_weight" in d and d["method"] == EQUAL


# ── drift ──────────────────────────────────────────────────────────────────────────
def test_drift_union_of_names():
    d = drift({"a": 0.5, "b": 0.5}, {"a": 0.3, "c": 0.4})
    assert d["a"] == pytest.approx(-0.2)
    assert d["b"] == pytest.approx(-0.5)
    assert d["c"] == pytest.approx(0.4)
