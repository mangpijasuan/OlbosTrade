"""Portfolio routes — heat, exposure and concentration over open positions."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/heat")
async def portfolio_heat():
    """Portfolio heat (% of capital at risk), exposures, and concentration flags."""
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.trade import Trade
    from app.services.portfolio_engine import compute_portfolio_risk, position_risk_dollars, sector_for

    positions: list[dict] = []
    try:
        async with AsyncSessionLocal() as session:
            open_trades = (await session.execute(
                select(Trade).where(Trade.status == "open")
            )).scalars().all()
        for t in open_trades:
            positions.append({
                "underlying": t.underlying,
                "risk_dollars": position_risk_dollars(t),
                "sector": sector_for(t.underlying),
            })
    except Exception as exc:
        return {"error": str(exc),
                **compute_portfolio_risk([], settings.starting_capital)}

    return compute_portfolio_risk(positions, settings.starting_capital)
