"""Tests for the Market Bias assembler (pure composite)."""

from app.services.chart.market_bias import BiasInputs, assemble_bias
from app.services.chart.market_structure import StructureResult
from app.services.chart.timeframe_alignment import AlignmentResult, TimeframeState


def _align(dominant, bull, total, score, max_score):
    return AlignmentResult(
        per_timeframe=[TimeframeState("1h", dominant, "above", True, "")],
        score=score, max_score=max_score, bullish_count=bull, bearish_count=total - bull,
        total=total, dominant=dominant, interpretation=f"Strong {dominant} agreement",
    )


def _struct(state):
    return StructureResult(state=state, recent_event="", support=[1], resistance=[2], note="")


def test_bullish_bias_high_confidence():
    r = assemble_bias(BiasInputs(
        symbol="QQQ", price=500.0,
        alignment=_align("bullish", 5, 5, 5.0, 5.0),
        structure=_struct("uptrend"),
        rsi=60, above_vwap=True, relative_volume=1.6, atr_pct=1.2,
        regime="low_vol_trending", macro_risk="low",
    ))
    assert r.bias == "bullish"
    assert r.confidence >= 80
    assert "bullish" in r.timeframe_alignment.lower() or r.timeframe_alignment.startswith("5")


def test_macro_risk_penalises_confidence():
    base = dict(symbol="QQQ", price=500.0, alignment=_align("bullish", 5, 5, 5.0, 5.0),
                structure=_struct("uptrend"), rsi=60, above_vwap=True,
                relative_volume=1.6, atr_pct=1.2, regime="low_vol_trending")
    low = assemble_bias(BiasInputs(macro_risk="low", **base)).confidence
    high = assemble_bias(BiasInputs(macro_risk="very_high", **base)).confidence
    assert high < low
    assert "macro" in assemble_bias(BiasInputs(macro_risk="very_high", **base)).main_risk.lower()


def test_neutral_when_no_alignment():
    r = assemble_bias(BiasInputs(
        symbol="XYZ", price=100.0,
        alignment=_align("neutral", 1, 4, 0.0, 4.0),
        structure=_struct("range"), macro_risk="low",
    ))
    assert r.bias == "neutral"
    assert "confirmation" in r.main_risk.lower()


def test_result_is_evidence_not_recommendation():
    r = assemble_bias(BiasInputs(
        symbol="QQQ", price=500.0, alignment=_align("bullish", 5, 5, 5.0, 5.0),
        structure=_struct("uptrend"), macro_risk="low",
    ))
    d = r.to_dict()
    assert "not a buy/sell" in d["note"].lower()
    assert "probability" in d["note"].lower()
