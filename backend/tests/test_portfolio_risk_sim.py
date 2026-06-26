"""Tests for parametric portfolio VaR / Expected Shortfall."""

from __future__ import annotations

import pytest

from app.services.portfolio_risk_sim import (
    breaches_var_limit, daily_pnl_sigma, incremental_var, portfolio_var,
    value_at_risk,
)


# ── daily_pnl_sigma ────────────────────────────────────────────────────────────────
def test_sigma_zero_when_no_exposure():
    assert daily_pnl_sigma(0.0, 100.0, 0.0) == 0.0


def test_sigma_scales_with_delta_and_vol():
    a = daily_pnl_sigma(10.0, 100.0, 0.20)
    b = daily_pnl_sigma(20.0, 100.0, 0.20)
    assert b > a > 0


def test_sigma_combines_delta_and_vega():
    delta_only = daily_pnl_sigma(10.0, 100.0, 0.20, net_vega=0.0)
    with_vega = daily_pnl_sigma(10.0, 100.0, 0.20, net_vega=50.0, iv_daily_move_pts=1.0)
    assert with_vega > delta_only


# ── value_at_risk ──────────────────────────────────────────────────────────────────
def test_var_zero_sigma():
    assert value_at_risk(0.0) == (0.0, 0.0)


def test_var_es_ordering_and_confidence():
    var95, es95 = value_at_risk(1000.0, 0.95)
    var99, es99 = value_at_risk(1000.0, 0.99)
    assert es95 > var95 > 0                  # ES always exceeds VaR
    assert var99 > var95                      # higher confidence → larger VaR


def test_var_scales_with_horizon():
    v1, _ = value_at_risk(1000.0, 0.95, horizon_days=1)
    v4, _ = value_at_risk(1000.0, 0.95, horizon_days=4)
    assert v4 == pytest.approx(v1 * 2, rel=1e-6)   # sqrt(4) = 2


def test_var_confidence_clamped():
    # absurd confidence clamped into (0.5, 0.999) — no error, finite output
    v, e = value_at_risk(1000.0, 0.9999999)
    assert v > 0 and e > 0


# ── portfolio_var ──────────────────────────────────────────────────────────────────
def test_portfolio_var_report_shape():
    r = portfolio_var(net_delta=50.0, net_vega=100.0, spot=450.0,
                      underlying_annual_vol=0.18, portfolio_value=100000.0)
    for k in ("sigma_1d", "var", "expected_shortfall", "var_pct", "es_pct"):
        assert k in r
    assert r["var"] > 0 and r["var_pct"] > 0


def test_portfolio_var_zero_value_pct_none():
    r = portfolio_var(10.0, 0.0, 450.0, 0.18, portfolio_value=0.0)
    assert r["var_pct"] is None and r["es_pct"] is None


# ── incremental_var ────────────────────────────────────────────────────────────────
def test_incremental_var():
    base = {"var": 1000.0, "expected_shortfall": 1300.0}
    combined = {"var": 1500.0, "expected_shortfall": 1900.0}
    out = incremental_var(base, combined)
    assert out["incremental_var"] == 500.0
    assert out["incremental_es"] == 600.0


# ── breaches_var_limit ─────────────────────────────────────────────────────────────
def test_breaches_var_limit():
    assert breaches_var_limit({"var_pct": 12.0}, 10.0) is True
    assert breaches_var_limit({"var_pct": 5.0}, 10.0) is False
    assert breaches_var_limit({"var_pct": None}, 10.0) is False
