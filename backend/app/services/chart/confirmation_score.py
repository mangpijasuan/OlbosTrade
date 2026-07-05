"""
Trade Confirmation Score — Module 5.

A configurable, TRANSPARENT evidence score (0–100) combining chart and context
factors. It returns the supporting evidence and the risk factors that produced
it, so nothing is a black box.

It is an EVIDENCE / CONFIRMATION score, not a calibrated probability of success,
until Module 11 research validates it. It never emits a buy/sell decision and
never bypasses the risk/portfolio/macro gates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ScoreInputs:
    # Chart evidence
    alignment_score: float               # weighted alignment magnitude
    alignment_max: float
    dominant: str                        # bullish/neutral/bearish
    structure_agrees: bool
    breakout_confirmed: bool
    relative_volume: Optional[float]
    above_vwap: Optional[bool]
    atr_pct: Optional[float]
    # Context
    regime_fit: bool                     # regime compatible with the bias
    macro_risk: str                      # low/moderate/high/very_high
    portfolio_overlap_pct: Optional[float]
    max_overlap_pct: float = 25.0
    data_quality: Optional[int] = None   # 0–100 from intel registry


@dataclass
class ConfirmationScore:
    score: int
    supporting: list[str] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
    contributions: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "supporting": self.supporting,
            "risk_factors": self.risk_factors,
            "contributions": {k: round(v, 1) for k, v in self.contributions.items()},
            "note": "Confirmation/evidence score, not a calibrated probability of success.",
        }


def compute_confirmation_score(inp: ScoreInputs) -> ConfirmationScore:
    contrib: dict[str, float] = {}
    supporting: list[str] = []
    risk: list[str] = []

    # Multi-timeframe alignment — up to 30.
    if inp.alignment_max > 0 and inp.dominant != "neutral":
        a = 30.0 * (inp.alignment_score / inp.alignment_max)
        contrib["alignment"] = a
        supporting.append(f"{inp.dominant} multi-timeframe alignment")
    else:
        contrib["alignment"] = 0.0
        risk.append("no clear timeframe alignment")

    # Structure agreement — 12.
    contrib["structure"] = 12.0 if inp.structure_agrees else 0.0
    if inp.structure_agrees:
        supporting.append("market structure agrees with bias")

    # Breakout confirmed — 15.
    contrib["breakout"] = 15.0 if inp.breakout_confirmed else 0.0
    if inp.breakout_confirmed:
        supporting.append("breakout confirmed on a closed bar")

    # Relative volume — 10.
    if inp.relative_volume is not None and inp.relative_volume >= 1.2:
        contrib["relative_volume"] = 10.0
        supporting.append(f"relative volume {inp.relative_volume:.1f}x")
    else:
        contrib["relative_volume"] = 0.0

    # VWAP — 8.
    if (inp.above_vwap is True and inp.dominant == "bullish") or (inp.above_vwap is False and inp.dominant == "bearish"):
        contrib["vwap"] = 8.0
        supporting.append("price on the trend side of VWAP")
    else:
        contrib["vwap"] = 0.0

    # Regime fit — 10.
    contrib["regime"] = 10.0 if inp.regime_fit else 0.0
    if inp.regime_fit:
        supporting.append("market regime compatible")

    # Data quality — up to 5.
    if inp.data_quality is not None:
        contrib["data_quality"] = 5.0 * (inp.data_quality / 100.0)
        if inp.data_quality < 70:
            risk.append(f"data quality {inp.data_quality}/100")
    else:
        contrib["data_quality"] = 0.0

    # ── Penalties ────────────────────────────────────────────────────────────
    macro = (inp.macro_risk or "low").lower()
    if macro in ("high", "very_high"):
        contrib["macro_penalty"] = -18.0
        risk.append("high-impact macro event near")
    elif macro == "moderate":
        contrib["macro_penalty"] = -8.0
        risk.append("macro event in window")
    else:
        contrib["macro_penalty"] = 0.0

    if inp.portfolio_overlap_pct is not None and inp.portfolio_overlap_pct > inp.max_overlap_pct:
        contrib["overlap_penalty"] = -12.0
        risk.append(f"portfolio overlap {inp.portfolio_overlap_pct:.0f}% over {inp.max_overlap_pct:.0f}% limit")
    else:
        contrib["overlap_penalty"] = 0.0

    if inp.atr_pct is not None and inp.atr_pct >= 3.0:
        contrib["extension_penalty"] = -6.0
        risk.append("price extended vs normal range")
    else:
        contrib["extension_penalty"] = 0.0

    total = sum(contrib.values())
    score = int(max(0, min(100, round(total))))
    return ConfirmationScore(score=score, supporting=supporting, risk_factors=risk, contributions=contrib)
