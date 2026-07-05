"""
Market Bias assembler.

Combines multi-timeframe alignment, market structure, and daily indicators into
a single Market Bias Card: bias (bullish/neutral/bearish), an evidence-based
confidence (0–100), trend/volatility/relative-volume/VWAP context, regime fit,
macro-event risk, main supporting evidence, and the main risk factor.

PURE: all live inputs are passed in. It is an EVIDENCE score, not a probability
of success, and it never emits a buy/sell recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from app.services.chart.timeframe_alignment import AlignmentResult
from app.services.chart.market_structure import StructureResult

Bias = Literal["bullish", "neutral", "bearish"]


@dataclass
class BiasInputs:
    symbol: str
    price: float | None
    alignment: AlignmentResult
    structure: StructureResult
    rsi: float | None = None
    above_vwap: bool | None = None
    relative_volume: float | None = None
    atr_pct: float | None = None            # ATR as % of price (volatility state)
    regime: Optional[str] = None            # e.g. "low_vol_trending"
    macro_risk: Optional[str] = None        # "low" | "moderate" | "high" | "very_high"
    data_freshness_s: float = 0.0


@dataclass
class BiasResult:
    symbol: str
    price: float | None
    bias: Bias
    confidence: int                         # 0–100 evidence score
    trend_state: str
    volatility_state: str
    relative_volume_state: str
    vwap_state: str
    regime_fit: str
    macro_risk: str
    timeframe_alignment: str                # "4 of 5 bullish"
    main_evidence: str
    main_risk: str
    data_freshness_s: float

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "bias": self.bias,
            "confidence": self.confidence,
            "trend_state": self.trend_state,
            "volatility_state": self.volatility_state,
            "relative_volume_state": self.relative_volume_state,
            "vwap_state": self.vwap_state,
            "regime_fit": self.regime_fit,
            "macro_risk": self.macro_risk,
            "timeframe_alignment": self.timeframe_alignment,
            "main_evidence": self.main_evidence,
            "main_risk": self.main_risk,
            "data_freshness_s": round(self.data_freshness_s, 1),
            "note": "Evidence score, not a probability. Not a buy/sell recommendation.",
        }


def _vol_state(atr_pct: float | None) -> str:
    if atr_pct is None:
        return "unknown"
    if atr_pct < 1.0:
        return "low"
    if atr_pct < 2.5:
        return "moderate"
    return "elevated"


def _rvol_state(rvol: float | None) -> str:
    if rvol is None:
        return "unknown"
    if rvol >= 1.5:
        return "elevated"
    if rvol >= 0.8:
        return "normal"
    return "below average"


def assemble_bias(inp: BiasInputs) -> BiasResult:
    align = inp.alignment
    bias: Bias = align.dominant

    # Evidence-based confidence: start from alignment strength, adjust for
    # structure agreement, VWAP, relative volume; penalise macro risk.
    conf = 0.0
    if align.max_score > 0:
        conf += 55.0 * (align.score / align.max_score)   # up to 55 from alignment

    struct_agrees = (
        (bias == "bullish" and inp.structure.state in ("uptrend",))
        or (bias == "bearish" and inp.structure.state in ("downtrend",))
    )
    if struct_agrees:
        conf += 15.0

    if inp.above_vwap is True and bias == "bullish":
        conf += 10.0
    elif inp.above_vwap is False and bias == "bearish":
        conf += 10.0

    if inp.relative_volume is not None and inp.relative_volume >= 1.2:
        conf += 8.0

    macro = (inp.macro_risk or "low").lower()
    if macro in ("high", "very_high"):
        conf -= 15.0
    elif macro == "moderate":
        conf -= 7.0

    confidence = int(max(0, min(100, round(conf))))

    # Human-readable context.
    trend = f"{bias.capitalize()} across timeframes" if bias != "neutral" else "No clear trend"
    tf_align = f"{align.bullish_count} of {align.total} bullish" if align.total else "—"
    vwap_state = ("above VWAP" if inp.above_vwap else "below VWAP") if inp.above_vwap is not None else "unknown"
    regime_fit = (inp.regime or "unknown").replace("_", " ")

    evidence_bits = []
    if align.dominant != "neutral":
        evidence_bits.append(align.interpretation.lower())
    if struct_agrees:
        evidence_bits.append(f"structure is {inp.structure.state}")
    if inp.above_vwap is not None:
        evidence_bits.append(vwap_state)
    main_evidence = "; ".join(evidence_bits[:3]) or "mixed signals"

    if macro in ("high", "very_high"):
        main_risk = "High-impact macro event near — new exposure should be reduced"
    elif inp.atr_pct is not None and inp.atr_pct >= 2.5:
        main_risk = "Elevated volatility — price is extended vs normal range"
    elif bias == "neutral":
        main_risk = "No timeframe alignment — wait for confirmation"
    else:
        main_risk = "Higher-timeframe confirmation may be incomplete"

    return BiasResult(
        symbol=inp.symbol,
        price=inp.price,
        bias=bias,
        confidence=confidence,
        trend_state=trend,
        volatility_state=_vol_state(inp.atr_pct),
        relative_volume_state=_rvol_state(inp.relative_volume),
        vwap_state=vwap_state,
        regime_fit=regime_fit,
        macro_risk=macro,
        timeframe_alignment=tf_align,
        main_evidence=main_evidence,
        main_risk=main_risk,
        data_freshness_s=inp.data_freshness_s,
    )
