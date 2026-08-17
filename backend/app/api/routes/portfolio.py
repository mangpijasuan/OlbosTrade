"""Portfolio routes — heat, exposure and concentration over open positions."""
from __future__ import annotations

from fastapi import APIRouter

from app.services.account_state import get_account_value

router = APIRouter()


@router.get("/heat")
async def portfolio_heat():
    """Portfolio heat (% of capital at risk), exposures, and concentration flags."""
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.trade import Trade
    from app.services.portfolio_engine import compute_portfolio_risk, position_risk_dollars, sector_for

    account_value = await get_account_value()

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
                **compute_portfolio_risk([], account_value)}

    return compute_portfolio_risk(positions, account_value)


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


@router.get("/correlation")
async def portfolio_correlation():
    """
    Correlation clusters across open positions' underlyings — flags when
    distinct tickers move together enough to behave as one concentrated
    position (something the underlying/sector concentration flags on
    /heat can't see).
    """
    import asyncio

    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.main import _yf_bars
    from app.models.trade import Trade
    from app.services.portfolio_engine import (
        CORRELATION_THRESHOLD,
        align_price_series,
        cluster_concentration_flags,
        compute_correlation_clusters,
        position_risk_dollars,
    )

    account_value = await get_account_value()
    empty = {
        "status": "insufficient_data",
        "tickers": [],
        "correlation_matrix": None,
        "clusters": [],
        "concentration_flags": [],
        "excluded_symbols": [],
        "lookback_days": 60,
        "threshold": CORRELATION_THRESHOLD,
    }

    try:
        async with AsyncSessionLocal() as session:
            open_trades = (await session.execute(
                select(Trade).where(Trade.status == "open")
            )).scalars().all()
    except Exception as exc:
        return {**empty, "status": "error", "error": str(exc)}

    risk_by_underlying: dict[str, float] = {}
    for t in open_trades:
        risk_by_underlying[t.underlying] = risk_by_underlying.get(t.underlying, 0.0) + position_risk_dollars(t)

    tickers = sorted(risk_by_underlying.keys())
    if len(tickers) < 2:
        return {**empty, "reason": f"only {len(tickers)} distinct open underlying(s), need >= 2"}

    sem = asyncio.Semaphore(5)
    excluded_symbols: list[dict] = []

    async def _fetch(ticker: str):
        async with sem:
            try:
                bars = await _yf_bars(ticker, limit=60)
                return ticker, bars
            except Exception as exc:
                excluded_symbols.append({"ticker": ticker, "reason": f"fetch failed: {exc}"})
                return ticker, []

    fetched = await asyncio.gather(*(_fetch(t) for t in tickers))
    bars_by_ticker = {t: bars for t, bars in fetched if bars}

    aligned, align_excluded = align_price_series(bars_by_ticker)
    excluded_symbols.extend(align_excluded)

    if len(aligned) < 2:
        return {
            **empty,
            "reason": "insufficient overlapping price history across positions",
            "excluded_symbols": excluded_symbols,
        }

    clustered = compute_correlation_clusters(aligned)
    clusters, flags = cluster_concentration_flags(clustered["clusters"], risk_by_underlying, account_value)

    return {
        "status": "ok",
        "tickers": clustered["tickers"],
        "correlation_matrix": clustered["correlation_matrix"],
        "clusters": clusters,
        "concentration_flags": flags,
        "excluded_symbols": excluded_symbols,
        "lookback_days": 60,
        "threshold": CORRELATION_THRESHOLD,
    }
