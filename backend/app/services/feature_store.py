"""
Centralized Feature Store.

ONE validated home for the indicator/feature math that was previously duplicated
across the Symphony DSL, the regime classifier, and the equity signal engine.
Strategies and research all compute features through this registry so a formula
lives in exactly one place and carries its own metadata + validation bounds.

Design:
  • Each feature is a FeatureSpec(name, fn, source, update_frequency, kind, ...).
  • `fn` is pure and takes the data shape declared by `source`:
        price_series  → fn(s: pd.Series, window: int) -> float
        ohlcv         → fn(df: pd.DataFrame, window: int) -> float   (needs high/low/close)
        iv_series     → fn(s: pd.Series, window: int) -> float
        two_series    → fn(pair: tuple[pd.Series, pd.Series], window: int) -> float
  • `compute(name, data, window=...)` dispatches and validates the result.

`SERIES_INDICATORS` is exported for hot-path callers (the Symphony evaluator) so
they reference the same implementations without going through validation on every
node evaluation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd


class FeatureError(Exception):
    """Raised on unknown feature, bad input shape, or failed validation."""


# ── Source / kind vocabulary ─────────────────────────────────────────────────────
SRC_PRICE = "price_series"
SRC_OHLCV = "ohlcv"
SRC_IV = "iv_series"
SRC_TWO = "two_series"


@dataclass(frozen=True)
class FeatureSpec:
    name:             str
    fn:               Callable
    source:           str
    update_frequency: str            # "intraday" | "daily"
    kind:             str            # "trend" | "momentum" | "volatility" | "vol_regime" | "correlation"
    description:      str
    min_value:        Optional[float] = None
    max_value:        Optional[float] = None

    def as_dict(self) -> dict:
        return {
            "name": self.name, "source": self.source,
            "update_frequency": self.update_frequency, "kind": self.kind,
            "description": self.description,
            "bounds": [self.min_value, self.max_value],
        }


# ── Indicator implementations (single source of truth) ───────────────────────────
def rsi(s: pd.Series, window: int = 14) -> float:
    delta = s.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    val = out.iloc[-1]
    return float(val) if val == val else 50.0  # NaN → neutral


def sma(s: pd.Series, window: int = 20) -> float:
    return float(s.tail(window).mean())


def ema(s: pd.Series, window: int = 20) -> float:
    return float(s.ewm(span=window, adjust=False).mean().iloc[-1])


def price(s: pd.Series, window: int = 0) -> float:
    return float(s.iloc[-1])


def cumulative_return(s: pd.Series, window: int = 20) -> float:
    if len(s) <= window:
        window = len(s) - 1
    if window <= 0:
        return 0.0
    return float(s.iloc[-1] / s.iloc[-1 - window] - 1.0)


def volatility(s: pd.Series, window: int = 20) -> float:
    rets = s.pct_change().tail(window)
    v = rets.std() * np.sqrt(252)
    return float(v) if v == v else 0.0


def max_drawdown(s: pd.Series, window: int = 60) -> float:
    w = s.tail(window)
    peak = w.cummax()
    dd = (w / peak - 1.0).min()
    return float(abs(dd)) if dd == dd else 0.0


def atr(df: pd.DataFrame, window: int = 14) -> float:
    """Average True Range from an OHLCV frame (needs high/low/close columns)."""
    for col in ("high", "low", "close"):
        if col not in df.columns:
            raise FeatureError(f"atr requires '{col}' column")
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(),
                    (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    val = tr.tail(window).mean()
    return float(val) if val == val else 0.0


def iv_rank(s: pd.Series, window: int = 252) -> float:
    """Where current IV sits in its [min,max] range over the window → 0..100."""
    w = s.tail(window).dropna()
    if len(w) < 2:
        return 0.0
    lo, hi, cur = float(w.min()), float(w.max()), float(w.iloc[-1])
    if hi - lo < 1e-12:
        return 0.0
    return float((cur - lo) / (hi - lo) * 100.0)


def iv_percentile(s: pd.Series, window: int = 252) -> float:
    """Percent of observations in the window below the current value → 0..100."""
    w = s.tail(window).dropna()
    if len(w) < 2:
        return 0.0
    cur = float(w.iloc[-1])
    return float((w < cur).mean() * 100.0)


def momentum(s: pd.Series, window: int = 20) -> float:
    """Trailing return over the window (alias of cumulative_return, momentum kind)."""
    return cumulative_return(s, window)


def correlation(pair: tuple[pd.Series, pd.Series], window: int = 60) -> float:
    """Pearson correlation of the two series' returns over the window → -1..1."""
    a, b = pair
    ra = a.pct_change().tail(window)
    rb = b.pct_change().tail(window)
    joined = pd.concat([ra, rb], axis=1).dropna()
    if len(joined) < 2:
        return 0.0
    c = joined.iloc[:, 0].corr(joined.iloc[:, 1])
    return float(c) if c == c else 0.0


