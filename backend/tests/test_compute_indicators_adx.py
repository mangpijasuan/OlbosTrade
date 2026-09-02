"""
compute_indicators' adx field — previously ADX was only available as a
single shared market-wide reading (main.py's options scan read it off the
regime classifier for every symbol). Computed per-symbol here so each
stock's own trend strength is available wherever indicators are computed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.equity_signal_engine import compute_indicators


def _trending_bars(n: int = 60) -> pd.DataFrame:
    """A steadily rising series — should produce a real (non-default,
    non-NaN) ADX once enough bars have accumulated."""
    closes = np.linspace(100, 160, n)
    return pd.DataFrame({
        "open":   closes - 0.5,
        "high":   closes + 1.0,
        "low":    closes - 1.0,
        "close":  closes,
        "volume": np.full(n, 1_000_000),
    })


def test_adx_key_present_and_numeric():
    ind = compute_indicators(_trending_bars())
    assert "adx" in ind
    assert isinstance(ind["adx"], float)
    assert not np.isnan(ind["adx"])


def test_adx_reflects_a_real_trend_not_the_neutral_default():
    # A clean, steady uptrend should register meaningfully above the
    # neutral default (20.0) used when data is insufficient.
    ind = compute_indicators(_trending_bars())
    assert ind["adx"] > 20.0


def test_insufficient_bars_returns_empty_dict_no_adx_key():
    ind = compute_indicators(_trending_bars(n=10))
    assert ind == {}
