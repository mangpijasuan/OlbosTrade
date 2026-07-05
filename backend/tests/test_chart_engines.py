"""Tests for Chart Intelligence pure engines: alignment, structure, closed-bar."""

from datetime import datetime, timedelta, timezone

from app.services.chart.timeframe_alignment import (
    align, classify_timeframe, TimeframeState,
)
from app.services.chart.market_structure import analyze_structure
from app.services.chart.closed_bar import (
    SignalStatus, build_signal_record, is_bar_closed,
)


def _zigzag(n=60, start=100.0, drift=1.0, amp=3.0):
    """Trending zigzag so swing highs/lows are detectable (realistic structure)."""
    import math
    bars = []
    for i in range(n):
        base = start + drift * i
        osc = amp * math.sin(i * 0.9)
        p = base + osc
        bars.append({"high": p + 0.6, "low": p - 0.6, "close": p})
    return bars


def _uptrend_bars(n=60):
    return _zigzag(n, start=100.0, drift=1.0)


def _downtrend_bars(n=60):
    return _zigzag(n, start=160.0, drift=-1.0)


# ── Timeframe alignment ──────────────────────────────────────────────────────
def test_classify_uptrend_is_bullish():
    st = classify_timeframe("1h", _uptrend_bars())
    assert st.trend == "bullish"
    assert st.price_vs_ema == "above"


def test_classify_downtrend_is_bearish():
    st = classify_timeframe("1h", _downtrend_bars())
    assert st.trend == "bearish"


def test_classify_insufficient_bars_is_neutral():
    st = classify_timeframe("5m", [{"high": 1, "low": 1, "close": 1}] * 5)
    assert st.trend == "neutral"


def test_alignment_all_bullish_strong():
    tfs = [TimeframeState(tf, "bullish", "above", True, "") for tf in ["15m", "1h", "4h", "1d"]]
    res = align(tfs, "default")
    assert res.dominant == "bullish"
    assert res.bullish_count == 4
    assert "Strong" in res.interpretation


def test_alignment_weights_are_strategy_specific():
    # 1w bullish, everything else neutral. Options-income weights 1w heavily.
    tfs = [
        TimeframeState("5m", "neutral", "mixed", False, ""),
        TimeframeState("1w", "bullish", "above", True, ""),
    ]
    income = align(tfs, "options_income").score
    swing = align(tfs, "short_swing").score
    assert income > swing  # 1w matters more for income strategy


def test_alignment_mixed_is_neutral():
    tfs = [
        TimeframeState("1h", "bullish", "above", True, ""),
        TimeframeState("4h", "bearish", "below", False, ""),
    ]
    res = align(tfs, "default")
    assert res.dominant == "neutral"


# ── Market structure ─────────────────────────────────────────────────────────
def test_structure_detects_uptrend():
    res = analyze_structure(_uptrend_bars())
    assert res.state == "uptrend"
    assert res.support and res.resistance


def test_structure_detects_downtrend():
    res = analyze_structure(_downtrend_bars())
    assert res.state == "downtrend"


def test_structure_insufficient_bars():
    res = analyze_structure([{"high": 1, "low": 1, "close": 1}] * 5)
    assert res.state == "undetermined"


def test_structure_makes_no_smart_money_claim():
    res = analyze_structure(_uptrend_bars())
    assert "institutional" in res.note  # explicitly disclaims it


# ── Closed-bar lifecycle ─────────────────────────────────────────────────────
def _rec(close_ts, now):
    return build_signal_record(
        symbol="QQQ", timeframe="1h",
        candle_open_ts=close_ts - timedelta(hours=1), candle_close_ts=close_ts,
        close_price=500.0, indicator_values={"rsi": 55},
        structure_state="uptrend", trend_state="bullish", volume_state="above",
        strategy_version="v1", data_source="yfinance", data_freshness_s=30.0, now=now,
    )


def test_closed_bar_is_confirmed():
    now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
    rec = _rec(now - timedelta(minutes=1), now)  # candle already closed
    assert rec.status == SignalStatus.CONFIRMED
    assert rec.confirmation_ts is not None
    assert rec.price_at_confirmation == 500.0


def test_intrabar_is_preliminary():
    now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
    rec = _rec(now + timedelta(minutes=30), now)  # candle still forming
    assert rec.status == SignalStatus.PRELIMINARY
    assert rec.confirmation_ts is None
    assert rec.price_at_confirmation is None


def test_signal_id_is_deterministic_idempotent():
    now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
    close_ts = now - timedelta(minutes=1)
    assert _rec(close_ts, now).signal_id == _rec(close_ts, now).signal_id


def test_is_bar_closed():
    now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
    assert is_bar_closed(now - timedelta(seconds=1), now) is True
    assert is_bar_closed(now + timedelta(seconds=1), now) is False
