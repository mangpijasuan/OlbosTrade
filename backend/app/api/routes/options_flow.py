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


@router.get("/recommendations")
async def get_flow_recommendations(
    min_vol_oi: float = Query(5.0, ge=0.0),
    max_dte: int = Query(4, ge=0),
    min_cluster_premium: float = Query(5_000_000.0, ge=0.0),
    require_confluence: bool = Query(False),
    top: int = Query(50, ge=1, le=200),
):
    """
    Structured options Setup Recommendations from Unusual Options Activity +
    Live Signals confluence. Defaults follow the institutional-flow spec
    (vol/OI > 5, DTE ≤ 4, cluster premium ≥ $5M) — lower the thresholds for the
    free yfinance snapshot, which rarely shows $5M single-strike prints.
    """
    from app.services.flow_recommender import generate_recommendations
    try:
        recs = await generate_recommendations(
            min_vol_oi=min_vol_oi, max_dte=max_dte,
            min_cluster_premium=min_cluster_premium,
            require_confluence=require_confluence, top=top,
        )
        return {"count": len(recs), "recommendations": recs}
    except Exception as exc:
        return {"count": 0, "recommendations": [], "error": str(exc)}
