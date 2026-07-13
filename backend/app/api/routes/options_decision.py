"""
Options Decision route — EV-ranked vertical-spread selection.

POST candidate spreads (+ direction/confidence) and get back the best strategy,
strike/expiry, POP/EV/RR/Kelly, a 0–100 trade score, and a fail-closed NO-TRADE
gate. Pure evaluation — candidates are supplied by the caller (the options scan
or a chain fetcher), so the endpoint stays deterministic and fast.
"""
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.options_decision_engine import evaluate_vertical, decide

router = APIRouter()


class SpreadCandidate(BaseModel):
    kind: str                      # bull_put | bear_call | bull_call | bear_put
    short_strike: float
    long_strike: float
    net_price: float               # credit received / debit paid (magnitude)


class DecisionRequest(BaseModel):
    spot: float
    iv: float                      # annualized implied vol (e.g. 0.20)
    dte: float
    direction: str                 # BULLISH | BEARISH | NEUTRAL
    confidence: float = 0.6
    candidates: list[SpreadCandidate]
    min_ev: float = 0.0
    min_pop: float = 0.55
    min_rr: float = 0.25
    min_confidence: float = 0.0


@router.post("/evaluate")
async def evaluate_decision(req: DecisionRequest):
    """Evaluate all supplied verticals and return the EV-ranked decision."""
    evaluated = []
    for c in req.candidates:
        try:
            evaluated.append(evaluate_vertical(
                kind=c.kind, spot=req.spot, short_strike=c.short_strike,
                long_strike=c.long_strike, net_price=c.net_price,
                dte=req.dte, iv=req.iv,
            ))
        except ValueError:
            continue   # skip unknown kinds rather than 500
    d = decide(
        evaluated, direction=req.direction.upper(), confidence=req.confidence,
        min_ev=req.min_ev, min_pop=req.min_pop, min_rr=req.min_rr,
        min_confidence=req.min_confidence,
    )
    return d.to_dict()
