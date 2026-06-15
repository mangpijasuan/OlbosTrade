"""
Feature engineering pipeline for signal scorer training.
Computes all 15 features from raw market data + backtest results.

AUDIT FIXES:
- FIX-1: Look-ahead bias removed — rv20 and iv_rank computed only on data
         available at each trade's entry_date (strict point-in-time slicing).
- FIX-7: iv_rank/iv_percentile now computed from the same ATM IV series used
         in live inference (IVSurfaceEngine._update_iv_history), not from a
         realized-vol proxy. Training and serving now share the same definition.
- C1: Label is now continuous return-on-risk (RoR) float, not binary sign(P&L).
- C2: earnings_days_away capped at 60 days.

SUGGESTIONS IMPLEMENTED:
- S1: Two new options-specific features added:
      · credit_theta_rate  — daily credit decay relative to max risk (theta efficiency)
      · vix_term_slope     — VIX3M / VIX ratio (term structure: >1 contango, <1 stressed)
- S3: Label is now continuous RoR (float), enabling XGBRegressor in training.
      Model now predicts "how much will this trade earn per unit of risk"
      rather than "will this trade win or lose".
      S2 (Platt/isotonic calibration) is superseded by S3 — a regressor
      outputting RoR does not need probability calibration.
"""

import numpy as np
import pandas as pd
from typing import Optional


# ── S1: 2 new features added ──────────────────────────────────────────────────
# Total: 13 original + 2 new = 15 features
FEATURE_NAMES = [
    # Vol environment
    "iv_rank", "iv_percentile", "vix_level",
    # Price/trend
    "spy_rsi_14", "spy_adx_14", "spy_trend_direction",
    # Trade geometry
    "days_to_expiry", "short_strike_delta",
    "spread_width", "credit_to_width_ratio",
    # Risk events
    "earnings_days_away",
    # Realized vs implied vol spread
    "spy_realized_vol_20d", "iv_minus_rv",
    # S1: New options-specific features
    "credit_theta_rate",   # daily credit earned as % of max risk
    "vix_term_slope",      # VIX3M / VIX — vol term structure shape
]


def _ror_value(trade: dict) -> float:
    """
    S3 / C1 FIX — Continuous return-on-risk label for vertical spreads.

    For a credit spread the maximum risk is:
        max_risk = (spread_width * 100) - (credit_received * 100)

    Returns actual RoR = pnl / max_risk, clamped to [-1.0, 1.0].
    Positive = profitable; negative = loss; 0 = break-even.

    This is the regression target for XGBRegressor (S3).  A threshold of
    0.12 (12% RoR) is used at inference time instead of a probability cutoff.

    Why regression > classification:
      - A $5 win on a $500 max-risk trade (ror=1%) is NOT the same quality
        as a $50 win (ror=10%).  Binary labels can't distinguish these.
      - The regressor can say "this setup typically earns 18% RoR" which is
        a far more actionable signal for position sizing.
    """
    pnl           = float(trade.get("pnl", 0))
    spread_width  = float(trade.get("spread_width", 0))
    credit        = float(trade.get("credit_received", trade.get("entry_credit", 0)))

    if spread_width > 0 and credit > 0:
        max_risk = (spread_width * 100) - (credit * 100)
        if max_risk > 0:
            return float(np.clip(pnl / max_risk, -1.0, 1.0))

    # Fallback: use pnl / max_possible_loss if geometry missing
    # Assume 10-point spread as a conservative proxy
    fallback_risk = 1000.0   # $10-wide spread × 100 multiplier
    return float(np.clip(pnl / fallback_risk, -1.0, 1.0))


