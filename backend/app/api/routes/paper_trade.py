"""
Paper trading routes — wired to live broker positions + DB trade history.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Query
from sqlalchemy import select, func, and_, case

from app.broker.broker_factory import get_broker
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.trade import Trade

router = APIRouter()


# ── Portfolio summary ─────────────────────────────────────────────────────────

@router.get("/portfolio")
async def get_portfolio():
    """Live account summary from broker merged with DB P&L stats."""
    broker_data: dict = {}
    try:
        broker = get_broker()
        acct = await broker.get_account_summary()
        broker_data = {
            "account_value": float(acct.net_liquidation),
            "cash":          float(acct.cash_balance),
            "buying_power":  float(acct.buying_power),
        }
    except Exception as exc:
        broker_data = {"broker_error": str(exc)}

    try:
        async with AsyncSessionLocal() as session:
            # Only count closes with a KNOWN P&L. Trades auto-closed without a
            # reliable broker exit price are stored with pnl=NULL — including them
            # in the denominator would understate the win rate (a NULL is never a
            # win) and misrepresent total trades.
            stats = (await session.execute(
                select(
                    func.count(Trade.id).label("count"),
                    func.coalesce(func.sum(Trade.pnl), 0).label("total_pnl"),
                    func.coalesce(func.sum(case((Trade.pnl > 0, 1), else_=0)), 0).label("wins"),
                ).where(Trade.status == "closed", Trade.pnl.isnot(None))
            )).one()

            today = date.today()
            trades_today = (await session.execute(
                select(func.count(Trade.id)).where(
                    and_(Trade.status == "closed", func.date(Trade.exit_date) == today)
                )
            )).scalar() or 0

            open_count = (await session.execute(
                select(func.count(Trade.id)).where(Trade.status == "open")
            )).scalar() or 0

        total_trades = int(stats.count or 0)
        total_pnl    = float(stats.total_pnl or 0)
        wins         = int(stats.wins or 0)
        win_rate     = round(wins / total_trades, 3) if total_trades > 0 else 0.0
        acct_value   = broker_data.get("account_value", settings.starting_capital + total_pnl)

        return {"portfolio": {
            **broker_data,
            "total_pnl":        total_pnl,
            "total_trades":     total_trades,
            "win_rate":         win_rate,
            "open_positions":   open_count,
            "trades_today":     trades_today,
            "starting_capital": settings.starting_capital,
            "return_pct":       round((acct_value - settings.starting_capital) / settings.starting_capital * 100, 2),
        }}
    except Exception as exc:
        return {"portfolio": {**broker_data, "db_error": str(exc)}}


# ── Live positions ─────────────────────────────────────────────────────────────

@router.get("/positions")
async def get_positions():
    """Live broker positions merged with DB trade metadata."""
    try:
        broker = get_broker()
        broker_positions = await broker.get_positions()
    except Exception as exc:
        broker_positions = []
        broker_err = str(exc)
    else:
        broker_err = None

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Trade).where(Trade.status == "open"))
            db_trades = {t.underlying: t for t in result.scalars().all()}
    except Exception:
        db_trades = {}

    # Fetch current prices for all symbols via yfinance
    import asyncio, yfinance as yf
    symbols = list({getattr(p, "symbol", "") for p in broker_positions if getattr(p, "symbol", "")})
    price_map: dict[str, float] = {}
    if symbols:
        def _fetch_prices():
            try:
                tickers = yf.Tickers(" ".join(symbols))
                for sym in symbols:
                    try:
                        hist = tickers.tickers[sym].history(period="1d")
                        if not hist.empty:
                            price_map[sym] = float(hist["Close"].iloc[-1])
                    except Exception:
                        pass
            except Exception:
                pass
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _fetch_prices)

    positions = []
    seen = set()

    for pos in broker_positions:
        sym = getattr(pos, "symbol", str(pos))
        underlying = getattr(pos, "underlying", sym)
        seen.add(sym)
        db = db_trades.get(underlying)
        qty      = getattr(pos, "quantity", 0)
        avg_cost = float(getattr(pos, "avg_cost", 0) or 0)
        cur_price = price_map.get(sym)
        if cur_price is not None and avg_cost > 0:
            market_value   = round(cur_price * qty, 2)
            unrealized_pnl = round((cur_price - avg_cost) * qty, 2)
        else:
            market_value   = None
            unrealized_pnl = None
        positions.append({
            "symbol":         sym,
            "quantity":       qty,
            "avg_cost":       avg_cost,
            "current_price":  cur_price,
            "market_value":   market_value,
            "unrealized_pnl": unrealized_pnl,
            "strategy":       db.strategy if db else "unknown",
            "entry_date":     db.entry_date.isoformat() if db and db.entry_date else None,
            # A broker position with no matching DB open trade is "untracked" —
            # OlbosTrade did not open it (e.g. pre-existing holdings in a shared
            # paper account). The reconciler flags these as ghost positions; the
            # UI must not present them as OlbosTrade's managed trades or P&L.
            "tracked":        db is not None,
        })

    # Add any DB-open trades not in broker positions (may be paper-only)
    for sym, t in db_trades.items():
        if sym not in seen:
            positions.append({
                "symbol":          sym,
                "strategy":        t.strategy,
                "entry_date":      t.entry_date.isoformat() if t.entry_date else None,
                "hold_days":       max((date.today() - t.entry_date.date()).days, 0) if t.entry_date else None,
                "trading_mode":    t.trading_mode_at_entry,
                "credit_received": float(t.credit_received or 0),
                "mfe_pnl":         float(t.mfe_pnl or 0),
                "mae_pnl":         float(t.mae_pnl or 0),
                "source":          "db_only",
                "tracked":         True,
            })

    tracked_count = sum(1 for p in positions if p.get("tracked"))
    return {
        "positions": positions,
        "tracked_count": tracked_count,
        "untracked_count": len(positions) - tracked_count,
        **({"broker_error": broker_err} if broker_err else {}),
    }


# ── Trade history ──────────────────────────────────────────────────────────────

@router.get("/history")
async def get_trade_history(
    limit:  int = Query(50, le=500),
    offset: int = Query(0),
    status: Optional[str] = Query(None, description="open | closed | all"),
):
    """Trade history from DB, newest first."""
    try:
        async with AsyncSessionLocal() as session:
            q = select(Trade).order_by(Trade.entry_date.desc()).offset(offset).limit(limit)
            if status and status != "all":
                q = q.where(Trade.status == status)

            trades = (await session.execute(q)).scalars().all()

            count_q = select(func.count(Trade.id))
            if status and status != "all":
                count_q = count_q.where(Trade.status == status)
            total = (await session.execute(count_q)).scalar() or 0

        return {
            "trades": [
                {
                    "id":              str(t.id),
                    "strategy":        t.strategy,
                    "underlying":      t.underlying,
                    "status":          t.status,
                    "entry_date":      t.entry_date.isoformat() if t.entry_date else None,
                    "exit_date":       t.exit_date.isoformat() if t.exit_date else None,
                    "expiration":      t.expiration.isoformat() if t.expiration else None,
                    "short_strike":    float(t.short_strike),
                    "long_strike":     float(t.long_strike),
                    "quantity":        int(getattr(t, "quantity", None) or 0),
                    "credit_received": float(t.credit_received or 0),
                    "cost_to_close":   float(t.cost_to_close or 0),
                    "pnl":             float(t.pnl or 0),
                    "pnl_pct":         float(t.pnl_pct or 0),
                    "mfe":             float(t.mfe) if t.mfe is not None else None,
                    "mae":             float(t.mae) if t.mae is not None else None,
                    "exit_reason":     t.exit_reason,
                    "signal_score":    float(t.signal_score or 0),
                    "hold_days":       max(((t.exit_date or date.today()) - t.entry_date).days, 0) if t.entry_date else None,
                    "trading_mode":    getattr(t, "trading_mode_at_entry", None),
                }
                for t in trades
            ],
            "total":  total,
            "offset": offset,
            "limit":  limit,
        }
    except Exception as exc:
        return {"trades": [], "total": 0, "error": str(exc)}


# ── Strategy toggle ────────────────────────────────────────────────────────────

@router.post("/toggle/{strategy}")
async def toggle_strategy(strategy: str):
    return {
        "strategy": strategy,
        "toggled":  True,
        "message":  "Use /api/mode/set to change active trading mode and allowed strategies.",
    }


# ── Greeks summary ────────────────────────────────────────────────────────────

@router.get("/greeks-summary")
async def get_greeks_summary():
    """Portfolio Greeks from the live PortfolioGreeksTracker."""
    try:
        from app.main import _greeks_tracker
        if _greeks_tracker is None:
            return {"net_delta": 0.0, "net_theta": 0.0, "net_vega": 0.0, "net_gamma": 0.0}
        snap = _greeks_tracker.snapshot()
        return {
            "net_delta":     snap.get("net_delta", 0.0),
            "net_theta":     snap.get("net_theta", 0.0),
            "net_vega":      snap.get("net_vega",  0.0),
            "net_gamma":     0.0,
            "needs_hedge":   snap.get("needs_hedge", False),
            "delta_neutral": snap.get("is_delta_neutral", snap.get("delta_neutral", False)),
            "position_count": snap.get("total_position_count", 0),
        }
    except Exception as exc:
        return {"net_delta": 0.0, "net_theta": 0.0, "net_vega": 0.0, "net_gamma": 0.0, "error": str(exc)}
