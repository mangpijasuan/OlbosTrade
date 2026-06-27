"""
Options Flow routes — free "Unusual Options Activity" derived from yfinance.

A real-time OPRA flow tape needs a paid feed; this serves a periodic snapshot of
contracts with unusually high volume vs. open interest across the watchlist.
"""
from fastapi import APIRouter, Query

from app.core.config import settings
from app.services.unusual_activity import scan_unusual_activity, summarize

router = APIRouter()


@router.get("")
async def get_options_flow(
    min_volume: int = Query(200, ge=1),
    ratio: float = Query(2.0, ge=0.0),
    top: int = Query(150, ge=1, le=500),
):
    """Unusual options activity rows across the watchlist, newest premium first."""
    try:
        rows = await scan_unusual_activity(
            settings.get_equity_watchlist(),
            min_volume=min_volume, ratio=ratio, top=top,
        )
        return {"count": len(rows), "results": rows, "source": "yfinance_unusual_activity"}
    except Exception as exc:
        return {"count": 0, "results": [], "error": str(exc)}


@router.get("/summary")
async def get_options_flow_summary():
    """Call/put premium totals + net bullish ratio for the current unusual activity."""
    try:
        rows = await scan_unusual_activity(settings.get_equity_watchlist())
        return {"available": True, **summarize(rows)}
    except Exception as exc:
        return {"available": False, "error": str(exc)}
