"""
Bar fetch for Chart Intelligence — closed OHLCV per timeframe via yfinance.

Returns CLOSED bars only (the last, possibly-forming bar is dropped) so every
downstream signal obeys the closed-bar rule. Free, delayed data; fail-soft.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.utils.logger import get_logger

logger = get_logger(__name__)

# timeframe -> (yfinance interval, period). 4h is resampled from 1h.
_TF_MAP: dict[str, tuple[str, str]] = {
    "5m": ("5m", "5d"),
    "15m": ("15m", "1mo"),
    "1h": ("60m", "3mo"),
    "4h": ("60m", "6mo"),   # resampled to 4h below
    "1d": ("1d", "1y"),
    "1w": ("1wk", "5y"),
}


def fetch_bars(symbol: str, timeframe: str, drop_forming: bool = True) -> list[dict]:
    """Fetch closed OHLCV bars for a timeframe. Empty list on any failure."""
    interval, period = _TF_MAP.get(timeframe, ("1d", "1y"))
    try:
        import pandas as pd  # type: ignore
        import yfinance as yf  # type: ignore

        hist = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
        if hist is None or hist.empty:
            return []
        if timeframe == "4h":
            hist = hist.resample("4h").agg({
                "Open": "first", "High": "max", "Low": "min",
                "Close": "last", "Volume": "sum",
            }).dropna()

        bars = []
        for ts, row in hist.iterrows():
            bars.append({
                "timestamp": ts.to_pydatetime().isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row.get("Volume", 0) or 0),
            })
        if drop_forming and bars:
            bars = bars[:-1]  # last bar may still be forming
        return bars
    except Exception as exc:
        logger.warning("chart bars fetch failed for %s %s: %s", symbol, timeframe, exc)
        return []


def freshness_seconds(bars: list[dict]) -> float:
    if not bars:
        return 0.0
    try:
        last = datetime.fromisoformat(bars[-1]["timestamp"])
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - last).total_seconds())
    except Exception:
        return 0.0
