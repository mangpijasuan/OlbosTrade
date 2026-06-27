"""
Income Matrix routes — Options-Matrix-Pro-style premium-income screener.

Scans watchlist option chains for the best cash-secured-put / covered-call
income setups (free yfinance snapshot, not a real-time feed).
"""
from fastapi import APIRouter, Query

from app.core.config import settings
from app.services.income_screener import scan_income_matrix

router = APIRouter()


@router.get("")
async def get_income_matrix(
    min_premium: float = Query(0.10, ge=0.0),
    min_prob_otm: float = Query(0.60, ge=0.0, le=1.0),
    top: int = Query(200, ge=1, le=500),
):
    """Best CSP / covered-call income setups across the watchlist, top yield first."""
    try:
        rows = await scan_income_matrix(
            settings.get_equity_watchlist(),
            min_premium=min_premium, min_prob_otm=min_prob_otm, top=top,
        )
        return {"count": len(rows), "results": rows, "source": "yfinance_income_matrix"}
    except Exception as exc:
        return {"count": 0, "results": [], "error": str(exc)}
