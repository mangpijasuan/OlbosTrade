"""
Feature engineering pipeline for signal scorer training.
Computes all 13 features from raw market data + backtest results.
"""

from dataclasses import dataclass
import numpy as np
import pandas as pd
from typing import Optional


FEATURE_NAMES = [
    "iv_rank", "iv_percentile", "vix_level",
    "spy_rsi_14", "spy_adx_14", "spy_trend_direction",
    "days_to_expiry", "short_strike_delta",
    "spread_width", "credit_to_width_ratio",
    "earnings_days_away", "spy_realized_vol_20d",
    "iv_minus_rv",
]


def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average Directional Index."""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    pos_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    neg_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    atr = tr.ewm(span=period).mean()
    pos_di = 100 * pos_dm.ewm(span=period).mean() / atr
    neg_di = 100 * neg_dm.ewm(span=period).mean() / atr

    dx = (100 * (pos_di - neg_di).abs() / (pos_di + neg_di).replace(0, np.nan))
    return dx.ewm(span=period).mean()


def build_feature_matrix(
    ohlcv: pd.DataFrame,
    iv_history: pd.Series,
    vix_history: pd.Series,
    trades: list[dict],
) -> pd.DataFrame:
    """
    Build the full feature matrix from historical data + trade records.

    Args:
        ohlcv:      OHLCV DataFrame with Date index
        iv_history: Daily IV series for the underlying
        vix_history: Daily VIX closing values
        trades:     List of dicts from backtest output

    Returns:
        DataFrame with FEATURE_NAMES columns + 'label' column (1=profitable, 0=loss)
    """
    close = ohlcv["Close"]
    high = ohlcv["High"]
    low = ohlcv["Low"]

    # Technical indicators
    rsi = _compute_rsi(close)
    sma20 = close.rolling(20).mean()
    adx = compute_adx(high, low, close)
    rv20 = np.log(close / close.shift(1)).rolling(20).std() * np.sqrt(252)

    rows = []
    for trade in trades:
        entry_date = pd.Timestamp(trade["entry_date"])
        if entry_date not in ohlcv.index:
            continue

        idx = ohlcv.index.get_loc(entry_date)
        if idx < 20:
            continue

        lookback_iv = iv_history.iloc[:idx+1]
        iv_r = _iv_rank(lookback_iv)
        iv_p = _iv_percentile(lookback_iv)
        iv_current = float(lookback_iv.iloc[-1]) if len(lookback_iv) > 0 else 0.20
        rv_current = float(rv20.iloc[idx]) if not pd.isna(rv20.iloc[idx]) else 0.20

        row = {
            "iv_rank": iv_r,
            "iv_percentile": iv_p,
            "vix_level": float(vix_history.iloc[idx]) if idx < len(vix_history) else 20.0,
            "spy_rsi_14": float(rsi.iloc[idx]) if not pd.isna(rsi.iloc[idx]) else 50.0,
            "spy_adx_14": float(adx.iloc[idx]) if not pd.isna(adx.iloc[idx]) else 20.0,
            "spy_trend_direction": 1.0 if float(close.iloc[idx]) > float(sma20.iloc[idx]) else -1.0,
            "days_to_expiry": float(trade.get("days_to_expiry", 35)),
            "short_strike_delta": float(trade.get("short_strike_delta", 0.20)),
            "spread_width": float(trade.get("spread_width", 10.0)),
            "credit_to_width_ratio": float(trade.get("credit_to_width_ratio", 0.25)),
            "earnings_days_away": float(trade.get("earnings_days_away", 999)),
            "spy_realized_vol_20d": rv_current,
            "iv_minus_rv": iv_current - rv_current,
            "label": 1 if float(trade.get("pnl", 0)) > 0 else 0,
        }
        rows.append(row)

    return pd.DataFrame(rows)


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _iv_rank(iv_series: pd.Series, lookback: int = 252) -> float:
    window = iv_series.iloc[-lookback:]
    if len(window) < 2:
        return 0.0
    current = float(window.iloc[-1])
    lo, hi = float(window.min()), float(window.max())
    return round(((current - lo) / (hi - lo)) * 100, 2) if hi != lo else 0.0


def _iv_percentile(iv_series: pd.Series, lookback: int = 252) -> float:
    window = iv_series.iloc[-lookback:]
    if len(window) < 2:
        return 0.0
    current = float(window.iloc[-1])
    return round(float((window < current).mean() * 100), 2)
