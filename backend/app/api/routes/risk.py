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


# ── Scenario / stress analysis + parametric VaR (Phase 2 Batch 4) ──────────────────
def _trade_to_scenario_position(t, spot_iv: float = 0.25) -> dict:
    """
    Approximate a stored options trade as a scenario position. Uses the short
    strike as the spot proxy and a flat IV when live marks aren't available;
    refined automatically once market data is wired in.
    """
    qty = int(t.quantity or 1)
    # Credit spreads are net short the near leg → negative quantity.
    short = str(t.spread_type or "").startswith(("bull_put", "bear_call", "iron"))
    signed = -qty if short else qty
    strike = float(t.short_strike or 0) or 100.0
    from datetime import date as _date
    dte = max(0, (t.expiration - _date.today()).days) if t.expiration else 0
    return {
        "symbol": t.underlying, "kind": "option",
        "option_type": t.option_type or "put",
        "spot": strike, "strike": strike, "dte_days": dte,
        "iv": spot_iv, "r": 0.04, "quantity": signed, "multiplier": 100,
    }


@router.get("/scenarios")
async def get_scenarios():
    """Stress the open book under the standard shock set (crash, vol spike, …)."""
    from app.services.scenario_engine import run_all
    try:
        async with AsyncSessionLocal() as session:
            open_trades = (await session.execute(
                select(Trade).where(Trade.status == "open")
            )).scalars().all()
        positions = [_trade_to_scenario_position(t) for t in open_trades]
    except Exception as exc:
        return {"error": str(exc), "scenarios": [], "worst_scenario": None, "worst_pnl": 0.0}
    return run_all(positions, capital=settings.starting_capital)


@router.get("/var")
async def get_var(confidence: float = 0.95, horizon_days: int = 1):
    """Parametric (delta-vega-normal) portfolio VaR / Expected Shortfall."""
    from app.services.portfolio_risk_sim import portfolio_var

    net_delta = net_vega = 0.0
    vol = 0.18
    spot = 450.0
    try:
        from app.main import _greeks_tracker, _current_regime
        if _greeks_tracker:
            net_delta = _greeks_tracker.net_delta() * 100.0   # contract → share-delta
            net_vega = _greeks_tracker.net_vega() * 100.0
        feat = getattr(_current_regime, "features_used", None)
        if feat:
            vol = max(0.05, float(getattr(feat, "vix", 18.0)) / 100.0)
    except Exception:
        pass

    try:
        from app.broker.broker_factory import get_broker
        acct = await get_broker().get_account_summary()
        pv = float(acct.net_liquidation)
    except Exception:
        pv = settings.starting_capital

    return portfolio_var(net_delta, net_vega, spot, vol, pv,
                         confidence=confidence, horizon_days=horizon_days)


@router.get("/margin")
async def get_margin():
    """
    Margin utilization / buying-power-reduction status from broker figures.

    Returns the margin monitor's status (ok/warn/critical) plus the raw figures.
    `available: false` when the broker doesn't report margin (e.g. disconnected).
    """
    from app.services.margin_monitor import evaluate_margin

    try:
        from app.broker.broker_factory import get_broker
        acct = await get_broker().get_account_summary()
    except Exception as exc:
        return {"available": False, "reason": str(exc)}

    if acct.maintenance_margin is None:
        return {"available": False, "reason": "broker did not report margin figures"}

    status = evaluate_margin(
        net_liquidation=float(acct.net_liquidation or 0),
        maintenance_margin=float(acct.maintenance_margin or 0),
        excess_liquidity=float(acct.excess_liquidity or 0),
        buying_power=float(acct.buying_power or 0),
        init_margin=float(acct.init_margin or 0),
        warn_pct=settings.margin_warn_pct,
        critical_pct=settings.margin_critical_pct,
    )
    return {"available": True, **status.to_dict()}


@router.get("/reconciliation")
async def get_reconciliation():
    """
    Broker-vs-DB position reconciliation status (non-raising).

    Surfaces untracked broker positions (held at broker, no OlbosQuant record),
    DB phantoms (open in DB, not at broker), and quantity mismatches so the UI
    can flag a "needs reconcile" state without halting trading.
    """
    from app.broker.broker_factory import get_broker
    from app.services.position_reconciler import PositionReconciler

    res = await PositionReconciler(get_broker()).check()
    return {
        "clean":                 res.clean,
        "broker_position_count": res.broker_position_count,
        "db_open_trade_count":   res.db_open_trade_count,
        "untracked_at_broker":   res.untracked_at_broker,
        "phantom_in_db":         res.phantom_in_db,
        "warnings":              res.warnings,
        "checked_at":            res.checked_at.isoformat(),
    }