def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average Directional Index — pure rolling, no look-ahead."""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low  - close.shift(1)).abs()
    tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    up_move   = high - high.shift(1)
    down_move = low.shift(1) - low

    pos_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    neg_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    atr    = tr.ewm(span=period).mean()
    pos_di = 100 * pos_dm.ewm(span=period).mean() / atr
    neg_di = 100 * neg_dm.ewm(span=period).mean() / atr

    dx = (100 * (pos_di - neg_di).abs() / (pos_di + neg_di).replace(0, np.nan))
    return dx.ewm(span=period).mean()


def build_feature_matrix(
    ohlcv: pd.DataFrame,
    iv_history: pd.Series,
    vix_history: pd.Series,
    trades: list[dict],
    vix3m_history: Optional[pd.Series] = None,   # S1: VIX3M for term structure
) -> pd.DataFrame:
    """
    Build the full feature matrix from historical data + trade records.

    Args:
        ohlcv:         OHLCV DataFrame with Date index (tz-naive)
        iv_history:    Daily ATM IV series — must match live inference source.
        vix_history:   Daily VIX closing values
        trades:        List of dicts from backtest output
        vix3m_history: S1 — Daily VIX3M (3-month IV) series for term structure.
                       Pass None to use default slope of 1.05 (mild contango).

    Returns:
        DataFrame with FEATURE_NAMES columns + 'label' (continuous RoR) + 'entry_date'.
        Sorted by entry_date ascending (required for TimeSeriesSplit in training).
    """
    close = ohlcv["Close"]
    high  = ohlcv["High"]
    low   = ohlcv["Low"]

    rsi   = _compute_rsi(close)
    sma20 = close.rolling(20).mean()
    adx   = compute_adx(high, low, close)
    log_ret = np.log(close / close.shift(1))

    # S1: Align VIX3M to SPY calendar (same as iv_history alignment in trainer)
    if vix3m_history is not None:
        vix3m_history = vix3m_history.reindex(ohlcv.index, method="ffill")

    rows = []
    for trade in trades:
        entry_date = pd.Timestamp(trade["entry_date"])
        if entry_date not in ohlcv.index:
            continue

        idx = ohlcv.index.get_loc(entry_date)
        if idx < 20:
            continue

        # ── Point-in-time IV rank / percentile (FIX-1 + FIX-7) ───────────────
        lookback_iv = iv_history.iloc[:idx + 1]
        iv_r        = _iv_rank(lookback_iv)
        iv_p        = _iv_percentile(lookback_iv)
        iv_current  = float(lookback_iv.iloc[-1]) if len(lookback_iv) > 0 else 0.20

        # ── Point-in-time realized vol (FIX-1) ───────────────────────────────
        rv_pit     = log_ret.iloc[:idx + 1].rolling(20).std().iloc[-1]
        rv_current = float(rv_pit * np.sqrt(252)) if not pd.isna(rv_pit) else 0.20

        # ── S1: VIX term structure slope ──────────────────────────────────────
        # VIX3M / VIX ratio:
        #   > 1.0 → contango (near-term vol cheaper than medium-term) = NORMAL
        #   < 1.0 → backwardation (near-term vol elevated) = STRESS / CRISIS
        #   ~ 1.0 → flat term structure = neutral
        # Options sellers prefer contango (slope > 1): front-month premium is
        # fair but not distorted by near-term fear.
        vix_spot = float(vix_history.iloc[idx]) if idx < len(vix_history) else 20.0
        if vix3m_history is not None and idx < len(vix3m_history):
            vix3m_val = float(vix3m_history.iloc[idx])
            vix_slope = (vix3m_val / vix_spot) if vix_spot > 0 else 1.05
        else:
            vix_slope = 1.05   # mild contango default

        # ── S1: Credit theta rate ─────────────────────────────────────────────
        # Measures how much of the max-risk you collect PER DAY.
        # credit_theta_rate = credit_to_width / DTE
        # High value = fast theta decay relative to risk = efficient trade
        # e.g. 0.30 credit on $10-wide at DTE=30 → 0.30/30 = 0.01 per day
        dte   = float(trade.get("days_to_expiry", 35))
        ctw   = float(trade.get("credit_to_width_ratio", 0.25))
        theta_rate = ctw / max(dte, 1.0)   # avoid division by zero

        row = {
            "entry_date":            entry_date,
            "iv_rank":               iv_r,
            "iv_percentile":         iv_p,
            "vix_level":             vix_spot,
            "spy_rsi_14":            float(rsi.iloc[idx])   if not pd.isna(rsi.iloc[idx])   else 50.0,
            "spy_adx_14":            float(adx.iloc[idx])   if not pd.isna(adx.iloc[idx])   else 20.0,
            "spy_trend_direction":   1.0 if float(close.iloc[idx]) > float(sma20.iloc[idx]) else -1.0,
            "days_to_expiry":        dte,
            "short_strike_delta":    float(trade.get("short_strike_delta", 0.20)),
            "spread_width":          float(trade.get("spread_width", 10.0)),
            "credit_to_width_ratio": ctw,
            # C2: cap at 60 — beyond 60 days earnings have no options pricing effect
            "earnings_days_away":    min(float(trade.get("earnings_days_away", 999)), 60.0),
            "spy_realized_vol_20d":  rv_current,
            "iv_minus_rv":           iv_current - rv_current,
            # S1 new features
            "credit_theta_rate":     round(theta_rate, 6),
            "vix_term_slope":        round(vix_slope, 4),
            # S3: continuous RoR target (replaces binary label)
            "label":                 _ror_value(trade),
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("entry_date").reset_index(drop=True)
    return df


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _iv_rank(iv_series: pd.Series, lookback: int = 252) -> float:
    """IV rank computed on strictly point-in-time data."""
    window  = iv_series.iloc[-lookback:]
    if len(window) < 2:
        return 0.0
    current = float(window.iloc[-1])
    lo, hi  = float(window.min()), float(window.max())
    return round(((current - lo) / (hi - lo)) * 100, 2) if hi != lo else 0.0


def _iv_percentile(iv_series: pd.Series, lookback: int = 252) -> float:
    """IV percentile computed on strictly point-in-time data."""
    window  = iv_series.iloc[-lookback:]
    if len(window) < 2:
        return 0.0
    current = float(window.iloc[-1])
    return round(float((window < current).mean() * 100), 2)
