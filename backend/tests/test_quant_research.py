"""
Regression coverage for three BacktestEngine bugs found in code review
(Copilot PR #41, Quant Research & Strategy Lab):

1. direction="BOTH" never actually shorted — hardcoded to LONG whenever
   direction wasn't explicitly "SHORT".
2. max_drawdown_pct measured drawdown from starting_capital (a constant
   that never reflects an open position's unrealized P&L) instead of the
   rolling equity peak — so the kill-switch could never fire while a
   position was open, no matter how far it was underwater.
3. daily_loss was initialized once and never reset per calendar day, so
   it was actually a whole-backtest cumulative-loss counter mislabeled as
   "daily" — once tripped, it permanently blocked all further entries.

All three tests build a small synthetic OHLCV series directly (no yfinance,
no DB) and patch BacktestEngine._fetch_ohlcv, matching how quant_research.py
is otherwise fully DB/broker-free and safe to unit test in isolation.
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd

from app.services.quant_research import BacktestEngine, StrategyBuilder


def _ohlcv(closes: list[float], *, start="2024-01-02", spread: float = 0.5, volume: int = 1_000_000) -> pd.DataFrame:
    """Build a minimal daily OHLCV frame from a list of closing prices."""
    idx = pd.bdate_range(start=start, periods=len(closes))
    close = pd.Series(closes, index=idx, dtype=float)
    high = close + spread
    low = close - spread
    open_ = close.shift(1).fillna(close.iloc[0])
    return pd.DataFrame({
        "Open": open_, "High": high, "Low": low, "Close": close,
        "Volume": float(volume),
    }, index=idx)


def _run(df: pd.DataFrame, **cfg_kwargs):
    cfg_kwargs.setdefault("name", "test")
    cfg = StrategyBuilder.build(cfg_kwargs)
    engine = BacktestEngine()
    with patch.object(BacktestEngine, "_fetch_ohlcv", staticmethod(lambda *a, **k: df)):
        return engine.run(cfg, "TEST", "2024-01-01", "2024-12-31", starting_capital=100_000.0)


def test_direction_both_takes_both_long_and_short_trades():
    """A sine-wave price crosses its own SMA_20 repeatedly in both
    directions. With a single 'CLOSE crosses_above SMA_20' entry condition
    and direction=BOTH, the old code only ever opened LONG — the mirrored
    (crosses_below) short trigger this fix adds must actually produce
    SHORT trades too."""
    n = 160
    t = np.arange(n)
    closes = list(100 + 15 * np.sin(t / 8.0))
    df = _ohlcv(closes)

    result = _run(
        df,
        direction="BOTH",
        entry=[{"indicator": "CLOSE", "period": 0, "operator": "crosses_above",
                "compare_to": "SMA", "compare_period": 20}],
        stop_atr_mult=20.0, target_atr_mult=20.0,
        max_concurrent_positions=1,
        position_size_pct=5.0,
    )

    directions = {t["direction"] for t in result.trades}
    assert "LONG" in directions
    assert "SHORT" in directions, (
        "direction=BOTH must take SHORT trades too, not just mirror-fail "
        "into LONG-only — this is the exact bug being regression-tested"
    )


def test_max_drawdown_triggers_on_peak_relative_not_start_relative():
    """One position opens and is held (stop/target set far away, exit
    condition never fires). Price rises 50% (new equity peak, well above
    starting capital) then falls ~17% from that peak while remaining well
    above the ORIGINAL starting price the whole time.

    Old code: dd_pct = 100 * (1 - equity / starting_capital) — and
    `equity` (realized-only) never changes while a position stays open, so
    dd_pct is permanently 0 and MAX_DRAWDOWN can never fire regardless of
    how far the open position is underwater from its own peak.

    Fixed code must close the position with exit_reason=MAX_DRAWDOWN well
    before the last bar, once the peak-relative drawdown exceeds 15%."""
    n = 80
    warmup = [100.0] * 20                                    # ATR/SMA warmup
    up     = list(100 + (np.arange(30) / 29.0) * 50)          # 100 -> 150
    down   = list(150 - (np.arange(30) / 29.0) * 30)          # 150 -> 120 (-20% from peak)
    closes = warmup + up + down
    assert len(closes) == n
    df = _ohlcv(closes)

    result = _run(
        df,
        direction="LONG",
        entry=[{"indicator": "CLOSE", "period": 0, "operator": ">",
                "compare_to": "VALUE", "value": 0}],  # always true -> opens ASAP
        exit=[{"indicator": "RSI", "period": 14, "operator": "<",
               "compare_to": "VALUE", "value": -999}],  # never true -> no SIGNAL exit
        stop_atr_mult=100.0, target_atr_mult=100.0,       # never hit
        max_drawdown_pct=15.0,
        max_concurrent_positions=1,
        position_size_pct=90.0,
    )

    dd_trades = [t for t in result.trades if t["exit_reason"] == "MAX_DRAWDOWN"]
    assert dd_trades, "peak-relative drawdown must trigger MAX_DRAWDOWN while a position is still open"
    # Must close mid-backtest (peak-relative), not just at the final bar
    # (which would indicate the check never actually fired).
    assert dd_trades[0]["exit_date"] != str(df.index[-1].date())


def test_daily_loss_limit_resets_each_day_not_cumulative():
    """A ~0.4%-per-trade loss, one round-trip trade per day (entry and
    exit layers both empty = always true, so a position opens and closes
    every bar). max_daily_loss_pct=1.0 means any SINGLE day's loss (0.4%)
    must never block entries — but cumulative loss crosses 1% by day 3.

    Old code: daily_loss accumulates forever, never resets -> permanently
    blocks all entries after ~day 3, so only a couple of trades occur
    across the whole series.
    Fixed code: daily_loss resets every calendar day -> trading continues
    every day for the whole series."""
    n = 60
    # Steady ~0.4%/day decline -> each 1-day LONG round-trip is a small loss.
    closes = [100.0 * (0.996 ** i) for i in range(n)]
    df = _ohlcv(closes)

    result = _run(
        df,
        direction="LONG",
        entry=[{"indicator": "CLOSE", "period": 0, "operator": ">",
                "compare_to": "VALUE", "value": 0}],  # always true
        exit=[],   # always true -> closes (and reopens) every bar
        stop_atr_mult=100.0, target_atr_mult=100.0,
        max_daily_loss_pct=1.0,
        max_concurrent_positions=1,
        position_size_pct=90.0,
    )

    # Old buggy behaviour would strand this at ~2-3 trades total once
    # cumulative loss crossed 1%; the fix should keep trading most days.
    assert len(result.trades) > 15, (
        f"only {len(result.trades)} trades ran — daily_loss looks like it's "
        f"still a permanent cumulative block instead of resetting per day"
    )
