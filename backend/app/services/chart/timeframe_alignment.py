"""
Multi-Timeframe Alignment engine.

For each timeframe, classify trend from closed bars (EMA structure + higher-
high/higher-low sequence + price-vs-EMA), then combine into a weighted
alignment score. Weights are STRATEGY-CONFIGURABLE — no single timeframe model
is hard-coded for all strategies.

Pure and deterministic: operates on lists of closed bars, so it is fully
testable without network or the `ta` library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Trend = Literal["bullish", "neutral", "bearish"]

# Default timeframes and per-strategy weightings. Short-swing leans intraday,
# ETF swing leans mid, options-income leans higher timeframes.
TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d", "1w"]

STRATEGY_WEIGHTS: dict[str, dict[str, float]] = {
    "default":        {"5m": 0.5, "15m": 1.0, "1h": 1.0, "4h": 1.0, "1d": 1.0, "1w": 0.5},
    "short_swing":    {"5m": 0.5, "15m": 1.5, "1h": 1.5, "4h": 1.5, "1d": 1.0, "1w": 0.5},
    "etf_swing":      {"5m": 0.0, "15m": 0.5, "1h": 1.5, "4h": 1.5, "1d": 1.5, "1w": 1.0},
    "options_income": {"5m": 0.0, "15m": 0.0, "1h": 0.5, "4h": 1.0, "1d": 1.5, "1w": 1.5},
}


@dataclass
class TimeframeState:
    timeframe: str
    trend: Trend
    price_vs_ema: str          # "above" | "below" | "mixed"
    higher_highs_lows: bool
    detail: str


@dataclass
class AlignmentResult:
    per_timeframe: list[TimeframeState] = field(default_factory=list)
    score: float = 0.0          # 0–5 style, weighted
    max_score: float = 0.0
    bullish_count: int = 0
    bearish_count: int = 0
    total: int = 0
    dominant: Trend = "neutral"
    interpretation: str = ""

    def to_dict(self) -> dict:
        return {
            "per_timeframe": [
                {"timeframe": t.timeframe, "trend": t.trend,
                 "price_vs_ema": t.price_vs_ema, "higher_highs_lows": t.higher_highs_lows,
                 "detail": t.detail}
                for t in self.per_timeframe
            ],
            "score": round(self.score, 2),
            "max_score": round(self.max_score, 2),
            "bullish_count": self.bullish_count,
            "bearish_count": self.bearish_count,
            "total": self.total,
            "dominant": self.dominant,
            "interpretation": self.interpretation,
        }


def _ema(values: list[float], window: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (window + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _higher_highs_lows(highs: list[float], lows: list[float], lookback: int = 20) -> bool:
    """True if the recent window makes a higher high AND a higher low vs the
    prior window — a simple uptrend-structure check."""
    n = min(lookback, len(highs) // 2)
    if n < 3:
        return False
    recent_h, prior_h = max(highs[-n:]), max(highs[-2 * n:-n])
    recent_l, prior_l = min(lows[-n:]), min(lows[-2 * n:-n])
    return recent_h > prior_h and recent_l > prior_l


def classify_timeframe(timeframe: str, bars: list[dict]) -> TimeframeState:
    """Classify one timeframe's trend from CLOSED bars.

    bars: list of {"high","low","close"} oldest→newest (already closed)."""
    closes = [float(b["close"]) for b in bars if b.get("close") is not None]
    if len(closes) < 25:
        return TimeframeState(timeframe, "neutral", "mixed", False, "insufficient bars")

    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    ema20 = _ema(closes, 20)[-1]
    ema50 = _ema(closes, 50 if len(closes) >= 50 else 20)[-1]
    price = closes[-1]
    hh_hl = _higher_highs_lows(highs, lows)

    above = price > ema20 and ema20 >= ema50
    below = price < ema20 and ema20 <= ema50

    if above and hh_hl:
        trend: Trend = "bullish"
        detail = "price above rising EMAs with higher highs/lows"
    elif below:
        trend = "bearish"
        detail = "price below falling EMAs"
    elif above:
        trend = "bullish"
        detail = "price above EMAs"
    else:
        trend = "neutral"
        detail = "no clear EMA trend"

    pve = "above" if price > ema20 else "below" if price < ema20 else "mixed"
    return TimeframeState(timeframe, trend, pve, hh_hl, detail)


def align(per_timeframe: list[TimeframeState], strategy: str = "default") -> AlignmentResult:
    weights = STRATEGY_WEIGHTS.get(strategy, STRATEGY_WEIGHTS["default"])
    score = 0.0
    max_score = 0.0
    bull = bear = 0
    for tf in per_timeframe:
        w = weights.get(tf.timeframe, 1.0)
        max_score += w
        if tf.trend == "bullish":
            score += w
            bull += 1
        elif tf.trend == "bearish":
            score -= w
            bear += 1

    total = len(per_timeframe)
    dominant: Trend = "bullish" if score > 0.5 else "bearish" if score < -0.5 else "neutral"

    if abs(score) >= 0.8 * max_score and max_score > 0:
        interp = f"Strong multi-timeframe {dominant} agreement"
    elif dominant != "neutral":
        interp = f"Leaning {dominant}, higher-timeframe confirmation incomplete"
    else:
        interp = "Mixed timeframes — no clear alignment"

    return AlignmentResult(
        per_timeframe=per_timeframe,
        score=abs(score),          # magnitude of agreement
        max_score=max_score,
        bullish_count=bull,
        bearish_count=bear,
        total=total,
        dominant=dominant,
        interpretation=interp,
    )