# ── Registry ──────────────────────────────────────────────────────────────────────
FEATURES: dict[str, FeatureSpec] = {}


def register(spec: FeatureSpec) -> None:
    FEATURES[spec.name] = spec


def _seed() -> None:
    specs = [
        FeatureSpec("rsi", rsi, SRC_PRICE, "intraday", "momentum",
                    "Relative Strength Index", 0.0, 100.0),
        FeatureSpec("sma", sma, SRC_PRICE, "intraday", "trend",
                    "Simple moving average", 0.0, None),
        FeatureSpec("ema", ema, SRC_PRICE, "intraday", "trend",
                    "Exponential moving average", 0.0, None),
        FeatureSpec("price", price, SRC_PRICE, "intraday", "trend",
                    "Latest price", 0.0, None),
        FeatureSpec("cumulative_return", cumulative_return, SRC_PRICE, "intraday",
                    "momentum", "Trailing return over window", -1.0, None),
        FeatureSpec("momentum", momentum, SRC_PRICE, "intraday", "momentum",
                    "Trailing return (momentum)", -1.0, None),
        FeatureSpec("volatility", volatility, SRC_PRICE, "intraday", "volatility",
                    "Annualized realized volatility", 0.0, None),
        FeatureSpec("max_drawdown", max_drawdown, SRC_PRICE, "daily", "volatility",
                    "Max peak-to-trough drawdown over window", 0.0, 1.0),
        FeatureSpec("atr", atr, SRC_OHLCV, "intraday", "volatility",
                    "Average True Range", 0.0, None),
        FeatureSpec("iv_rank", iv_rank, SRC_IV, "daily", "vol_regime",
                    "IV rank within trailing range", 0.0, 100.0),
        FeatureSpec("iv_percentile", iv_percentile, SRC_IV, "daily", "vol_regime",
                    "IV percentile within window", 0.0, 100.0),
        FeatureSpec("correlation", correlation, SRC_TWO, "daily", "correlation",
                    "Return correlation of two assets", -1.0, 1.0),
    ]
    for s in specs:
        register(s)


_seed()


# Series-only indicators, exposed for hot-path callers (Symphony evaluator), with
# the alias keys Symphony historically supported.
SERIES_INDICATORS: dict[str, Callable] = {
    name: spec.fn for name, spec in FEATURES.items() if spec.source == SRC_PRICE
}
SERIES_INDICATORS["current_price"] = price   # alias
SERIES_INDICATORS["cum_return"] = cumulative_return  # alias


# ── Public API ────────────────────────────────────────────────────────────────────
def get(name: str) -> FeatureSpec:
    if name not in FEATURES:
        raise FeatureError(f"unknown feature '{name}'")
    return FEATURES[name]


def names() -> list[str]:
    return sorted(FEATURES)


def catalog() -> list[dict]:
    return [FEATURES[n].as_dict() for n in names()]


def validate(name: str, value: float) -> bool:
    """True when value is finite and within the feature's declared bounds."""
    spec = get(name)
    if value is None or not math.isfinite(value):
        return False
    if spec.min_value is not None and value < spec.min_value:
        return False
    if spec.max_value is not None and value > spec.max_value:
        return False
    return True


def compute(name: str, data, window: Optional[int] = None) -> float:
    """Dispatch to the feature's fn and validate the result."""
    spec = get(name)
    value = spec.fn(data, window) if window is not None else spec.fn(data)
    if not validate(name, value):
        raise FeatureError(f"feature '{name}' produced out-of-bounds value: {value}")
    return value
