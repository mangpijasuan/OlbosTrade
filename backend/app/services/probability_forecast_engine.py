"""Read-only probabilistic market outlooks for the Scenario Lab.

This module deliberately has no broker, OMS, or execution dependencies.  It
turns a validated OHLCV history into an informational three-scenario outlook.
The initial implementation is a transparent deterministic baseline; its model
evidence is labelled ``shadow`` until calibrated trained models replace it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import numpy as np

SUPPORTED_HORIZONS = (1, 3, 5, 10, 20)


@dataclass(frozen=True)
class ForecastBar:
    close: float
    high: float
    low: float
    volume: float = 0.0


def _softmax(values: Iterable[float]) -> list[float]:
    vals = list(values)
    peak = max(vals)
    exps = [math.exp(v - peak) for v in vals]
    total = sum(exps)
    return [v / total for v in exps]


def _rounded_probabilities(values: list[float]) -> list[int]:
    """Round percentages while guaranteeing the displayed result sums to 100."""
    raw = [v * 100 for v in values]
    rounded = [int(math.floor(v)) for v in raw]
    for idx in sorted(range(len(raw)), key=lambda i: raw[i] - rounded[i], reverse=True)[: 100 - sum(rounded)]:
        rounded[idx] += 1
    return rounded


def generate_forecast(symbol: str, horizon: int, bars: list[ForecastBar]) -> dict:
    """Generate a transparent baseline outlook from chronological daily bars."""
    ticker = symbol.strip().upper()
    if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
        raise ValueError("invalid symbol")
    if horizon not in SUPPORTED_HORIZONS:
        raise ValueError(f"horizon must be one of {SUPPORTED_HORIZONS}")
    if len(bars) < 45:
        return _abstain(ticker, horizon, "At least 45 valid daily bars are required", len(bars))

    close = np.asarray([b.close for b in bars], dtype=float)
    high = np.asarray([b.high for b in bars], dtype=float)
    low = np.asarray([b.low for b in bars], dtype=float)
    volume = np.asarray([b.volume for b in bars], dtype=float)
    if not np.isfinite(close).all() or (close <= 0).any():
        return _abstain(ticker, horizon, "Price history contains invalid values", len(bars))

    returns = np.diff(np.log(close))
    current = float(close[-1])
    momentum_5 = float(close[-1] / close[-6] - 1)
    momentum_20 = float(close[-1] / close[-21] - 1)
    realized_vol = float(np.std(returns[-20:], ddof=1) * math.sqrt(252))
    trend_distance = float(current / np.mean(close[-20:]) - 1)
    prev_close = close[:-1]
    true_ranges = np.maximum.reduce((high[1:] - low[1:], np.abs(high[1:] - prev_close), np.abs(low[1:] - prev_close)))
    atr = float(np.mean(true_ranges[-14:]))
    atr_pct = atr / current if current else 0.0
    recent_volume = float(np.mean(volume[-5:]))
    baseline_volume = float(np.mean(volume[-20:]))
    volume_ratio = recent_volume / baseline_volume if baseline_volume > 0 else 1.0

    scale = max(atr_pct, realized_vol / math.sqrt(252), 0.005)
    directional = (0.45 * momentum_5 + 0.35 * momentum_20 + 0.20 * trend_distance) / scale
    trend_stability = max(0.0, 1.0 - float(np.std(returns[-10:])) / max(float(np.std(returns[-40:])), 1e-6))
    bull, base, bear = _softmax([directional, 0.55 - abs(directional) * 0.35, -directional])
    probabilities = _rounded_probabilities([bull, base, bear])

    model_directions = [
        0.55 + max(-0.25, min(0.25, momentum_20 / max(scale, 1e-6) * 0.08)),
        0.55 + max(-0.25, min(0.25, momentum_5 / max(scale, 1e-6) * 0.08)),
        0.52 + max(-0.22, min(0.22, trend_distance / max(scale, 1e-6) * 0.07)),
    ]
    dispersion = float(np.std(model_directions))
    agreement = int(round(max(0, min(100, 100 - dispersion * 360 - abs(bull - bear) * 8))))
    data_quality = min(100, 72 + min(len(bars), 100) // 5 + (5 if baseline_volume > 0 else 0))
    separation = max(probabilities) - sorted(probabilities)[-2]

    abstain_reasons: list[str] = []
    if separation < 8:
        abstain_reasons.append("Scenario probabilities lack sufficient separation")
    if agreement < 55:
        abstain_reasons.append("Baseline models materially disagree")
    if data_quality < 75:
        abstain_reasons.append("Data quality is below the research threshold")
    if not math.isfinite(realized_vol) or realized_vol <= 0:
        abstain_reasons.append("Volatility estimate is unavailable")

    if abstain_reasons:
        confidence = "ABSTAIN"
        status = "ABSTAIN"
    elif agreement >= 80 and data_quality >= 90 and separation >= 18:
        confidence = "HIGH"
        status = "RESEARCH_CANDIDATE"
    elif agreement >= 65 and data_quality >= 80 and separation >= 10:
        confidence = "MEDIUM"
        status = "REVIEW_CANDIDATE"
    else:
        confidence = "LOW"
        status = "INFORMATIONAL"

    horizon_vol = realized_vol * math.sqrt(horizon / 252)
    expected_center = (0.4 * momentum_5 + 0.6 * momentum_20) * min(horizon / 5, 2.0)
    lower = expected_center - 1.15 * horizon_vol
    upper = expected_center + 1.15 * horizon_vol

    positive = []
    negative = []
    _factor(positive, negative, "Multi-timeframe trend", trend_distance, 14)
    _factor(positive, negative, "20-day momentum", momentum_20, 12)
    _factor(positive, negative, "5-day momentum", momentum_5, 9)
    _factor(positive, negative, "Relative volume", volume_ratio - 1.0, 7)
    _factor(positive, negative, "Volatility pressure", 0.22 - realized_vol, 6)

    scenario_names = ("Bull case", "Base case", "Bear case")
    scenario_ranges = ((expected_center, upper), (-0.45 * horizon_vol, 0.45 * horizon_vol), (lower, expected_center))
    compatibility = (
        ["Momentum swing", "Bull call spread", "Bull put spread"],
        ["No trade", "Defined-risk income after all gates"],
        ["Cash", "Bear put spread", "Bear call spread"],
    )
    scenarios = []
    for idx, name in enumerate(scenario_names):
        lo, hi = scenario_ranges[idx]
        scenarios.append({
            "key": ("bull", "base", "bear")[idx],
            "name": name,
            "probability": probabilities[idx],
            "return_range": {"lower_pct": round(lo * 100, 2), "upper_pct": round(hi * 100, 2)},
            "price_range": {"lower": round(current * (1 + lo), 2), "upper": round(current * (1 + hi), 2)},
            "volatility_assumption_pct": round(realized_vol * 100, 1),
            "strategy_compatibility": compatibility[idx],
        })

    return {
        "symbol": ticker,
        "horizon_days": horizon,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_tier": "SHADOW_BASELINE",
        "execution_eligible": False,
        "status": status,
        "confidence": confidence,
        "abstain": bool(abstain_reasons),
        "abstain_reasons": abstain_reasons,
        "probabilities": {"bull": probabilities[0], "base": probabilities[1], "bear": probabilities[2]},
        "expected_range": {
            "lower_pct": round(lower * 100, 2), "upper_pct": round(upper * 100, 2),
            "lower_price": round(current * (1 + lower), 2), "upper_price": round(current * (1 + upper), 2),
        },
        "current_price": round(current, 2),
        "expected_volatility_pct": round(realized_vol * 100, 1),
        "model_agreement": agreement,
        "data_quality": data_quality,
        "outcome_definition": {"version": "atr-0.75-v1", "bull": "> +0.75 ATR", "base": "-0.75 ATR to +0.75 ATR", "bear": "< -0.75 ATR"},
        "factors": {"positive": positive[:4], "negative": negative[:4]},
        "model_evidence": [
            {"model": "20-day logistic baseline proxy", "bull_probability": round(model_directions[0] * 100)},
            {"model": "5-day momentum baseline", "bull_probability": round(model_directions[1] * 100)},
            {"model": "regime trend benchmark", "bull_probability": round(model_directions[2] * 100)},
        ],
        "scenarios": scenarios,
        "diagnostics": {"bars": len(bars), "atr_pct": round(atr_pct * 100, 2), "trend_stability": round(trend_stability, 3)},
        "disclaimer": "Probabilities describe defined outcomes, not guaranteed prices or trade profitability.",
    }


def _factor(positive: list, negative: list, name: str, raw: float, scale: int) -> None:
    score = int(round(max(-scale, min(scale, raw * 180))))
    target = positive if score >= 0 else negative
    target.append({"name": name, "score": score})


def _abstain(symbol: str, horizon: int, reason: str, bars: int) -> dict:
    return {
        "symbol": symbol, "horizon_days": horizon,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_tier": "SHADOW_BASELINE", "execution_eligible": False,
        "status": "ABSTAIN", "confidence": "ABSTAIN", "abstain": True,
        "abstain_reasons": [reason], "probabilities": {"bull": 0, "base": 0, "bear": 0},
        "expected_range": None, "current_price": None, "expected_volatility_pct": None,
        "model_agreement": 0, "data_quality": min(70, bars), "factors": {"positive": [], "negative": []},
        "model_evidence": [], "scenarios": [], "diagnostics": {"bars": bars},
        "outcome_definition": {"version": "atr-0.75-v1", "bull": "> +0.75 ATR", "base": "-0.75 ATR to +0.75 ATR", "bear": "< -0.75 ATR"},
        "disclaimer": "Insufficient evidence. No trade inference should be made.",
    }
