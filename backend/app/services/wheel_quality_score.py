"""
Wheel Quality Score (WQS) — ranks cash-secured put / covered-call candidates 0–100.

DESIGN PHILOSOPHY (see ARCHITECTURE_MEMO): OlbosTrade prioritizes capital
preservation, so WQS is SAFETY-TILTED by default and RISK-PROFILE-AWARE. The
same six factors are re-weighted per profile — conservative leans ~75% on
safety factors, aggressive shifts toward ~60% income.

WQS ranks *quality*. It NEVER overrides the eligibility gate — a candidate can
score 85 and still be blocked by concentration/guardrail limits. The two are
separate concerns (see csp_eligibility_gate).

The score is fully explainable: score_candidate() returns per-factor
contributions so the UI detail drawer can show "why it ranked".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RiskProfile = Literal["conservative", "balanced", "aggressive"]

# Factor weights per risk profile. Each column sums to 1.0.
# Safety factors: distance_to_strike, liquidity, event_free.
# Income factors: premium_yield, iv_rank.
# Neutral: delta_in_band.
_WEIGHTS: dict[RiskProfile, dict[str, float]] = {
    "conservative": {
        "distance_to_strike": 0.30,
        "liquidity": 0.25,
        "event_free": 0.20,
        "premium_yield": 0.12,
        "iv_rank": 0.08,
        "delta_in_band": 0.05,
    },
    "balanced": {
        "distance_to_strike": 0.22,
        "liquidity": 0.20,
        "event_free": 0.15,
        "premium_yield": 0.25,
        "iv_rank": 0.13,
        "delta_in_band": 0.05,
    },
    "aggressive": {
        "distance_to_strike": 0.15,
        "liquidity": 0.15,
        "event_free": 0.10,
        "premium_yield": 0.35,
        "iv_rank": 0.20,
        "delta_in_band": 0.05,
    },
}

# Target delta band for a "healthy" CSP — full credit in-band, decaying outside.
_DELTA_BAND_LOW = 0.15
_DELTA_BAND_HIGH = 0.30

# Annualized premium yield (as a fraction) that maps to a full income score.
# 30% annualized is treated as excellent for a defined-collateral CSP.
_YIELD_FULL_SCORE = 0.30


@dataclass
class WqsInputs:
    """Raw candidate metrics needed to compute the Wheel Quality Score."""

    stock_price: float
    put_strike: float
    delta: float                 # absolute value, 0–1
    premium: float               # per-share credit
    dte: int
    iv_rank: float               # 0–100
    open_interest: int
    bid_ask_spread: float        # absolute dollars
    days_to_next_event: int | None  # earnings/macro; None = none in window


@dataclass
class WqsResult:
    score: float                            # 0–100
    factors: dict[str, float]               # per-factor normalized value 0–1
    contributions: dict[str, float]         # weighted points each factor added
    profile: RiskProfile


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _distance_to_strike_score(inp: WqsInputs) -> float:
    """Cushion between spot and strike. 0% OTM = 0, >=15% OTM = 1."""
    if inp.stock_price <= 0:
        return 0.0
    otm_fraction = (inp.stock_price - inp.put_strike) / inp.stock_price
    return _clamp(otm_fraction / 0.15)


def _liquidity_score(inp: WqsInputs) -> float:
    """Blend open interest depth and bid-ask tightness."""
    oi_score = _clamp(inp.open_interest / 1000.0)
    # $0.05 spread or tighter = perfect; $0.30+ = zero.
    spread_score = _clamp((0.30 - inp.bid_ask_spread) / 0.25)
    return 0.6 * oi_score + 0.4 * spread_score


def _event_free_score(inp: WqsInputs) -> float:
    """Reward a clear runway to expiration. Event inside DTE = penalized."""
    if inp.days_to_next_event is None:
        return 1.0
    if inp.dte <= 0:
        return 1.0
    # Event before expiry is bad; the closer, the worse.
    if inp.days_to_next_event >= inp.dte:
        return 1.0
    return _clamp(inp.days_to_next_event / inp.dte)


def _premium_yield_score(inp: WqsInputs) -> float:
    """Annualized premium yield on collateral, normalized to _YIELD_FULL_SCORE."""
    if inp.put_strike <= 0 or inp.dte <= 0:
        return 0.0
    period_yield = inp.premium / inp.put_strike
    annualized = period_yield * (365.0 / inp.dte)
    return _clamp(annualized / _YIELD_FULL_SCORE)


def _iv_rank_score(inp: WqsInputs) -> float:
    return _clamp(inp.iv_rank / 100.0)


def _delta_in_band_score(inp: WqsInputs) -> float:
    """Full score inside the target band, linear decay outside."""
    d = inp.delta
    if _DELTA_BAND_LOW <= d <= _DELTA_BAND_HIGH:
        return 1.0
    if d < _DELTA_BAND_LOW:
        # Too far OTM — little premium. Decay over a 0.10 window.
        return _clamp(1.0 - (_DELTA_BAND_LOW - d) / 0.10)
    # Too close / ITM risk — decay faster over a 0.15 window.
    return _clamp(1.0 - (d - _DELTA_BAND_HIGH) / 0.15)


_FACTOR_FNS = {
    "distance_to_strike": _distance_to_strike_score,
    "liquidity": _liquidity_score,
    "event_free": _event_free_score,
    "premium_yield": _premium_yield_score,
    "iv_rank": _iv_rank_score,
    "delta_in_band": _delta_in_band_score,
}


def score_candidate(inp: WqsInputs, profile: RiskProfile = "balanced") -> WqsResult:
    """Compute the Wheel Quality Score and its explainable breakdown."""
    weights = _WEIGHTS[profile]
    factors: dict[str, float] = {}
    contributions: dict[str, float] = {}

    for name, fn in _FACTOR_FNS.items():
        raw = _clamp(fn(inp))
        factors[name] = raw
        contributions[name] = round(raw * weights[name] * 100.0, 2)

    score = round(sum(contributions.values()), 1)
    return WqsResult(
        score=score,
        factors=factors,
        contributions=contributions,
        profile=profile,
    )
