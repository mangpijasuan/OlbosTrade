"""
Equity signal engine — OLBOS-style rule-based signal generation for stocks/ETFs.
Uses the `ta` library (Technical Analysis Library in Python) for indicator computation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ── Indicator computation ───────────────────────────────────────────────────

def compute_indicators(df: pd.DataFrame) -> dict:
    """
    Compute technical indicators from an OHLCV DataFrame.

    Expected columns: open, high, low, close, volume (all numeric).
    Returns a dict of latest indicator values.
    """
    try:
        import ta as ta_lib  # type: ignore
        from ta.trend import EMAIndicator, MACD, ADXIndicator
        from ta.momentum import RSIIndicator, StochasticOscillator
        from ta.volatility import BollingerBands, AverageTrueRange
        from ta.volume import OnBalanceVolumeIndicator
    except ImportError:
        logger.warning("ta library not installed — returning empty indicators")
        return {}

    if len(df) < 30:
        logger.warning("Insufficient bars for indicator computation: %d", len(df))
        return {}

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    # EMAs
    df["ema20"]  = EMAIndicator(close=close, window=20).ema_indicator()
    df["ema50"]  = EMAIndicator(close=close, window=50).ema_indicator()
    df["ema200"] = EMAIndicator(close=close, window=200).ema_indicator()

    # RSI
    df["rsi"] = RSIIndicator(close=close, window=14).rsi()

    # MACD
    macd_obj = MACD(close=close, window_fast=12, window_slow=26, window_sign=9)
    df["macd"]        = macd_obj.macd()
    df["macd_signal"] = macd_obj.macd_signal()
    df["macd_hist"]   = macd_obj.macd_diff()

    # Bollinger Bands
    bb_obj = BollingerBands(close=close, window=20, window_dev=2)
    df["bb_lower"] = bb_obj.bollinger_lband()
    df["bb_mid"]   = bb_obj.bollinger_mavg()
    df["bb_upper"] = bb_obj.bollinger_hband()
    # pct_b = (close - lower) / (upper - lower)
    bb_width = (bb_obj.bollinger_hband() - bb_obj.bollinger_lband()).replace(0, 1)
    df["bb_pct_b"] = (close - bb_obj.bollinger_lband()) / bb_width

    # ATR
    df["atr"] = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()

    # ADX — trend strength. Previously only available as a single shared
    # market-wide reading (main.py's options scan read it off the regime
    # classifier for every symbol); computed per-symbol here so each stock's
    # own trend strength is available wherever this function's output is used.
    df["adx"] = ADXIndicator(high=high, low=low, close=close, window=14).adx()

    # OBV
    df["obv"] = OnBalanceVolumeIndicator(close=close, volume=volume).on_balance_volume()

    # Stochastic K/D
    stoch_obj = StochasticOscillator(high=high, low=low, close=close, window=14, smooth_window=3)
    df["stoch_k"] = stoch_obj.stoch()
    df["stoch_d"] = stoch_obj.stoch_signal()

    # VWAP approximation (cumulative from first bar — good enough for daily bars)
    df["vwap"] = (close * volume).cumsum() / volume.cumsum()

    # Volume ratio vs 20-bar average
    df["vol_avg20"]    = volume.rolling(20).mean()
    df["volume_ratio"] = volume / df["vol_avg20"].replace(0, 1)

    latest = df.iloc[-1]
    close  = float(latest.get("close", 0))
    ema20  = float(latest.get("ema20",  0) or 0)
    ema50  = float(latest.get("ema50",  0) or 0)
    ema200 = float(latest.get("ema200", 0) or 0)
    vwap   = float(latest.get("vwap",   0) or 0)

    return {
        "close":           close,
        "ema20":           ema20,
        "ema50":           ema50,
        "ema200":          ema200,
        "rsi":             float(latest.get("rsi", 50) or 50),
        "macd":            float(latest.get("macd", 0) or 0),
        "macd_signal":     float(latest.get("macd_signal", 0) or 0),
        "macd_hist":       float(latest.get("macd_hist", 0) or 0),
        "bb_pct_b":        float(latest.get("bb_pct_b", 0.5) or 0.5),
        "atr":             float(latest.get("atr", 1) or 1),
        "adx":             float(latest.get("adx", 20.0) or 20.0),
        "obv":             float(latest.get("obv", 0) or 0),
        "stoch_k":         float(latest.get("stoch_k", 50) or 50),
        "stoch_d":         float(latest.get("stoch_d", 50) or 50),
        "vwap":            vwap,
        "volume_ratio":    float(latest.get("volume_ratio", 1.0) or 1.0),
        "above_ema200":    close > ema200 if ema200 > 0 else False,
        "above_vwap":      close > vwap  if vwap  > 0 else False,
        "ema_aligned_bull": (ema20 > ema50 and close > ema20) if (ema20 and ema50) else False,
        "ema_aligned_bear": (ema20 < ema50 and close < ema20) if (ema20 and ema50) else False,
    }


# ── Signal scoring ──────────────────────────────────────────────────────────

def score_equity_signal(
    ind: dict,
    sentiment_score: float = 0.0,
    orderflow_score: float = 0.0,
) -> tuple[str, float, dict]:
    """
    Score equity indicators and return (action, confidence, reasons).

    action:     "BUY" | "SELL" | "HOLD"
    confidence: 0.0 – 1.0
    reasons:    dict of contributing factors and their point values
    """
    bull_pts = 0.0
    bear_pts = 0.0
    reasons: dict = {}

    rsi        = ind.get("rsi", 50)
    macd       = ind.get("macd", 0)
    macd_sig   = ind.get("macd_signal", 0)
    bb_pct_b   = ind.get("bb_pct_b", 0.5)
    vol_ratio  = ind.get("volume_ratio", 1.0)
    stoch_k    = ind.get("stoch_k", 50)

    # ── Bull scoring ─────────────────────────────────────────────────────
    if rsi < 35:
        bull_pts += 1.5
        reasons["rsi_oversold"] = 1.5

    if macd > macd_sig and macd_sig != 0:
        bull_pts += 0.8
        reasons["macd_above_signal"] = 0.8
    if macd > 0 and macd_sig < 0:  # bullish cross
        bull_pts += 2.0
        reasons["macd_bull_cross"] = 2.0

    if bb_pct_b < 0.10:
        bull_pts += 1.5
        reasons["bb_oversold"] = 1.5

    if vol_ratio > 1.5 and ind.get("above_vwap"):
        bull_pts += 0.7
        reasons["volume_confirmed_bull"] = 0.7

    if ind.get("above_ema200"):
        bull_pts += 0.5
        reasons["above_ema200"] = 0.5

    if ind.get("ema_aligned_bull"):
        bull_pts += 0.8
        reasons["ema_aligned_bull"] = 0.8

    if ind.get("above_vwap"):
        bull_pts += 0.6
        reasons["above_vwap"] = 0.6

    if stoch_k < 20:
        bull_pts += 1.0
        reasons["stoch_oversold"] = 1.0

    if orderflow_score > 0.15:
        pts = orderflow_score * 1.2
        bull_pts += pts
        reasons["orderflow_bull"] = round(pts, 3)

    if sentiment_score > 0.2:
        pts = sentiment_score * 1.5
        bull_pts += pts
        reasons["sentiment_bull"] = round(pts, 3)

    # ── Bear scoring ─────────────────────────────────────────────────────
    if rsi > 65:
        bear_pts += 1.5
        reasons["rsi_overbought"] = -1.5

    if macd < macd_sig and macd_sig != 0:
        bear_pts += 0.8
        reasons["macd_below_signal"] = -0.8
    if macd < 0 and macd_sig > 0:  # bearish cross
        bear_pts += 2.0
        reasons["macd_bear_cross"] = -2.0

    if bb_pct_b > 0.90:
        bear_pts += 1.5
        reasons["bb_overbought"] = -1.5

    if vol_ratio > 1.5 and not ind.get("above_vwap"):
        bear_pts += 0.7
        reasons["volume_confirmed_bear"] = -0.7

    if not ind.get("above_ema200"):
        bear_pts += 0.5
        reasons["below_ema200"] = -0.5

    if ind.get("ema_aligned_bear"):
        bear_pts += 0.8
        reasons["ema_aligned_bear"] = -0.8

    if not ind.get("above_vwap"):
        bear_pts += 0.6
        reasons["below_vwap"] = -0.6

    if stoch_k > 80:
        bear_pts += 1.0
        reasons["stoch_overbought"] = -1.0

    if orderflow_score < -0.15:
        pts = abs(orderflow_score) * 1.2
        bear_pts += pts
        reasons["orderflow_bear"] = round(-pts, 3)

    if sentiment_score < -0.2:
        pts = abs(sentiment_score) * 1.5
        bear_pts += pts
        reasons["sentiment_bear"] = round(-pts, 3)

    # ── Direction decision ────────────────────────────────────────────────
    total = bull_pts + bear_pts
    if total == 0:
        return "HOLD", 0.0, reasons

    directional_share = max(bull_pts, bear_pts) / total
    strength = min((max(bull_pts, bear_pts) - 1.0) / 8.0, 1.0)
    confidence = directional_share * (0.65 + 0.35 * max(strength, 0.0))

    # Require minimum 6% edge margin to fire
    margin = abs(bull_pts - bear_pts) / max(total, 1)
    if margin < 0.06:
        return "HOLD", round(confidence, 4), reasons

    action = "BUY" if bull_pts > bear_pts else "SELL"
    return action, round(confidence, 4), reasons


# ── Trade plan ──────────────────────────────────────────────────────────────

def compute_equity_trade_plan(
    ind: dict,
    action: str,
    portfolio_value: float,
    max_position_pct: float = 0.08,
    sentiment_score: float = 0.0,
) -> dict:
    """
    Compute entry/stop/target and position size for an equity signal.

    Returns:
        entry_price, stop_price, target_price, position_size,
        shares, risk_reward, risk_dollars
    """
    entry = ind.get("close", 0.0)
    atr   = ind.get("atr",   1.0) or 1.0

    if action == "BUY":
        stop   = entry - atr * 2.0
        target = entry + atr * 4.0
    elif action == "SELL":
        stop   = entry + atr * 2.0
        target = entry - atr * 4.0
    else:
        return {"entry_price": entry, "action": "HOLD"}

    risk_per_share = abs(entry - stop)
    if risk_per_share == 0:
        risk_per_share = atr

    # Base position size: 2% portfolio risk
    risk_dollars_base = portfolio_value * 0.02
    shares_raw = int(risk_dollars_base / risk_per_share)

    # Soft sentiment scaling: bearish news on BUY reduces size by up to 30%
    sentiment_scale = 1.0
    if action == "BUY" and sentiment_score < -0.1:
        sentiment_scale = max(0.70, 1.0 + sentiment_score)
    elif action == "SELL" and sentiment_score > 0.1:
        sentiment_scale = max(0.70, 1.0 - sentiment_score)

    shares = int(shares_raw * sentiment_scale)
    # Allow 0 — caller / OMS skips zero-size instead of forcing a 1-share trade.
    shares = max(0, shares)

    # Cap at max_position_pct of portfolio
    max_shares = int((portfolio_value * max_position_pct) / max(entry, 0.01))
    if shares > 0:
        shares = min(shares, max_shares)

    position_size = shares * entry
    risk_dollars  = shares * risk_per_share
    reward_dollars = shares * abs(target - entry)
    risk_reward   = round(reward_dollars / max(risk_dollars, 0.01), 2)
    # % move from entry to the 4xATR target — lets a caller judge a signal's
    # projected size (e.g. "only trade setups targeting 5%+") without having
    # to recompute it from entry_price/target_price everywhere it's shown.
    target_move_pct = round(abs(target - entry) / entry * 100, 2) if entry else 0.0

    return {
        "entry_price":     round(entry, 4),
        "stop_price":      round(stop, 4),
        "target_price":    round(target, 4),
        "target_move_pct": target_move_pct,
        "position_size":   round(position_size, 2),
        "shares":          shares,
        "risk_reward":     risk_reward,
        "risk_dollars":    round(risk_dollars, 2),
        "sentiment_scale": round(sentiment_scale, 3),
    }


# ── Earnings gate ───────────────────────────────────────────────────────────

_earnings_cache: dict[str, tuple[bool, datetime]] = {}
_CACHE_TTL_SECONDS = 3600


def earnings_gate(ticker: str, gate_days: int = 3) -> bool:
    """
    Returns True if earnings are within gate_days — signal should be skipped.
    Uses yfinance calendar; falls back to False (allow) on any error.
    """
    now = datetime.now(timezone.utc)
    if ticker in _earnings_cache:
        gated, cached_at = _earnings_cache[ticker]
        if (now - cached_at).total_seconds() < _CACHE_TTL_SECONDS:
            return gated

    try:
        import yfinance as yf  # type: ignore
        t = yf.Ticker(ticker)
        cal = t.calendar  # returns dict in yfinance >=0.2.x, DataFrame in older

        # Normalise: accept both dict and DataFrame
        earn_dates: list = []
        if cal is None:
            pass
        elif isinstance(cal, dict):
            # New yfinance API: {"Earnings Date": [Timestamp, ...], ...}
            earn_dates = cal.get("Earnings Date", []) or []
        else:
            # Legacy DataFrame
            try:
                if not cal.empty and "Earnings Date" in cal.index:
                    earn_dates = list(cal.loc["Earnings Date"])
            except Exception:
                pass

        for val in earn_dates:
            try:
                ts = pd.Timestamp(val)
                if ts.tzinfo is None:
                    ts = ts.tz_localize("UTC")
                else:
                    ts = ts.tz_convert("UTC")
                days_away = (ts - pd.Timestamp(now)).days
                if abs(days_away) <= gate_days:
                    logger.info("Earnings gate triggered for %s — %d days away", ticker, days_away)
                    _earnings_cache[ticker] = (True, now)
                    return True
            except Exception:
                continue

    except Exception as exc:
        logger.warning("Earnings gate check failed for %s: %s", ticker, exc)

    _earnings_cache[ticker] = (False, now)
    return False
