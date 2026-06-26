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


@router.get("/allocation")
async def portfolio_allocation(method: str = "blended"):
    """
    Target capital weights per strategy from the Dynamic Capital Allocation
    Engine, driven by each strategy's health (score/vol/expectancy) and the
    meta-strategy tilt (regime × health). The remainder is held as cash.
    """
    from app.api.routes.strategy import _evaluate_health
    from app.services.allocation_engine import (
        StrategyAlloc, AllocationConstraints, allocate, METHODS,
    )
    from app.services.meta_strategy import decide, tilts

    if method not in METHODS:
        return {"error": f"unknown method '{method}'", "methods": list(METHODS)}

    try:
        health = await _evaluate_health(min_sample=20)
    except Exception as exc:
        return {"error": str(exc), "weights": {}, "cash_weight": 1.0}

    from app.main import _current_regime
    regime = getattr(getattr(_current_regime, "regime", None), "value", None) or "unknown"
    tilt_map = tilts(decide(regime, [h.as_dict() for h in health]))

    inputs = [
        StrategyAlloc(
            strategy=h.strategy, score=h.score, volatility=h.volatility,
            expectancy=h.expectancy,
            tilt=tilt_map.get(h.strategy, 0.0),
        )
        for h in health
    ]
    result = allocate(inputs, method=method, constraints=AllocationConstraints())
    return {"regime": regime, **result.as_dict()}
