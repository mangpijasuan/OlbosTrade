"""Tests for the Scenario / Stress engine."""

from __future__ import annotations

import pytest

from app.services.scenario_engine import (
    DEFAULT_SCENARIOS, Shock, apply_shock, position_value, run_all, run_scenario,
)


def _long_call(qty=1):
    return {"symbol": "SPY", "kind": "option", "option_type": "call",
            "spot": 100.0, "strike": 100.0, "dte_days": 30, "iv": 0.20,
            "r": 0.04, "quantity": qty, "multiplier": 100}


def _short_put(qty=1):
    return {"symbol": "SPY", "kind": "option", "option_type": "put",
            "spot": 100.0, "strike": 95.0, "dte_days": 30, "iv": 0.20,
            "r": 0.04, "quantity": -qty, "multiplier": 100}


def _equity(qty=100):
    return {"symbol": "AAPL", "kind": "equity", "spot": 50.0,
            "quantity": qty, "multiplier": 1}


# ── position_value ─────────────────────────────────────────────────────────────────
def test_equity_value():
    assert position_value(_equity(100)) == pytest.approx(5000.0)


def test_option_value_positive():
    assert position_value(_long_call()) > 0


def test_value_overrides_apply():
    base = position_value(_long_call())
    up = position_value(_long_call(), spot=110.0)
    assert up > base                        # call worth more when spot rises


def test_expired_option_uses_intrinsic():
    v = position_value(_long_call(), dte_days=0, spot=120.0)
    assert v == pytest.approx((120.0 - 100.0) * 100)   # intrinsic × multiplier


# ── apply_shock ────────────────────────────────────────────────────────────────────
def test_crash_hurts_long_call():
    out = apply_shock(_long_call(), Shock("crash", spot_pct=-0.20, iv_mult=1.5))
    assert out["pnl"] < 0                    # long call loses in a crash
    assert out["symbol"] == "SPY"


def test_crash_helps_short_put_holder_loses():
    # short put loses when spot crashes (put gains value, we're short it)
    out = apply_shock(_short_put(), Shock("crash", spot_pct=-0.20, iv_mult=1.8))
    assert out["pnl"] < 0


def test_vol_spike_helps_long_option():
    out = apply_shock(_long_call(), Shock("vol", iv_add=0.30))
    assert out["pnl"] > 0                    # long vega gains on IV spike


def test_iv_floor_prevents_negative():
    # massive negative iv_add floored at 0.0001 → no crash, finite value
    out = apply_shock(_long_call(), Shock("crush", iv_mult=0.0, iv_add=-5.0))
    assert out["shocked"] >= 0


# ── run_scenario / run_all ─────────────────────────────────────────────────────────
def test_run_scenario_aggregates_and_pct():
    book = [_long_call(2), _equity(100)]
    r = run_scenario(book, Shock("gap_down", spot_pct=-0.10), capital=100000.0)
    assert r["scenario"] == "gap_down"
    assert len(r["positions"]) == 2
    assert r["portfolio_pnl_pct"] is not None


def test_run_scenario_no_capital_pct_none():
    r = run_scenario([_equity(100)], Shock("gap", spot_pct=-0.05))
    assert r["portfolio_pnl_pct"] is None


def test_run_all_sorts_worst_first():
    out = run_all([_long_call(5)], capital=100000.0)
    assert len(out["scenarios"]) == len(DEFAULT_SCENARIOS)
    pnls = [s["portfolio_pnl"] for s in out["scenarios"]]
    assert pnls == sorted(pnls)              # ascending → worst first
    assert out["worst_pnl"] == pnls[0]


def test_run_all_empty_book():
    out = run_all([], capital=100000.0)
    assert out["worst_scenario"] is not None    # scenarios still run (zero pnl)
    assert out["worst_pnl"] == 0.0


def test_run_all_custom_scenarios():
    out = run_all([_long_call()], scenarios=[Shock("only", spot_pct=-0.5)])
    assert len(out["scenarios"]) == 1 and out["worst_scenario"] == "only"


def test_shock_as_dict():
    d = Shock("x", spot_pct=-0.1, iv_mult=2.0).as_dict()
    assert d["name"] == "x" and d["spot_pct"] == -0.1 and d["iv_mult"] == 2.0
