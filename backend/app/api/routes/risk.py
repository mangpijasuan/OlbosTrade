"""
Risk monitoring routes.
FIX #11: Kill switch route now fully implemented — cancels orders, flattens positions.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import select, func, and_, case

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.trade import Trade
from app.models.risk_state import PortfolioSnapshot
from app.services.kill_switch import kill_switch_service


def _require_api_key(x_api_key: str = Header(default="")) -> None:
    if not settings.secret_key:
        raise HTTPException(status_code=503, detail="SECRET_KEY not configured")
    if x_api_key != settings.secret_key:
        raise HTTPException(status_code=403, detail="Invalid API key")

router = APIRouter()


class KillSwitchResetRequest(BaseModel):
    authorization_code: str


@router.get("/portfolio-state")
async def get_portfolio_state():
    """
    Real portfolio state: account value from broker + guardrail metrics from DB.
    """
    try:
        from app.broker.broker_factory import get_broker
        broker = get_broker()
        acct   = await broker.get_account_summary()
        acct_value    = float(acct.net_liquidation)
        buying_power  = float(acct.buying_power)
        cash          = float(acct.cash_balance)
    except Exception as exc:
        acct_value   = settings.starting_capital
        buying_power = settings.starting_capital
        cash         = settings.starting_capital
        broker_error = str(exc)
    else:
        broker_error = None

    try:
        today = date.today()
        week_start  = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)

        async with AsyncSessionLocal() as session:
            def _pnl_window(from_date: date):
                return select(func.coalesce(func.sum(Trade.pnl), 0)).where(
                    and_(Trade.status == "closed", func.date(Trade.exit_date) >= from_date)
                )

            daily_pnl   = float((await session.execute(_pnl_window(today))).scalar() or 0)
            weekly_pnl  = float((await session.execute(_pnl_window(week_start))).scalar() or 0)
            monthly_pnl = float((await session.execute(_pnl_window(month_start))).scalar() or 0)

            trades_today = int((await session.execute(
                select(func.count(Trade.id)).where(
                    and_(Trade.status == "closed", func.date(Trade.exit_date) == today)
                )
            )).scalar() or 0)

            open_count = int((await session.execute(
                select(func.count(Trade.id)).where(Trade.status == "open")
            )).scalar() or 0)

            # Consecutive losses — count backwards from most recent closed trade
            recent = (await session.execute(
                select(Trade.pnl).where(Trade.status == "closed")
                .order_by(Trade.exit_date.desc()).limit(20)
            )).scalars().all()
            consecutive_losses = 0
            for p in recent:
                if (p or 0) < 0:
                    consecutive_losses += 1
                else:
                    break

        daily_loss_pct   = abs(daily_pnl)   / settings.starting_capital if daily_pnl   < 0 else 0.0
        weekly_loss_pct  = abs(weekly_pnl)  / settings.starting_capital if weekly_pnl  < 0 else 0.0
        monthly_loss_pct = abs(monthly_pnl) / settings.starting_capital if monthly_pnl < 0 else 0.0
        total_pnl        = acct_value - settings.starting_capital

        return {
            "state": {
                "account_value":       acct_value,
                "cash":                cash,
                "buying_power":        buying_power,
                "starting_capital":    settings.starting_capital,
                "total_pnl":           round(total_pnl, 2),
                "return_pct":          round(total_pnl / settings.starting_capital * 100, 2),
                "daily_pnl":           round(daily_pnl, 2),
                "weekly_pnl":          round(weekly_pnl, 2),
                "monthly_pnl":         round(monthly_pnl, 2),
                "daily_loss_pct":      round(daily_loss_pct, 4),
                "weekly_loss_pct":     round(weekly_loss_pct, 4),
                "monthly_loss_pct":    round(monthly_loss_pct, 4),
                "open_positions":      open_count,
                "trades_today":        trades_today,
                "consecutive_losses":  consecutive_losses,
                "max_daily_loss_pct":  settings.max_daily_loss_pct,
                "max_weekly_loss_pct": settings.max_weekly_loss_pct,
                "capital_pct_remaining": round(acct_value / settings.starting_capital, 4),
                **({"broker_error": broker_error} if broker_error else {}),
            }
        }
    except Exception as exc:
        return {"state": {"error": str(exc)}}


@router.get("/daily-pnl")
async def get_daily_pnl():
    """Today's realised P&L from closed trades."""
    try:
        async with AsyncSessionLocal() as session:
            today = date.today()
            daily_pnl = float((await session.execute(
                select(func.coalesce(func.sum(Trade.pnl), 0)).where(
                    and_(Trade.status == "closed", func.date(Trade.exit_date) == today)
                )
            )).scalar() or 0)

        daily_pnl_pct = round(daily_pnl / settings.starting_capital * 100, 4)
        return {
            "daily_pnl":     round(daily_pnl, 2),
            "daily_pnl_pct": daily_pnl_pct,
            "date":          today.isoformat(),
        }
    except Exception as exc:
        return {"daily_pnl": 0, "daily_pnl_pct": 0, "error": str(exc)}


@router.get("/approval/{trade_id}")
async def get_trade_approval(trade_id: str):
    """Check risk approval status for a trade."""
    try:
        from app.models.position import Position
        import uuid as _uuid
        async with AsyncSessionLocal() as session:
            pos = await session.get(Position, _uuid.UUID(trade_id))
        if pos:
            return {
                "trade_id": trade_id,
                "approved": pos.risk_approved,
                "flags":    pos.risk_flags or {},
            }
        return {"trade_id": trade_id, "approved": False, "reason": "not found"}
    except Exception as exc:
        return {"trade_id": trade_id, "approved": False, "error": str(exc)}


@router.get("/kill-switch/status")
async def get_kill_switch_status():
    """Returns current kill switch state."""
    return kill_switch_service.status


@router.post("/kill-switch/trigger")
async def trigger_kill_switch(
    reason: str = "manual",
    x_api_key: str = Header(default=""),
):
    """
    FIX #11: Fully implemented kill switch.
    Cancels all open orders, flattens all positions, pauses scheduler.
    This is irreversible until manually reset via /kill-switch/reset.
    Requires X-Api-Key header matching SECRET_KEY.
    """
    _require_api_key(x_api_key)
    if kill_switch_service.is_engaged:
        return {
            "status": "already_engaged",
            "detail": kill_switch_service.status,
        }

    result = await kill_switch_service.engage(reason=reason)

    if result.get("errors"):
        # Kill switch ran but had partial errors — still engaged, log for review
        raise HTTPException(
            status_code=207,  # Multi-status
            detail={
                "message": "Kill switch engaged with errors — manual review required",
                "result": result,
            },
        )

    return {
        "status": "engaged",
        "message": "Kill switch engaged. All orders cancelled and positions flattened.",
        "result": result,
    }


@router.post("/kill-switch/reset")
async def reset_kill_switch(body: KillSwitchResetRequest):
    """
    Reset kill switch after manual review.
    Requires authorization_code='OLBOSQUANT_MANUAL_RESET' to prevent accidents.
    """
    result = await kill_switch_service.reset(body.authorization_code)
    if not result.get("reset"):
        raise HTTPException(status_code=403, detail=result)
    return result
