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


@router.get("/open-orders")
async def portfolio_open_orders():
    """Resting broker orders, and which open positions have no stop.

    Read-only: it reads the order book, it never places, modifies or cancels
    anything.

    The list itself is secondary. The number that matters is
    `positions_without_stop` — equity entries go in as brackets with a GTC
    stop child (see IBKRClient.place_equity_order), but positions the
    reconciler adopted from the broker never had a bracket, and `trades` has
    no stop column, so until now nothing could tell a protected position from
    an unprotected one.

    `source` is load-bearing. An empty order list means "no resting orders"
    only when source == "refreshed"; on a cache fall-back it may just mean the
    cache was never populated, and `unprotected_is_reliable` says so rather
    than letting an empty list read as a clean bill of health.
    """
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.trade import Trade
    from app.broker.broker_factory import get_broker
    from app.broker.ibkr_coordinator import Priority, ibkr_coordinator

    broker = get_broker()
    if not hasattr(broker, "get_open_orders"):
        return {"available": False,
                "reason": f"{type(broker).__name__} does not expose an order book"}

    try:
        result = await ibkr_coordinator.submit(
            Priority.P1, broker.get_open_orders,
            key="open_orders", req_type="OPEN_ORDERS", timeout=15.0,
        )
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

    orders = result.get("orders", [])
    source = result.get("source", "unknown")

    protected = {
        (o.get("symbol") or "").upper()
        for o in orders
        if o.get("is_protective") and (o.get("remaining") or 0) > 0
    }

    try:
        async with AsyncSessionLocal() as session:
            open_trades = (await session.execute(
                select(Trade).where(Trade.status == "open")
            )).scalars().all()
    except Exception as exc:
        return {"available": True, "source": source, "orders": orders,
                "positions_error": f"{type(exc).__name__}: {exc}"}

    unprotected = []
    for t in open_trades:
        sym = (t.underlying or "").upper()
        if sym and sym not in protected:
            unprotected.append({
                "ticker": sym,
                "quantity": t.quantity,
                "spread_type": t.spread_type,
                # Adopted positions never had a bracket submitted for them —
                # worth surfacing, because it explains the gap rather than
                # leaving it looking like a lost order.
                "adopted_from_broker": (t.strategy or "") == "adopted_untracked",
            })

    return {
        "available": True,
        "source": source,
        "unprotected_is_reliable": source == "refreshed",
        "order_count": len(orders),
        "protective_order_count": sum(1 for o in orders if o.get("is_protective")),
        "protected_tickers": sorted(protected),
        "open_position_count": len(open_trades),
        "positions_without_stop": unprotected,
        "orders": orders,
    }


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


@router.get("/rotation-performance")
async def portfolio_rotation_performance():
    """
    Rotation-performance ledger — aggregate stats on the closed side of
    every position_rotation.py rotation close. Reports honestly on
    whether closing that position was a good call in hindsight; does not
    attempt to compare against whatever new position it enabled (no
    structural link exists between a rotation close and the specific
    entry it freed a slot for).
    """
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.trade import Trade
    from app.services.rotation_ledger import compute_rotation_ledger_stats

    empty = {
        "status": "no_rotations_yet",
        "total": 0, "total_pnl": 0.0, "avg_pnl": None,
        "win_rate": None, "avg_hold_days": None,
        "by_regime": {}, "recent": [],
    }

    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(Trade).where(Trade.exit_reason == "position_rotation")
            )).scalars().all()
    except Exception as exc:
        return {**empty, "status": "error", "error": str(exc)}

    rotations: list[dict] = []
    for t in rows:
        # Skip closes with unknown P&L — counting them as $0 would pollute
        # win rate and total_pnl with a fabricated flat trade, matching
        # analytics.py's own convention for the same situation.
        if t.pnl is None:
            continue
        entry = t.entry_date.date() if t.entry_date else None
        exit_d = t.exit_date.date() if t.exit_date else None
        rotations.append({
            "trade_id": str(t.id),
            "ticker": t.underlying,
            "pnl": float(t.pnl),
            "regime": t.regime,
            "entry_date": str(entry) if entry else None,
            "exit_date": str(exit_d) if exit_d else None,
            "hold_days": (exit_d - entry).days if entry and exit_d else None,
            "exit_reason": t.exit_reason,
        })

    if not rotations:
        return empty

    return {"status": "ok", **compute_rotation_ledger_stats(rotations)}


@router.get("/rotation-activity")
async def portfolio_rotation_activity(limit: int = 20):
    """
    Rotation activity feed — a chronological read of what
    position_rotation.py actually closed and why (the ranking signals
    captured on every rotation receipt: quality_score, in_flagged_cluster,
    confidence, unrealized_pnl_at_decision). Complementary to
    /rotation-performance: that route reports financial outcome after the
    fact from Trade rows; this one reports the decision itself from
    ExecutionEvent, forward-looking rather than backward-looking. Does not
    attempt to show what new position a freed slot went to — no
    structural link exists between a rotation close and the entry it
    enabled (same known gap /rotation-performance already documents).
    """
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.execution_event import ExecutionEvent

    empty = {"status": "no_rotations_yet", "events": []}

    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(ExecutionEvent)
                .where(
                    ExecutionEvent.kind == "execution",
                    ExecutionEvent.payload["closed_by"].astext == "position_rotation",
                )
                .order_by(ExecutionEvent.created_at.desc())
                .limit(limit)
            )).scalars().all()
    except Exception as exc:
        return {**empty, "status": "error", "error": str(exc)}

    if not rows:
        return empty

    events = []
    for r in rows:
        p = r.payload or {}
        events.append({
            "id": str(r.id),
            "ticker": r.ticker,
            # close_equity_trade()'s receipt has no asset_type key at all
            # (only close_options_trade()'s does) — default to equity.
            "asset_type": p.get("asset_type") or "equity",
            "status": p.get("status"),
            "quality_score": p.get("quality_score"),
            "in_flagged_cluster": p.get("in_flagged_cluster"),
            "confidence": p.get("confidence"),
            "unrealized_pnl_at_decision": p.get("unrealized_pnl_at_decision"),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {"status": "ok", "events": events}
