"""
Feature engineering for the signal scorer training pipeline.

Bridges app.services.backtester.BacktestTrade (the labeled data source) to
app.services.signal_scorer.SignalFeatures / FEATURE_NAMES (what the model
actually consumes at inference time) — the two must stay in lockstep or
training data won't match what the live scorer feeds the model.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Wilder's Average Directional Index from OHLC data.

    The backtester previously hardcoded adx=15.0 for every single trade
    (see backtester.py's call to strategy.generate_signal) — meaning the
    model would have learned nothing from this feature. Computed for real
    here so training data actually varies.
    """
    high, low, close = df["High"], df["Low"], df["Close"]

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr

    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()

    # Neutral default (matches the old hardcoded stub) where ADX is undefined
    # — the first `period` bars of any history window, and true zero-range bars.
    return adx.fillna(20.0)


# Order matters — must exactly match app.services.signal_scorer.FEATURE_NAMES.
FEATURE_NAMES = [
    "iv_rank", "iv_percentile", "vix_level",
    "spy_rsi_14", "spy_adx_14", "spy_trend_direction",
    "days_to_expiry", "short_strike_delta",
    "spread_width", "credit_to_width_ratio",
    "earnings_days_away", "spy_realized_vol_20d",
    "iv_minus_rv",
    "credit_theta_rate", "vix_term_slope",
]


def features_from_trade(trade) -> dict:
    """
    Build a FEATURE_NAMES-ordered feature dict from a BacktestTrade.

    earnings_days_away is fixed at 60 (SPY is an ETF — no single-name
    earnings event), matching the live options-scan path in main.py.
    vix_term_slope has no historical VIX3M/VIX series wired up yet, so it
    uses the same "mild contango" default the live SignalFeatures dataclass
    falls back to — a known limitation, not a bug: retrain once VIX3M
    history is available to stop constant-feature-izing this column.
    """
    dte = max(trade.days_to_expiry, 1.0)
    return {
        "iv_rank": trade.iv_rank,
        "iv_percentile": trade.iv_percentile,
        "vix_level": trade.entry_vix,
        "spy_rsi_14": trade.spy_rsi_14,
        "spy_adx_14": trade.spy_adx_14,
        "spy_trend_direction": trade.spy_trend_direction,
        "days_to_expiry": trade.days_to_expiry,
        "short_strike_delta": trade.short_strike_delta,
        "spread_width": trade.spread_width,
        "credit_to_width_ratio": trade.credit_to_width_ratio,
        "earnings_days_away": 60.0,
        "spy_realized_vol_20d": trade.spy_realized_vol_20d,
        "iv_minus_rv": trade.iv_minus_rv,
        "credit_theta_rate": trade.credit_to_width_ratio / dte,
        "vix_term_slope": 1.05,
    }


def ror_label(trade) -> float:
    """
    Realized return-on-risk for a closed BacktestTrade — the training label.

    max_loss = capital actually at risk. For the three credit strategies this
    is spread width minus credit received (the same quantity main.py's
    options-scan path computes as max_loss_dollars before gating on the
    scorer). bull_call_debit_spread has negative entry_credit (= -debit paid,
    see backtester.py's entry-side comment) and a different risk profile: max
    loss is simply the debit paid, not width-minus-credit — that formula
    would add the debit to the width instead of isolating it. Clipped to
    [-2, 2] to keep force-closed end-of-backtest trades (pnl=0, could still
    produce a degenerate ratio if max_loss rounds to ~0) and any other
    outliers from dominating the loss.
    """
    if trade.entry_credit < 0:
        max_loss = max(abs(trade.entry_credit) * 100 * trade.contracts, 1.0)
    else:
        max_loss = max((trade.spread_width - trade.entry_credit) * 100 * trade.contracts, 1.0)
    return float(np.clip(trade.pnl / max_loss, -2.0, 2.0))
