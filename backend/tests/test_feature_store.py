"""Tests for the centralized Feature Store."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services import feature_store as fs
from app.services.feature_store import (
    FeatureError, FeatureSpec, SERIES_INDICATORS,
    atr, catalog, compute, correlation, cumulative_return, ema, get, iv_percentile,
    iv_rank, max_drawdown, momentum, names, price, register, rsi, sma, validate,
    volatility,
)


def _trend(n=300, start=100.0, step=0.5):
    return pd.Series([start + i * step for i in range(n)])


def _ohlcv(n=60):
    close = _trend(n)
    return pd.DataFrame({"high": close + 1.0, "low": close - 1.0, "close": close})


# ── registry ──────────────────────────────────────────────────────────────────────
def test_seeded_features_present():
    for f in ("rsi", "sma", "ema", "price", "cumulative_return", "momentum",
              "volatility", "max_drawdown", "atr", "iv_rank", "iv_percentile",
              "correlation"):
        assert f in names()


def test_get_unknown_raises():
    with pytest.raises(FeatureError):
        get("does_not_exist")


def test_catalog_shape():
    cat = catalog()
    assert all({"name", "source", "update_frequency", "kind", "bounds"} <= set(c) for c in cat)
    rsi_spec = next(c for c in cat if c["name"] == "rsi")
    assert rsi_spec["bounds"] == [0.0, 100.0]


def test_spec_as_dict():
    d = get("rsi").as_dict()
    assert d["name"] == "rsi" and d["kind"] == "momentum"


# ── indicator math ──────────────────────────────────────────────────────────────────
def test_rsi_uptrend_above_neutral():
    # Mostly-up series (with small pullbacks so 'loss' isn't all-zero → not NaN).
    seq = [1.0, 1.0, 1.0, -0.5] * 30
    s = pd.Series(100.0 + np.cumsum(seq))
    assert rsi(s, 14) > 50


def test_rsi_nan_returns_neutral():
    # Pure flat (and pure monotonic) series → all-zero loss → NaN → neutral 50.
    assert rsi(pd.Series([100.0, 100.0]), 14) == 50.0
    assert fs.rsi(_trend(), 14) == 50.0


def test_sma_ema_price():
    s = _trend(50)
    assert sma(s, 10) == pytest.approx(float(s.tail(10).mean()))
    assert price(s) == s.iloc[-1]
    assert ema(s, 10) > 0


def test_cumulative_return_and_momentum_alias():
    s = pd.Series([100.0, 110.0])
    assert cumulative_return(s, 1) == pytest.approx(0.10)
    assert momentum(s, 1) == cumulative_return(s, 1)


def test_cumulative_return_window_guard():
    assert cumulative_return(pd.Series([100.0]), 5) == 0.0   # window collapses → 0


def test_volatility_nonnegative_and_nan_zero():
    assert volatility(_trend(), 20) >= 0.0
    assert volatility(pd.Series([100.0]), 20) == 0.0


def test_max_drawdown_detects_dip():
    s = pd.Series([100, 120, 60, 90], dtype=float)
    assert max_drawdown(s, 4) == pytest.approx(0.5)          # 120 → 60


def test_atr_positive_and_missing_column():
    assert atr(_ohlcv(), 14) > 0
    with pytest.raises(FeatureError):
        atr(pd.DataFrame({"close": [1, 2, 3]}), 14)


def test_iv_rank_and_percentile():
    s = pd.Series([10, 20, 30, 40, 50], dtype=float)
    assert iv_rank(s, 252) == pytest.approx(100.0)           # current is the max
    assert iv_percentile(s, 252) == pytest.approx(80.0)      # 4 of 5 below
    assert iv_rank(pd.Series([5.0]), 252) == 0.0             # too few points
    assert iv_percentile(pd.Series([5.0]), 252) == 0.0
    assert iv_rank(pd.Series([7.0, 7.0, 7.0]), 252) == 0.0   # flat range → 0


def test_correlation_positive_negative_and_short():
    r = np.array([0.01, -0.02, 0.03, -0.015, 0.02, -0.01] * 20)
    a = pd.Series(100.0 * np.cumprod(1 + r))
    b = pd.Series(100.0 * np.cumprod(1 - r))   # anti-correlated returns
    assert correlation((a, a), 60) > 0.99       # identical → ~1
    assert correlation((a, b), 60) < -0.9       # opposite returns → ~-1
    assert correlation((pd.Series([1.0]), pd.Series([1.0])), 60) == 0.0


# ── validate + compute ──────────────────────────────────────────────────────────────
def test_validate_bounds_and_finite():
    assert validate("rsi", 50.0)
    assert not validate("rsi", 150.0)        # above max
    assert not validate("rsi", -1.0)         # below min
    assert not validate("rsi", float("nan"))
    assert not validate("rsi", float("inf"))
    assert not validate("sma", None)


def test_compute_dispatches_and_validates():
    s = _trend(50)
    assert compute("sma", s, window=10) == pytest.approx(sma(s, 10))
    # price takes no window → compute without window
    assert compute("price", s) == price(s)


def test_compute_rejects_out_of_bounds(monkeypatch):
    register(FeatureSpec("bogus", lambda s, w: 999.0, fs.SRC_PRICE, "daily",
                         "trend", "always out of range", 0.0, 1.0))
    with pytest.raises(FeatureError):
        compute("bogus", _trend(10), window=5)


def test_series_indicators_aliases_present():
    assert SERIES_INDICATORS["current_price"] is price
    assert "cum_return" in SERIES_INDICATORS
    assert "volatility" in SERIES_INDICATORS
