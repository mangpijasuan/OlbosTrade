"""Tests for the Flow Recommender (unusual activity + signals → setups)."""

from __future__ import annotations

from app.services.flow_recommender import (
    safe_vol_oi, conviction_score, pick_strategy, cluster_flow,
    build_recommendation, recommend, _bias_from_signals,
)


def _row(ticker="SPY", typ="CALL", strike=750.0, dte=2, spot=754.0,
         volume=1000, oi=100, premium=6_000_000.0, side=None):
    r = {"ticker": ticker, "type": typ, "strike": strike, "dte": dte,
         "spot": spot, "volume": volume, "open_interest": oi, "premium": premium}
    if side is not None:
        r["side"] = side
    return r


# ── safe_vol_oi (division-by-zero / OI==0 handling) ─────────────────────────────
def test_safe_vol_oi_normal():
    assert safe_vol_oi(1000, 100) == (10.0, False)


def test_safe_vol_oi_zero_oi_with_volume_is_new_position():
    ratio, new = safe_vol_oi(500, 0)
    assert ratio is None and new is True


def test_safe_vol_oi_zero_everything():
    assert safe_vol_oi(0, 0) == (0.0, False)


def test_safe_vol_oi_none_inputs():
    assert safe_vol_oi(None, None) == (0.0, False)


# ── conviction_score ───────────────────────────────────────────────────────────
def test_conviction_caps_at_10():
    s = conviction_score(vol_oi=50, new_position=False, premium=10e6,
                         premium_floor=5e6, confluent=True, aggressive=True)
    assert s == 10


def test_conviction_new_position_gets_full_ratio_points():
    s = conviction_score(vol_oi=None, new_position=True, premium=0,
                         premium_floor=5e6, confluent=False, aggressive=False)
    assert s == 4   # 4 ratio pts only


def test_conviction_floor_is_one():
    s = conviction_score(vol_oi=0, new_position=False, premium=0,
                         premium_floor=5e6, confluent=False, aggressive=False)
    assert s == 1


# ── pick_strategy ──────────────────────────────────────────────────────────────
def test_strategy_bullish_ask_is_long_call():
    assert pick_strategy("BULLISH", 2, "ASK") == "Long Call"


def test_strategy_bullish_bid_is_credit_spread():
    assert pick_strategy("BULLISH", 2, "BID") == "Bull Put Spread"


def test_strategy_zero_dte_momentum():
    assert "0DTE" in pick_strategy("BEARISH", 0, "ASK")


def test_strategy_bearish_default_no_side():
    assert pick_strategy("BEARISH", 3, None) == "Bear Call Spread"


# ── cluster_flow ───────────────────────────────────────────────────────────────
def test_cluster_aggregates_premium_and_gamma_magnet():
    rows = [
        _row(strike=750, volume=3000, premium=2e6),
        _row(strike=755, volume=500,  premium=4e6),
    ]
    clusters = cluster_flow(rows)
    c = clusters[("SPY", "BULLISH")]
    assert c["total_premium"] == 6e6
    assert c["gamma_magnet"] == 750      # highest volume
    assert c["target_strike"] == 755     # highest premium


def test_cluster_flags_new_position_on_zero_oi():
    c = cluster_flow([_row(oi=0)])[("SPY", "BULLISH")]
    assert c["new_position"] is True


# ── recommend (end-to-end pure) ─────────────────────────────────────────────────
def test_recommend_emits_setup_when_thresholds_met():
    rows = [_row(volume=1000, oi=100, premium=6e6, side="ASK", dte=2)]
    recs = recommend(rows, {"SPY": "BULLISH"}, min_cluster_premium=5e6)
    assert len(recs) == 1
    r = recs[0]
    assert r["ticker"] == "SPY" and r["direction"] == "BULLISH"
    assert r["strategy_type"] == "Long Call"
    assert r["confluence"] == "confirmed"
    assert r["setup_details"]["estimated_gamma_magnet"] == 750.0
    assert 1 <= r["conviction_score"] <= 10


def test_recommend_filters_long_dated_and_thin_premium():
    # DTE too long
    assert recommend([_row(dte=30)], min_cluster_premium=0) == []
    # premium below cluster floor
    assert recommend([_row(premium=1000)], min_cluster_premium=5e6) == []


def test_recommend_divergent_bias_caps_conviction():
    rows = [_row(volume=5000, oi=10, premium=20e6, side="ASK", dte=1)]  # would score high
    recs = recommend(rows, {"SPY": "BEARISH"}, min_cluster_premium=5e6)
    assert recs[0]["confluence"] == "divergent"
    assert recs[0]["conviction_score"] <= 4


def test_recommend_require_confluence_drops_unconfirmed():
    rows = [_row(volume=1000, oi=100, premium=6e6, dte=2)]
    assert recommend(rows, {}, min_cluster_premium=5e6, require_confluence=True) == []


def test_recommend_zero_oi_does_not_crash_and_emits():
    rows = [_row(volume=800, oi=0, premium=6e6, side="ASK", dte=0)]
    recs = recommend(rows, {"SPY": "BULLISH"}, min_cluster_premium=5e6)
    assert recs and recs[0]["flow_summary"]["new_position"] is True


# ── bias mapping ────────────────────────────────────────────────────────────────
def test_bias_from_signals_takes_newest_per_ticker():
    sig = [{"ticker": "SPY", "action": "BUY"},
           {"ticker": "SPY", "action": "SELL"},   # older, ignored
           {"ticker": "QQQ", "action": "SELL"},
           {"ticker": "AMZN", "action": "HOLD"}]
    b = _bias_from_signals(sig)
    assert b == {"SPY": "BULLISH", "QQQ": "BEARISH"}   # HOLD → no bias


# ── extra edge coverage ─────────────────────────────────────────────────────────
def test_passes_filters_rejects_thin_row_premium():
    # min_row_premium gate (per-contract) filters the row out before clustering
    assert recommend([_row(premium=100)], min_row_premium=1000, min_cluster_premium=0) == []


def test_aggressive_mid_side_is_neutral_strategy():
    assert pick_strategy("BULLISH", 2, "MID") == "Bull Put Spread"


def test_cluster_skips_unknown_option_type():
    bad = {**_row(), "type": "XYZ"}
    assert cluster_flow([bad]) == {}


def test_build_recommendation_handles_missing_spot():
    cluster = {
        "ticker": "SPY", "direction": "BULLISH", "total_premium": 6e6,
        "total_volume": 1000, "max_vol_oi": 10.0, "new_position": False,
        "gamma_magnet": 750.0, "target_strike": 755.0, "spot": None,
        "expiry": "2026-06-30", "dte": 2, "side": None, "contracts": 1,
    }
    rec = build_recommendation(cluster, "BULLISH", premium_floor=5e6)
    assert "±" in rec["setup_details"]["entry_zone"]   # no spot → generic band


def test_recommend_min_conviction_filters_all():
    rows = [_row(volume=1000, oi=100, premium=6e6, dte=2)]
    assert recommend(rows, {}, min_cluster_premium=5e6, min_conviction=11) == []
