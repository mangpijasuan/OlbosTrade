"""
Options Flow API routes (Options Intelligence module).

  GET  /api/options-flow            paginated flow records (filterable)
  GET  /api/options-flow/summary    per-ticker bullish/bearish, premium, sweeps
  WS   /api/options-flow/ws         live stream of the options_flow_live channel

All endpoints read the existing ``options_flow`` table / Redis channel. They
return empty/zeroed results (not errors) when no flow has been ingested yet, so
the UI works even while the ingest service is idle.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.redis import subscribe_json
from app.models.options_flow import OptionsFlow
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/snapshot")
async def refresh_snapshot():
    """Run the free yfinance unusual-activity snapshot now and return the count."""
    from app.services.options_flow_snapshot import run_snapshot
    count = await run_snapshot()
    return {"refreshed": True, "rows": count, "source": "yfinance-snapshot"}


def _serialize(row: OptionsFlow) -> dict:
    return {
        "id": row.id,
        "ticker": row.ticker,
        "strike": float(row.strike),
        "expiry": row.expiry.isoformat(),
        "right": row.right,
        "exchange": row.exchange,
        "timestamp": row.timestamp.isoformat(),
        "premium": float(row.premium),
        "size": row.size,
        "trade_type": row.trade_type,
        "sentiment": row.sentiment,
        "iv": float(row.iv) if row.iv is not None else None,
        "delta": float(row.delta) if row.delta is not None else None,
        "dte": row.dte,
        "relative_volume": float(row.relative_volume)
        if row.relative_volume is not None else None,
        "sweep_confirmed": row.sweep_confirmed,
        "large_sweep": row.large_sweep,
    }


@router.get("")
async def get_options_flow(
    ticker: Optional[str] = Query(None),
    right: str = Query("all", pattern="^(C|P|all)$"),
    min_premium: Optional[float] = Query(None, ge=0),
    trade_type: Optional[str] = Query(None, pattern="^(sweep|block|single)$"),
    sentiment: Optional[str] = Query(None, pattern="^(bullish|bearish|neutral)$"),
    max_dte: Optional[int] = Query(None, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    """Paginated, filterable list of options-flow records (newest first)."""
    try:
        stmt = select(OptionsFlow)
        if ticker and ticker.lower() != "all":
            stmt = stmt.where(OptionsFlow.ticker == ticker.upper())
        if right in ("C", "P"):
            stmt = stmt.where(OptionsFlow.right == right)
        if min_premium is not None:
            stmt = stmt.where(OptionsFlow.premium >= min_premium)
        if trade_type:
            stmt = stmt.where(OptionsFlow.trade_type == trade_type)
        if sentiment:
            stmt = stmt.where(OptionsFlow.sentiment == sentiment)
        if max_dte is not None:
            stmt = stmt.where(OptionsFlow.dte <= max_dte)
        stmt = stmt.order_by(OptionsFlow.timestamp.desc()).limit(limit)

        async with AsyncSessionLocal() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return {"count": len(rows), "results": [_serialize(r) for r in rows]}
    except Exception as exc:
        logger.error("get_options_flow failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to query options flow")


@router.get("/summary")
async def get_options_flow_summary():
    """Per-ticker bullish/bearish ratio, total premium today, large-sweep count."""
    try:
        start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        async with AsyncSessionLocal() as session:
            # premium split by sentiment per ticker (today)
            rows = (await session.execute(
                select(
                    OptionsFlow.ticker,
                    OptionsFlow.sentiment,
                    func.sum(OptionsFlow.premium),
                    func.count(OptionsFlow.id),
                ).where(OptionsFlow.timestamp >= start)
                .group_by(OptionsFlow.ticker, OptionsFlow.sentiment)
            )).all()

            large_rows = (await session.execute(
                select(OptionsFlow.ticker, func.count(OptionsFlow.id))
                .where(OptionsFlow.timestamp >= start, OptionsFlow.large_sweep.is_(True))
                .group_by(OptionsFlow.ticker)
            )).all()

            # most active strike per ticker today (by total premium)
            active_rows = (await session.execute(
                select(
                    OptionsFlow.ticker,
                    OptionsFlow.strike,
                    OptionsFlow.right,
                    func.sum(OptionsFlow.premium).label("p"),
                ).where(OptionsFlow.timestamp >= start)
                .group_by(OptionsFlow.ticker, OptionsFlow.strike, OptionsFlow.right)
                .order_by(func.sum(OptionsFlow.premium).desc())
            )).all()

        per_ticker: dict[str, dict] = {}
        for tkr, sent, premium, cnt in rows:
            d = per_ticker.setdefault(tkr, {
                "ticker": tkr, "bullish_premium": 0.0, "bearish_premium": 0.0,
                "neutral_premium": 0.0, "total_premium": 0.0, "trade_count": 0,
                "large_sweep_count": 0, "most_active_strike": None,
            })
            d[f"{sent}_premium"] = float(premium or 0)
            d["total_premium"] += float(premium or 0)
            d["trade_count"] += int(cnt or 0)

        for tkr, cnt in large_rows:
            per_ticker.setdefault(tkr, {
                "ticker": tkr, "bullish_premium": 0.0, "bearish_premium": 0.0,
                "neutral_premium": 0.0, "total_premium": 0.0, "trade_count": 0,
                "large_sweep_count": 0, "most_active_strike": None,
            })["large_sweep_count"] = int(cnt or 0)

        seen_active: set[str] = set()
        for tkr, strike, rgt, _p in active_rows:
            if tkr in per_ticker and tkr not in seen_active:
                per_ticker[tkr]["most_active_strike"] = f"{float(strike):g}{rgt}"
                seen_active.add(tkr)

        for d in per_ticker.values():
            bull, bear = d["bullish_premium"], d["bearish_premium"]
            denom = bull + bear
            d["bullish_ratio"] = round(bull / denom, 4) if denom > 0 else 0.5

        total_premium = sum(d["total_premium"] for d in per_ticker.values())
        total_large = sum(d["large_sweep_count"] for d in per_ticker.values())
        most_active = max(
            per_ticker.values(), key=lambda d: d["total_premium"], default=None
        )

        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "total_premium_today": round(total_premium, 2),
            "large_sweep_count_today": total_large,
            "most_active_ticker": most_active["ticker"] if most_active else None,
            "by_ticker": list(per_ticker.values()),
        }
    except Exception as exc:
        logger.error("get_options_flow_summary failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to build flow summary")


@router.websocket("/ws")
async def options_flow_ws(websocket: WebSocket):
    """
    Stream the options_flow_live channel to a connected client.

    Optional filter query params (same names as GET): ticker, right,
    min_premium, trade_type, sentiment, max_dte. Filtering is applied
    server-side before fanout.
    """
    await websocket.accept()
    qp = websocket.query_params
    f_ticker = (qp.get("ticker") or "all").upper()
    f_right = qp.get("right", "all")
    f_trade_type = qp.get("trade_type")
    f_sentiment = qp.get("sentiment")
    try:
        f_min_premium = float(qp.get("min_premium")) if qp.get("min_premium") else None
    except ValueError:
        f_min_premium = None
    try:
        f_max_dte = int(qp.get("max_dte")) if qp.get("max_dte") else None
    except ValueError:
        f_max_dte = None

    def _passes(tick: dict) -> bool:
        if f_ticker != "ALL" and tick.get("ticker") != f_ticker:
            return False
        if f_right in ("C", "P") and tick.get("right") != f_right:
            return False
        if f_min_premium is not None and (tick.get("premium") or 0) < f_min_premium:
            return False
        if f_trade_type and tick.get("trade_type") != f_trade_type:
            return False
        if f_sentiment and tick.get("sentiment") != f_sentiment:
            return False
        if f_max_dte is not None and (tick.get("dte") or 0) > f_max_dte:
            return False
        return True

    try:
        async for tick in subscribe_json(settings.options_flow_channel):
            if _passes(tick):
                await websocket.send_json(tick)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("Options flow WS closed: %s", exc)
        try:
            await websocket.close()
        except Exception:
            pass
