"""Tests for the Portfolio Engine (heat / exposure / concentration)."""

from __future__ import annotations

from types import SimpleNamespace as NS

from app.services.portfolio_engine import (
    compute_portfolio_risk,
    position_risk_dollars,
    sector_for,
)


def test_sector_lookup():
    assert sector_for("AAPL") == "Technology"
    assert sector_for("tlt") == "Bonds"
    assert sector_for("ZZZ") == "Unknown"
    assert sector_for("") == "Unknown"


def test_empty_portfolio():
    r = compute_portfolio_risk([], 10000.0)
    assert r["position_count"] == 0
    assert r["portfolio_heat_pct"] == 0.0
    assert r["heat_status"] == "ok"
    assert r["concentration_flags"] == []


def test_heat_and_status_thresholds():
    cap = 10000.0
    ok = compute_portfolio_risk([{"underlying": "SPY", "risk_dollars": 1000}], cap)
    assert ok["portfolio_heat_pct"] == 10.0 and ok["heat_status"] == "ok"
    elevated = compute_portfolio_risk([{"underlying": "SPY", "risk_dollars": 3500}], cap)
    assert elevated["heat_status"] == "elevated"
    high = compute_portfolio_risk([{"underlying": "SPY", "risk_dollars": 6000}], cap)
    assert high["heat_status"] == "high"


def test_exposure_aggregation_and_sorting():
    positions = [
        {"underlying": "AAPL", "risk_dollars": 500},
        {"underlying": "AAPL", "risk_dollars": 300},
        {"underlying": "TLT", "risk_dollars": 1000},
    ]
    r = compute_portfolio_risk(positions, 10000.0)
    assert r["exposure_by_underlying"]["AAPL"] == 800
    assert r["exposure_by_underlying"]["TLT"] == 1000
    # sorted descending → TLT first
    assert list(r["exposure_by_underlying"].keys())[0] == "TLT"
    assert r["exposure_by_sector"]["Technology"] == 800
    assert r["exposure_by_sector"]["Bonds"] == 1000


def test_concentration_flags():
    cap = 10000.0
    # 30% in one underlying → exceeds 25% single-name limit
    positions = [{"underlying": "NVDA", "risk_dollars": 3000}]
    r = compute_portfolio_risk(positions, cap)
    assert any("underlying_concentration:NVDA" in f for f in r["concentration_flags"])
    # spread across two tech names → sector concentration (45% > 40%)
    positions2 = [{"underlying": "NVDA", "risk_dollars": 2500},
                  {"underlying": "MSFT", "risk_dollars": 2000}]
    r2 = compute_portfolio_risk(positions2, cap)
    assert any("sector_concentration:Technology" in f for f in r2["concentration_flags"])


def test_zero_capital_safe():
    r = compute_portfolio_risk([{"underlying": "SPY", "risk_dollars": 100}], 0.0)
    assert r["portfolio_heat_pct"] == 0.0
    assert r["concentration_flags"] == []   # no division by zero


def test_position_risk_dollars_options_spread():
    # bull put 450/445, credit 1.50, qty 2 → (5-1.5)*100*2 = 700
    t = NS(quantity=2, spread_type="put", credit_received=1.50,
           short_strike=450, long_strike=445, strategy="bull_put_spread")
    assert position_risk_dollars(t) == 700.0


def test_position_risk_dollars_equity():
    # equity: entry 150 × 10 shares = 1500
    t = NS(quantity=10, spread_type="equity_long", credit_received=150.0,
           short_strike=0, long_strike=0, strategy="equity")
    assert position_risk_dollars(t) == 1500.0
