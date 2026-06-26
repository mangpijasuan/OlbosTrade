"""
Parametric portfolio risk — Value-at-Risk and Expected Shortfall.

A delta-vega-normal approximation: estimate the 1-day P&L standard deviation from
the book's net Greeks and assumed volatilities, then read VaR / ES off the normal
distribution. This is the *parametric* version — it needs no trade history and is
useful immediately. (Historical / Monte-Carlo VaR is deferred until enough live
P&L accrues.)

Pure functions; no I/O.
"""

from __future__ import annotations

import math

from scipy.stats import norm


def daily_pnl_sigma(net_delta: float, spot: float, underlying_annual_vol: float,
                    net_vega: float = 0.0, iv_daily_move_pts: float = 1.0) -> float:
    """
    1-day P&L standard deviation in dollars.

      • delta term: net_delta × spot × daily_underlying_vol
      • vega term:  net_vega × expected daily IV move (in vol points)
    The two are combined assuming independence (sqrt of summed squares).
    """
    daily_vol = max(0.0, underlying_annual_vol) / math.sqrt(252)
    delta_pnl = abs(net_delta) * max(0.0, spot) * daily_vol
    vega_pnl = abs(net_vega) * max(0.0, iv_daily_move_pts)
    return math.sqrt(delta_pnl ** 2 + vega_pnl ** 2)


def value_at_risk(sigma: float, confidence: float = 0.95,
                  horizon_days: int = 1) -> tuple[float, float]:
    """
    (VaR, Expected Shortfall) in dollars for a normal P&L with std `sigma`
    (1-day), scaled to the horizon. Both returned as positive loss magnitudes.
    """
    if sigma <= 0:
        return 0.0, 0.0
    confidence = min(max(confidence, 0.5), 0.999)
    scaled = sigma * math.sqrt(max(1, horizon_days))
    z = norm.ppf(confidence)
    var = z * scaled
    # ES for a normal: sigma * pdf(z) / (1 - confidence)
    es = scaled * norm.pdf(z) / (1.0 - confidence)
    return var, es


def portfolio_var(net_delta: float, net_vega: float, spot: float,
                  underlying_annual_vol: float, portfolio_value: float,
                  confidence: float = 0.95, horizon_days: int = 1,
                  iv_daily_move_pts: float = 1.0) -> dict:
    """Full parametric VaR/ES report for the book."""
    sigma = daily_pnl_sigma(net_delta, spot, underlying_annual_vol,
                            net_vega, iv_daily_move_pts)
    var, es = value_at_risk(sigma, confidence, horizon_days)
    return {
        "sigma_1d": round(sigma, 2),
        "confidence": confidence,
        "horizon_days": horizon_days,
        "var": round(var, 2),
        "expected_shortfall": round(es, 2),
        "var_pct": round(var / portfolio_value * 100, 2) if portfolio_value > 0 else None,
        "es_pct": round(es / portfolio_value * 100, 2) if portfolio_value > 0 else None,
    }


def incremental_var(base: dict, combined: dict) -> dict:
    """Marginal VaR a prospective trade adds: combined-book VaR minus current."""
    d_var = round(combined.get("var", 0.0) - base.get("var", 0.0), 2)
    d_es = round(combined.get("expected_shortfall", 0.0)
                 - base.get("expected_shortfall", 0.0), 2)
    return {"incremental_var": d_var, "incremental_es": d_es}


def breaches_var_limit(var_report: dict, max_var_pct: float) -> bool:
    """True when the book's VaR exceeds the allowed % of capital (None pct ⇒ no breach)."""
    pct = var_report.get("var_pct")
    return pct is not None and pct > max_var_pct
