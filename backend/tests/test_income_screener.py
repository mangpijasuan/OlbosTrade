"""Tests for the Income Matrix screener pure helpers."""

from __future__ import annotations

from app.services.income_screener import prob_otm, csp_row, cc_row, _yields


# ── prob_otm ───────────────────────────────────────────────────────────────────
def test_prob_otm_put_far_otm_high():
    # Spot well above a low put strike → very likely to stay OTM (seller keeps it)
    p = prob_otm(spot=100, strike=80, dte=30, iv=0.30, is_put=True)
    assert 0.8 < p <= 1.0


def test_prob_otm_call_far_otm_high():
    p = prob_otm(spot=100, strike=130, dte=30, iv=0.30, is_put=False)
    assert 0.8 < p <= 1.0


def test_prob_otm_atm_near_half():
    p = prob_otm(spot=100, strike=100, dte=30, iv=0.30, is_put=True)
    assert 0.4 < p < 0.6


def test_prob_otm_degenerate_returns_zero():
    assert prob_otm(0, 100, 30, 0.3, is_put=True) == 0.0
    assert prob_otm(100, 100, 0, 0.3, is_put=True) == 0.0
    assert prob_otm(100, 100, 30, 0, is_put=True) == 0.0


# ── yields ─────────────────────────────────────────────────────────────────────
def test_yields_annualize():
    y = _yields(premium=2.0, capital_per_share=100.0, dte=30)
    assert y["return_pct"] == 2.0          # 2/100
    assert y["monthly_return_pct"] == 2.0  # 30d → ~monthly
    assert y["annualized_return_pct"] == round(2.0 * (365 / 30), 2)


def test_yields_zero_capital_safe():
    y = _yields(premium=1.0, capital_per_share=0.0, dte=10)
    assert y["return_pct"] == 0.0


# ── csp_row / cc_row ───────────────────────────────────────────────────────────
def test_csp_row_fields():
    r = csp_row(ticker="aapl", strike=190, expiry="2026-07-03", dte=7,
                spot=200, premium=1.50, iv=0.28)
    assert r["strategy"] == "cash_secured_put" and r["type"] == "PUT"
    assert r["capital_required"] == 19000.0          # 190 × 100
    assert r["breakeven"] == 188.5                   # strike − premium
    assert r["ticker"] == "AAPL" and r["prob_otm"] is not None


def test_cc_row_fields():
    r = cc_row(ticker="NVDA", strike=210, expiry="2026-07-03", dte=7,
               spot=200, premium=2.0, iv=0.40)
    assert r["strategy"] == "covered_call" and r["type"] == "CALL"
    assert r["capital_required"] == 20000.0          # spot × 100
    assert r["return_pct"] == 1.0                    # 2 / 200


def test_rows_handle_missing_spot_iv():
    r = csp_row(ticker="X", strike=50, expiry="e", dte=5,
                spot=None, premium=0.5, iv=None)
    assert r["spot"] is None and r["prob_otm"] is None and r["capital_required"] == 5000.0
