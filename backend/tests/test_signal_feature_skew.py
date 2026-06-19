"""
Batch 4 (4-B) — serve-time feature parity with training.

ml/features.py caps earnings_days_away at 60 when building the training matrix.
The live SignalFeatures must apply the SAME cap, or the model (which uses this
feature — it's in EXPECTED_POSITIVE_SHAP) sees raw values at inference (e.g. 999
for ETFs) that never occurred in training.
"""

from __future__ import annotations

from app.services.signal_scorer import SignalFeatures


def _features(earnings_days_away: float) -> SignalFeatures:
    return SignalFeatures(
        iv_rank=50.0, iv_percentile=50.0, vix_level=18.0,
        spy_rsi_14=55.0, spy_adx_14=22.0, spy_trend_direction=1.0,
        days_to_expiry=35.0, short_strike_delta=0.20,
        spread_width=10.0, credit_to_width_ratio=0.30,
        earnings_days_away=earnings_days_away,
        spy_realized_vol_20d=0.15, iv_minus_rv=0.03,
    )


def test_earnings_days_away_capped_at_60_for_etf():
    # ETF default 999 must be clamped to 60 (training cap).
    assert _features(999.0).earnings_days_away == 60.0


def test_earnings_days_away_under_cap_unchanged():
    assert _features(7.0).earnings_days_away == 7.0


def test_earnings_days_away_exactly_60_unchanged():
    assert _features(60.0).earnings_days_away == 60.0


def test_to_array_uses_capped_value():
    # Column 11 (0-based 10) is earnings_days_away — must be the capped value.
    arr = _features(999.0).to_array()
    assert arr[0][10] == 60.0
