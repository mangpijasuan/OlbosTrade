"""Tests for the Unusual Options Activity pure helpers."""

from __future__ import annotations

from app.services.unusual_activity import is_unusual, flow_row, summarize


# ── is_unusual ─────────────────────────────────────────────────────────────────
def test_below_min_volume_not_unusual():
    assert is_unusual(50, 10, min_volume=200) is False


def test_volume_far_above_oi_is_unusual():
    assert is_unusual(1000, 100, min_volume=200, ratio=2.0) is True


def test_volume_not_enough_over_oi_not_unusual():
    assert is_unusual(300, 1000, min_volume=200, ratio=2.0) is False


def test_zero_oi_with_volume_is_unusual():
    assert is_unusual(500, 0, min_volume=200) is True


def test_none_values_safe():
    assert is_unusual(None, None, min_volume=200) is False


# ── flow_row ───────────────────────────────────────────────────────────────────
def test_flow_row_call_premium_and_sentiment():
    r = flow_row(ticker="spy", opt_type="call", strike=750, expiry="2026-06-03",
                 spot=754.1, volume=100, open_interest=20, last_price=1.14,
                 iv=0.31, dte=0)
    assert r["ticker"] == "SPY" and r["type"] == "CALL"
    assert r["sentiment"] == "bullish"
    assert r["premium"] == round(100 * 1.14 * 100, 2)   # vol × last × 100
    assert r["vol_oi_ratio"] == 5.0


def test_flow_row_put_and_new_oi():
    r = flow_row(ticker="QQQ", opt_type="put", strike=500, expiry="2026-06-12",
                 spot=None, volume=10, open_interest=0, last_price=2.0,
                 iv=None, dte=None)
    assert r["type"] == "PUT" and r["sentiment"] == "bearish"
    assert r["vol_oi_ratio"] is None and r["spot"] is None and r["iv"] is None


# ── summarize ──────────────────────────────────────────────────────────────────
def test_summarize_ratios():
    rows = [
        flow_row(ticker="A", opt_type="call", strike=1, expiry="x", spot=1,
                 volume=100, open_interest=1, last_price=1.0, iv=None, dte=1),  # $10k
        flow_row(ticker="B", opt_type="put", strike=1, expiry="x", spot=1,
                 volume=100, open_interest=1, last_price=1.0, iv=None, dte=1),  # $10k
    ]
    s = summarize(rows)
    assert s["count"] == 2 and s["bullish_ratio"] == 0.5
    assert s["net_premium"] == 0.0


def test_summarize_empty_is_neutral():
    s = summarize([])
    assert s["count"] == 0 and s["bullish_ratio"] == 0.5
