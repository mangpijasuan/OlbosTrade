"""Test for the POST /api/options-decision/evaluate route."""

from __future__ import annotations

import pytest

from app.api.routes.options_decision import evaluate_decision, DecisionRequest, SpreadCandidate


@pytest.mark.asyncio
async def test_evaluate_route_returns_ranked_decision():
    req = DecisionRequest(
        spot=750, iv=0.20, dte=4, direction="bullish", confidence=0.7,
        candidates=[
            SpreadCandidate(kind="bull_put", short_strike=745, long_strike=740, net_price=1.50),
            SpreadCandidate(kind="butterfly", short_strike=1, long_strike=2, net_price=1),  # skipped
        ],
        min_pop=0.5,
    )
    out = await evaluate_decision(req)
    assert out["direction"] == "BULLISH"
    assert out["decision"] in ("TRADE", "NO_TRADE")
    assert isinstance(out["ranked"], list) and len(out["ranked"]) == 1  # butterfly skipped
    assert out["ranked"][0]["kind"] == "bull_put"


@pytest.mark.asyncio
async def test_evaluate_route_no_trade_on_empty_direction():
    req = DecisionRequest(
        spot=750, iv=0.20, dte=4, direction="NEUTRAL", confidence=0.9,
        candidates=[SpreadCandidate(kind="bull_put", short_strike=745, long_strike=740, net_price=1.5)],
    )
    out = await evaluate_decision(req)
    assert out["decision"] == "NO_TRADE"
