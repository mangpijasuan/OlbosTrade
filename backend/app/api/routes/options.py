"""Options analytics routes — on-demand spread intelligence for the UI."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.options_intelligence import analyze_spread

router = APIRouter()


class SpreadAnalyzeRequest(BaseModel):
    spot: float
    short_strike: float
    long_strike: float
    option_type: str = "put"        # put = bull put | call = bear call
    dte: float = 30
    iv: float = 0.20
    credit_per_share: float = 0.60
    r: float = 0.05




@router.post("/analyze")
async def analyze(req: SpreadAnalyzeRequest):
    """Return POP / prob-touch / expected move / Greeks / EV / Kelly for a spread."""
    try:
        intel = analyze_spread(
            spot=req.spot, short_strike=req.short_strike, long_strike=req.long_strike,
            option_type=req.option_type, dte=req.dte, iv=req.iv,
            credit_per_share=req.credit_per_share, r=req.r,
        )
        return intel.as_dict()
    except ValueError as exc:
        return {"error": str(exc)}


@router.post("/scan")
async def scan_options_spreads(
    tickers: list[str] = None,
    strategy: str = "bull_put_spread",
    limit: int = 10,
):
    """
    A-grade multi-ticker options scan with live chain pricing + entry ladder logic.

    Ranks spreads by Expected Value (EV) with:
    - Live IBKR chain pricing (fallback: yfinance → Black-Scholes)
    - Entry ladder logic (kelly-scaled tranches)
    - IV rank + skew adjustments
    - NO-TRADE gates (kill switch, market hours)

    Returns high-EV candidates ready for autopilot or manual execution.
    """
    from app.services.options_scan_engine import scan_options

    if tickers is None:
        tickers = ["SPY", "ES", "QQQ"]

    result = await scan_options(
        tickers=tickers,
        strategy=strategy,
        limit=limit,
        base_quantity=1,
    )

    return {
        "scanned": len(result.tickers_scanned or []),
        "candidates": [c.as_dict() for c in result.candidates],
        "gate_blocked": result.gate_blocked,
        "gate_reason": result.gate_reason,
        "spot": result.spot,
        "vix_estimate": result.vix_estimate,
        "realized_vol": result.realized_vol,
        "iv_rank": result.iv_rank,
        "error": result.error,
        "tickers_scanned": result.tickers_scanned or [],
    }
