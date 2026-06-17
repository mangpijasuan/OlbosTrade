"""
Trade Desk routes — execution mode + approval queue for Copilot/Autopilot.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import require_admin_api_key
from app.core.config import settings
from app.services.execution_mode import ExecutionMode, execution_mode_manager
from app.services.kill_switch import kill_switch_service

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Kill switch ────────────────────────────────────────────────────────────────
# Single source of truth: kill_switch_service (from services/kill_switch.py).
# _kill_switch is a fast thread-safe mirror so the hot path doesn't need an
# async call — it is synced from kill_switch_service on every engage/reset.
_kill_switch = threading.Event()


def _is_kill_switch_active() -> bool:
    """Check both the local event and the authoritative service."""
    return _kill_switch.is_set() or kill_switch_service.is_engaged

# ── In-memory pending approvals (Copilot mode) ────────────────────────────────
# Populated by main.py background scanner when mode == copilot
# { signal_id: { ...signal_data, "asset_type": "equity"|"options" } }
_pending_approvals: dict[str, dict] = {}
_execution_log:     list[dict]      = []   # history of all auto/manual executions


class SetExecutionModeRequest(BaseModel):
    mode: str   # manual | copilot | autopilot


class KillSwitchRequest(BaseModel):
    engaged: bool


class ManualTradeRequest(BaseModel):
    ticker:      str
    action:      str            # BUY | SELL
    shares:      int   = 1
    order_type:  str   = "market"   # market | limit
    limit_price: Optional[float] = None


# ── Kill switch endpoints ──────────────────────────────────────────────────────

@router.get("/kill-switch")
async def get_kill_switch():
    """Return current kill switch state (checks both local event and service)."""
    return {"engaged": _is_kill_switch_active()}


@router.post("/kill-switch", dependencies=[Depends(require_admin_api_key)])
async def set_kill_switch(body: KillSwitchRequest):
    """Engage or reset the kill switch — syncs both the service and the local event."""
    if body.engaged:
        _kill_switch.set()
        await kill_switch_service.engage("manual via trade-desk API")
        logger.warning("KILL SWITCH ENGAGED via API — all order submission halted")
    else:
        if not settings.kill_switch_reset_code:
            raise HTTPException(503, "KILL_SWITCH_RESET_CODE not configured")
        _kill_switch.clear()
        await kill_switch_service.reset(settings.kill_switch_reset_code)
        logger.info("Kill switch reset via API — order submission resumed")
    return {"engaged": _is_kill_switch_active()}


# ── Execution mode ─────────────────────────────────────────────────────────────

@router.get("/execution-mode")
async def get_execution_mode():
    return execution_mode_manager.summary()


@router.post("/execution-mode", dependencies=[Depends(require_admin_api_key)])
async def set_execution_mode(body: SetExecutionModeRequest):
    try:
        mode = ExecutionMode(body.mode)
    except ValueError:
        raise HTTPException(400, f"Invalid mode. Valid: manual, copilot, autopilot")
    return execution_mode_manager.set_mode(mode)


# ── Pending approvals (Copilot) ────────────────────────────────────────────────

@router.get("/pending")
async def get_pending():
    """List signals awaiting user approval in Copilot mode."""
    items = sorted(_pending_approvals.values(),
                   key=lambda x: x.get("queued_at", ""), reverse=True)
    return {
        "mode":    execution_mode_manager.mode.value,
        "pending": items,
        "count":   len(items),
    }


@router.post("/approve/{signal_id}", dependencies=[Depends(require_admin_api_key)])
async def approve_signal(signal_id: str):
    """User approves a pending signal → executes order."""
    if signal_id not in _pending_approvals:
        raise HTTPException(404, "Signal not found in pending queue")

    signal = _pending_approvals.pop(signal_id)
    result = await _execute_signal(signal, approved_by="user")
    _execution_log.insert(0, {**result, "signal_id": signal_id, "approved_by": "user"})
    del _execution_log[200:]
    return result


@router.post("/reject/{signal_id}", dependencies=[Depends(require_admin_api_key)])
async def reject_signal(signal_id: str):
    """User rejects a pending signal — no order sent."""
    if signal_id not in _pending_approvals:
        raise HTTPException(404, "Signal not found in pending queue")

    signal = _pending_approvals.pop(signal_id)
    entry = {
        "signal_id":   signal_id,
        "ticker":      signal.get("ticker"),
        "asset_type":  signal.get("asset_type", "equity"),
        "action":      signal.get("action"),
        "result":      "rejected",
        "rejected_at": datetime.now(timezone.utc).isoformat(),
        "rejected_by": "user",
    }
    _execution_log.insert(0, entry)
    del _execution_log[200:]
    return entry


# ── Manual trade ──────────────────────────────────────────────────────────────

@router.post("/manual-trade", dependencies=[Depends(require_admin_api_key)])
async def manual_trade(req: ManualTradeRequest):
    """Force a manual equity order — bypasses signal scoring and IV filters."""
    if _is_kill_switch_active():
        raise HTTPException(403, "Kill switch is engaged — reset it first")

    signal = {
        "id":         str(uuid.uuid4()),
        "ticker":     req.ticker.upper(),
        "action":     req.action.upper(),
        "asset_type": "equity",
        "trade_plan": {
            "shares":      req.shares,
            "entry_price": req.limit_price,
            "stop_price":  None,
            "target_price": None,
        },
        "manual":     True,
        "order_type": req.order_type,
    }

    try:
        from app.broker.broker_factory import get_broker
        broker = get_broker()
        result = await broker.place_equity_order(
            ticker=req.ticker.upper(),
            qty=req.shares,
            side=req.action.upper(),
            order_type=req.order_type,
            limit_price=req.limit_price,
        )
        entry = {
            "signal_id":    signal["id"],
            "ticker":       req.ticker.upper(),
            "asset_type":   "equity",
            "action":       req.action.upper(),
            "shares":       req.shares,
            "order_type":   req.order_type,
            "limit_price":  req.limit_price,
            "order_id":     result.order_id,
            "order_status": result.status,
            "result":       "submitted",
            "approved_by":  "manual",
            "executed_at":  datetime.now(timezone.utc).isoformat(),
        }
        _execution_log.insert(0, entry)
        del _execution_log[200:]
        return entry
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Execution log ──────────────────────────────────────────────────────────────

@router.get("/execution-log")
async def get_execution_log(limit: int = 50):
    return {"log": _execution_log[:limit], "total": len(_execution_log)}


# ── Internal execution helper ──────────────────────────────────────────────────

async def _execute_signal(signal: dict, approved_by: str = "autopilot") -> dict:
    """
    Execute a signal via IBKR broker.
    Works for both equity and options signals.
    Returns execution result dict.
    """
    # Yield to the event loop — gives kill switch and guardrail checks a
    # chance to fire if they were set on the same iteration.
    await asyncio.sleep(0)

    # Hard stop: kill switch takes absolute priority over everything.
    if _is_kill_switch_active():
        logger.warning(
            "Order blocked for %s — kill switch is engaged",
            signal.get("ticker", "?"),
        )
        return {
            "signal_id":  signal.get("id"),
            "ticker":     signal.get("ticker", ""),
            "asset_type": signal.get("asset_type", "equity"),
            "result":     "blocked",
            "reason":     "kill_switch",
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }

    asset_type = signal.get("asset_type", "equity")
    ticker     = signal.get("ticker", "")
    action     = signal.get("action", "")
    executed_at = datetime.now(timezone.utc).isoformat()

    # Block duplicate: skip if an open trade for this symbol already exists in DB
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.trade import Trade
        from sqlalchemy import select
        async with AsyncSessionLocal() as _db:
            existing = (await _db.execute(
                select(Trade.id).where(
                    Trade.underlying == ticker,
                    Trade.status == "open",
                )
            )).first()
        if existing:
            logger.info("Skipping %s — open trade already exists in DB", ticker)
            return {
                "signal_id":  signal.get("id"),
                "ticker":     ticker,
                "asset_type": asset_type,
                "result":     "skipped",
                "reason":     "already_open",
                "executed_at": executed_at,
            }
    except Exception as _dup_exc:
        logger.warning("Duplicate check failed for %s: %s", ticker, _dup_exc)

    try:
        from app.broker.broker_factory import get_broker
        broker = get_broker()

        if asset_type == "equity":
            trade_plan = signal.get("trade_plan", {})
            shares     = trade_plan.get("shares", 1)
            side       = action  # "BUY" or "SELL"

            result = await broker.place_equity_order(
                ticker=ticker,
                qty=shares,
                side=side,
                order_type="limit",
                limit_price=trade_plan.get("entry_price"),
                stop=trade_plan.get("stop_price"),
            )

            # Record to DB
            try:
                from app.services.trade_recorder import trade_recorder
                from datetime import date
                await trade_recorder.record_fill(
                    strategy="equity",
                    underlying=ticker,
                    option_type="equity",
                    short_strike=trade_plan.get("entry_price") or 0,
                    long_strike=trade_plan.get("stop_price") or 0,
                    expiration=date.today(),
                    quantity=shares,
                    entry_credit=trade_plan.get("entry_price") or 0,
                    signal_score=signal.get("signal_score", 0),
                    iv_rank=signal.get("iv_rank", 0),
                    regime=signal.get("regime", "unknown"),
                    trading_mode=approved_by,
                    dispatch_id=result.order_id or signal.get("id", ""),
                )
            except Exception as _rec_exc:
                logger.warning("Failed to record trade to DB: %s", _rec_exc)

            return {
                "signal_id":   signal.get("id"),
                "ticker":      ticker,
                "asset_type":  "equity",
                "action":      action,
                "shares":      shares,
                "entry_price": trade_plan.get("entry_price"),
                "stop_price":  trade_plan.get("stop_price"),
                "target_price": trade_plan.get("target_price"),
                "order_id":    result.order_id,
                "order_status": result.status,
                "result":      "submitted",
                "approved_by": approved_by,
                "executed_at": executed_at,
            }

        elif asset_type == "options":
            from app.broker.broker_interface import SpreadOrder, SpreadLeg
            from decimal import Decimal
            from datetime import date

            spread_data = signal.get("spread", {})
            expiry_str  = spread_data.get("expiration", "")
            short_str   = spread_data.get("short_strike", 0)
            long_str    = spread_data.get("long_strike", 0)
            opt_type    = spread_data.get("option_type", "put")
            credit      = spread_data.get("net_credit", 0)
            strategy    = signal.get("strategy", "bull_put_spread")

            expiry_date = date.fromisoformat(expiry_str) if expiry_str else date.today()

            # Short leg (sell) + Long leg (buy) for credit spread
            short_action = "SELL"
            long_action  = "BUY"
            if "bear_call" in strategy:
                opt_type = "call"

            legs = [
                SpreadLeg(symbol=ticker, expiration=expiry_date,
                          strike=Decimal(str(short_str)), option_type=opt_type,
                          action=short_action, quantity=1),
                SpreadLeg(symbol=ticker, expiration=expiry_date,
                          strike=Decimal(str(long_str)), option_type=opt_type,
                          action=long_action, quantity=1),
            ]
            from app.core.config import settings as _cfg
            # Limit price aggression: 1.0 = at mid (most fills), 0.90 = accept
            # 10% less credit (very aggressive fill-seeking).
            # LIMIT_PRICE_AGGRESSION in .env (default 1.0 = at mid).
            aggression = getattr(_cfg, "limit_price_aggression", 1.0)
            limit_px = Decimal(str(round(credit * aggression, 2)))
            order = SpreadOrder(
                strategy=strategy,
                underlying=ticker,
                legs=legs,
                limit_price=limit_px,
                time_in_force="DAY",
            )
            result = await broker.place_order(order)

            # Record to DB
            try:
                from app.services.trade_recorder import trade_recorder
                await trade_recorder.record_fill(
                    strategy=strategy,
                    underlying=ticker,
                    option_type=opt_type,
                    short_strike=float(short_str),
                    long_strike=float(long_str),
                    expiration=expiry_date,
                    quantity=1,
                    entry_credit=float(credit),
                    spread_width=abs(float(short_str) - float(long_str)),
                    signal_score=signal.get("signal_score", 0),
                    iv_rank=signal.get("iv_rank", 0),
                    regime=signal.get("regime", "unknown"),
                    trading_mode=approved_by,
                    dispatch_id=result.order_id or signal.get("id", ""),
                )
            except Exception as _rec_exc:
                logger.warning("Failed to record options trade to DB: %s", _rec_exc)

            return {
                "signal_id":    signal.get("id"),
                "ticker":       ticker,
                "asset_type":   "options",
                "strategy":     strategy,
                "short_strike": short_str,
                "long_strike":  long_str,
                "option_type":  opt_type,
                "expiration":   expiry_str,
                "net_credit":   credit,
                "order_id":     result.order_id,
                "order_status": result.status,
                "result":       "submitted",
                "approved_by":  approved_by,
                "executed_at":  executed_at,
            }

    except Exception as exc:
        return {
            "signal_id":  signal.get("id"),
            "ticker":     ticker,
            "asset_type": asset_type,
            "result":     "error",
            "error":      str(exc),
            "executed_at": executed_at,
        }


# ── Called by main.py background scanner ─────────────────────────────────────

async def handle_signal(signal: dict) -> None:
    """
    Route a generated signal based on current execution mode.
    Called from the background scanner in main.py after signal scoring.
    """
    mode = execution_mode_manager.mode

    if mode == ExecutionMode.MANUAL:
        return   # Signal already written to _recent_signals — nothing more to do

    elif mode == ExecutionMode.COPILOT:
        signal_id = signal.get("id", str(uuid.uuid4()))
        signal["queued_at"] = datetime.now(timezone.utc).isoformat()
        signal["status"]    = "pending_approval"
        _pending_approvals[signal_id] = signal

    elif mode == ExecutionMode.AUTOPILOT:
        # Check guardrails before executing — use real portfolio value from broker
        from app.services.guardrails import GuardrailEngine, PortfolioState
        from app.core.config import settings

        # Try to get live portfolio value; fall back to config
        current_value = settings.starting_capital
        try:
            from app.broker.broker_factory import get_broker
            _broker = get_broker()
            _acct = await _broker.get_account_summary()
            current_value = float(_acct.net_liquidation or settings.starting_capital)
        except Exception:
            pass

        # Query real P&L windows from DB for accurate guardrail enforcement
        daily_pnl = 0.0
        weekly_pnl = 0.0
        monthly_pnl = 0.0
        consecutive_losses = 0
        trades_today = 0
        try:
            from datetime import date, timedelta
            from sqlalchemy import select, func, and_
            from app.core.database import AsyncSessionLocal
            from app.models.trade import Trade
            today = date.today()
            week_start = today - timedelta(days=today.weekday())
            month_start = today.replace(day=1)

            async with AsyncSessionLocal() as _db:
                async def _sum_pnl(from_date):
                    result = await _db.execute(
                        select(func.coalesce(func.sum(Trade.pnl), 0)).where(
                            and_(
                                Trade.status == "closed",
                                func.date(Trade.exit_date) >= from_date,
                            )
                        )
                    )
                    return float(result.scalar() or 0.0)

                daily_pnl   = await _sum_pnl(today)
                weekly_pnl  = await _sum_pnl(week_start)
                monthly_pnl = await _sum_pnl(month_start)

                count_today = await _db.execute(
                    select(func.count(Trade.id)).where(
                        func.date(Trade.entry_date) == today
                    )
                )
                trades_today = int(count_today.scalar() or 0)

                recent = (await _db.execute(
                    select(Trade.pnl)
                    .where(Trade.status == "closed")
                    .order_by(Trade.exit_date.desc())
                    .limit(20)
                )).scalars().all()
                for pnl in recent:
                    if (pnl or 0) < 0:
                        consecutive_losses += 1
                    else:
                        break
        except Exception as exc:
            logger.warning("Autopilot guardrail DB query failed; using zero P&L windows: %s", exc)

        engine = GuardrailEngine()
        portfolio = PortfolioState(
            current_value=current_value,
            starting_capital=settings.starting_capital,
            daily_pnl=daily_pnl,
            weekly_pnl=weekly_pnl,
            monthly_pnl=monthly_pnl,
            consecutive_losses=consecutive_losses,
            trades_today=trades_today,
        )
        status = engine.check_all(portfolio)
        if not status.trading_allowed:
            signal["autopilot_blocked"] = status.reason
            logger.warning(
                "Autopilot blocked for %s: %s", signal.get("ticker"), status.reason
            )
            return

        # Final kill switch check after guardrail evaluation
        if _is_kill_switch_active():
            logger.warning(
                "Autopilot blocked for %s — kill switch engaged after guardrail check",
                signal.get("ticker"),
            )
            return

        result = await _execute_signal(signal, approved_by="autopilot")
        _execution_log.insert(0, result)
        del _execution_log[200:]
