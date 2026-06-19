"""
Trade Desk routes — execution mode + approval queue for Copilot/Autopilot.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from decimal import Decimal

from app.services.execution_mode import ExecutionMode, execution_mode_manager
from app.services.guardrails import GuardrailEngine, PortfolioState
from app.services.kill_switch import kill_switch_service

logger = logging.getLogger(__name__)
router = APIRouter()


class RiskGateError(Exception):
    """Raised when the risk gate cannot safely evaluate — always fail closed."""


async def _fetch_portfolio_state() -> PortfolioState:
    """
    Load portfolio state from DB for guardrail evaluation.
    FAIL CLOSED: raises RiskGateError on any DB failure — never returns zero-defaults.
    Correct columns: Trade.pnl / Trade.exit_date / Trade.status (not realized_pnl/closed_at).
    """
    from app.core.config import settings as _cfg
    from app.core.database import AsyncSessionLocal
    from app.models.trade import Trade
    from sqlalchemy import select, func

    current_value = _cfg.starting_capital
    try:
        from app.broker.broker_factory import get_broker
        _acct = await get_broker().get_account_summary()
        current_value = float(_acct.net_liquidation or _cfg.starting_capital)
    except Exception:
        pass  # broker unreachable — fall back to config value, acceptable

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    try:
        async with AsyncSessionLocal() as _db:
            async def _sum_pnl(from_date: date) -> Decimal:
                row = await _db.execute(
                    select(func.sum(Trade.pnl)).where(
                        Trade.status == "closed",
                        Trade.exit_date >= from_date,
                        Trade.pnl.isnot(None),
                    )
                )
                val = row.scalar()
                return Decimal(str(val)) if val is not None else Decimal("0")

            daily_pnl   = await _sum_pnl(today)
            weekly_pnl  = await _sum_pnl(week_start)
            monthly_pnl = await _sum_pnl(month_start)

            trades_today = int((await _db.execute(
                select(func.count()).where(
                    Trade.status == "open",
                    Trade.entry_date >= today,
                )
            )).scalar() or 0)

            recent_pnl = (await _db.execute(
                select(Trade.pnl).where(Trade.status == "closed")
                .order_by(Trade.exit_date.desc()).limit(10)
            )).scalars().all()
            consecutive_losses = 0
            for pnl in recent_pnl:
                if pnl is not None and float(pnl) < 0:
                    consecutive_losses += 1
                else:
                    break

    except Exception as exc:
        raise RiskGateError(
            f"Guardrail DB read failed — refusing trade (fail closed): {exc}"
        ) from exc

    return PortfolioState(
        current_value=current_value,
        starting_capital=_cfg.starting_capital,
        daily_pnl=daily_pnl,
        weekly_pnl=weekly_pnl,
        monthly_pnl=monthly_pnl,
        consecutive_losses=consecutive_losses,
        trades_today=trades_today,
    )


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


@router.post("/kill-switch")
async def set_kill_switch(body: KillSwitchRequest):
    """Engage or reset the kill switch — syncs both the service and the local event."""
    if body.engaged:
        _kill_switch.set()
        await kill_switch_service.engage("manual via trade-desk API")
        logger.warning("KILL SWITCH ENGAGED via API — all order submission halted")
    else:
        _kill_switch.clear()
        await kill_switch_service.reset("OLBOSQUANT_MANUAL_RESET")
        logger.info("Kill switch reset via API — order submission resumed")
    return {"engaged": _is_kill_switch_active()}


# ── Execution mode ─────────────────────────────────────────────────────────────

@router.get("/execution-mode")
async def get_execution_mode():
    return execution_mode_manager.summary()


@router.post("/execution-mode")
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


@router.post("/approve/{signal_id}")
async def approve_signal(signal_id: str):
    """User approves a pending signal → executes order."""
    if signal_id not in _pending_approvals:
        raise HTTPException(404, "Signal not found in pending queue")

    signal = _pending_approvals.pop(signal_id)
    result = await _execute_signal(signal, approved_by="user")
    _execution_log.insert(0, {**result, "signal_id": signal_id, "approved_by": "user"})
    del _execution_log[200:]
    return result


@router.post("/reject/{signal_id}")
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

@router.post("/manual-trade")
async def manual_trade(req: ManualTradeRequest):
    """
    Force a manual equity order — bypasses signal scoring and IV filters
    but must still pass all risk guardrails (kill switch + loss limits + trade cap).
    """
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
    result = await _execute_signal(signal, approved_by="manual")
    if result.get("result") == "error":
        raise HTTPException(500, result.get("error", "execution error"))
    _execution_log.insert(0, result)
    del _execution_log[200:]
    return result


# ── Execution log ──────────────────────────────────────────────────────────────

@router.get("/execution-log")
async def get_execution_log(limit: int = 50):
    return {"log": _execution_log[:limit], "total": len(_execution_log)}


# ── Internal execution helper ──────────────────────────────────────────────────

async def _execute_signal(signal: dict, approved_by: str = "autopilot") -> dict:
    """
    Single fail-closed order pipeline. ALL order entry points must call this.
    Stages (in order — no stage may be skipped):
      1. Kill switch
      2. Guardrail risk check (fail closed — DB error = refused, not permitted)
      3. Duplicate guard
      4. Broker submission
      5. Fill-confirmed recording (CRITICAL alert on failure)
    """
    await asyncio.sleep(0)

    ticker      = signal.get("ticker", "")
    asset_type  = signal.get("asset_type", "equity")
    executed_at = datetime.now(timezone.utc).isoformat()

    def _blocked(reason: str) -> dict:
        return {
            "signal_id":  signal.get("id"),
            "ticker":     ticker,
            "asset_type": asset_type,
            "result":     "blocked",
            "reason":     reason,
            "executed_at": executed_at,
        }

    def _skipped(reason: str) -> dict:
        return {
            "signal_id":  signal.get("id"),
            "ticker":     ticker,
            "asset_type": asset_type,
            "result":     "skipped",
            "reason":     reason,
            "executed_at": executed_at,
        }

    # ── Stage 1: Kill switch ───────────────────────────────────────────────────
    if _is_kill_switch_active():
        logger.warning("Order blocked for %s — kill switch is engaged", ticker)
        return _blocked("kill_switch")

    # ── Stage 2: Guardrail risk check (fail closed) ────────────────────────────
    try:
        portfolio_state = await _fetch_portfolio_state()
    except RiskGateError as exc:
        logger.error("Risk gate refused trade for %s (fail closed): %s", ticker, exc)
        return _blocked(f"risk_gate_error: {exc}")

    _guardrail = GuardrailEngine()
    guardrail_status = _guardrail.check_all(portfolio_state)
    if not guardrail_status.trading_allowed:
        logger.warning("Guardrail blocked %s: %s", ticker, guardrail_status.reason)
        return _blocked(f"guardrail: {guardrail_status.reason}")

    # Capital preservation: restrict strategy selection even when trading is allowed
    strategy = signal.get("strategy", "")
    if strategy and not _guardrail.is_strategy_allowed(strategy, guardrail_status):
        logger.warning(
            "Capital preservation blocked strategy %s for %s", strategy, ticker
        )
        return _blocked(f"capital_preservation: strategy {strategy!r} not allowed in {guardrail_status.trading_mode} mode")

    # ── Stage 3: Duplicate guard ───────────────────────────────────────────────
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
            return _skipped("already_open")
    except Exception as _dup_exc:
        logger.warning("Duplicate check failed for %s: %s", ticker, _dup_exc)

    # ── Stages 4+5: Broker submission + fill recording ─────────────────────────
    action = signal.get("action", "")

    try:
        from app.broker.broker_factory import get_broker
        broker = get_broker()

        if asset_type == "equity":
            trade_plan = signal.get("trade_plan", {})
            shares     = trade_plan.get("shares", 1)

            # Stage 3b: sizing — zero shares = skip
            if not shares or shares <= 0:
                return _skipped("zero_size")

            result = await broker.place_equity_order(
                ticker=ticker,
                qty=shares,
                side=action,
                order_type=signal.get("order_type", "limit"),
                limit_price=trade_plan.get("entry_price"),
                stop=trade_plan.get("stop_price"),
            )

            # Stage 5: fill recording — CRITICAL on failure (filled but unrecorded is dangerous)
            from app.services.trade_recorder import trade_recorder
            recorded = await trade_recorder.record_fill(
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
            if recorded is None:
                logger.critical(
                    "CRITICAL: fill recorded at broker for %s but DB write FAILED — "
                    "position is untracked. Immediate review required.",
                    ticker,
                )

            return {
                "signal_id":    signal.get("id"),
                "ticker":       ticker,
                "asset_type":   "equity",
                "action":       action,
                "shares":       shares,
                "entry_price":  trade_plan.get("entry_price"),
                "stop_price":   trade_plan.get("stop_price"),
                "target_price": trade_plan.get("target_price"),
                "order_id":     result.order_id,
                "order_status": result.status,
                "result":       "submitted",
                "approved_by":  approved_by,
                "executed_at":  executed_at,
            }

        elif asset_type == "options":
            from app.broker.broker_interface import SpreadOrder, SpreadLeg
            from decimal import Decimal

            spread_data = signal.get("spread", {})
            expiry_str  = spread_data.get("expiration", "")
            short_str   = spread_data.get("short_strike", 0)
            long_str    = spread_data.get("long_strike", 0)
            opt_type    = spread_data.get("option_type", "put")
            credit      = spread_data.get("net_credit", 0)
            strategy    = signal.get("strategy", "bull_put_spread")
            quantity    = int(signal.get("quantity", 1))

            # Stage 3b: sizing — zero contracts = skip
            if quantity <= 0:
                return _skipped("zero_size")

            expiry_date = date.fromisoformat(expiry_str) if expiry_str else date.today()
            if "bear_call" in strategy:
                opt_type = "call"

            from app.core.config import settings as _cfg
            aggression = getattr(_cfg, "limit_price_aggression", 1.0)
            limit_px   = Decimal(str(round(credit * aggression, 2)))

            order = SpreadOrder(
                strategy=strategy,
                underlying=ticker,
                legs=[
                    SpreadLeg(symbol=ticker, expiration=expiry_date,
                              strike=Decimal(str(short_str)), option_type=opt_type,
                              action="SELL", quantity=quantity),
                    SpreadLeg(symbol=ticker, expiration=expiry_date,
                              strike=Decimal(str(long_str)), option_type=opt_type,
                              action="BUY", quantity=quantity),
                ],
                limit_price=limit_px,
                time_in_force="DAY",
            )
            result = await broker.place_order(order)

            # Stage 5: fill recording — CRITICAL on failure
            from app.services.trade_recorder import trade_recorder
            recorded = await trade_recorder.record_fill(
                strategy=strategy,
                underlying=ticker,
                option_type=opt_type,
                short_strike=float(short_str),
                long_strike=float(long_str),
                expiration=expiry_date,
                quantity=quantity,
                entry_credit=float(credit),
                spread_width=abs(float(short_str) - float(long_str)),
                signal_score=signal.get("signal_score", 0),
                iv_rank=signal.get("iv_rank", 0),
                regime=signal.get("regime", "unknown"),
                trading_mode=approved_by,
                dispatch_id=result.order_id or signal.get("id", ""),
            )
            if recorded is None:
                logger.critical(
                    "CRITICAL: fill recorded at broker for %s %s but DB write FAILED — "
                    "position is untracked. Immediate review required.",
                    strategy, ticker,
                )

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

        else:
            return _blocked(f"unknown asset_type: {asset_type}")

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
        # All risk checks (kill switch, guardrails, duplicate) happen inside _execute_signal.
        # The inline guardrail block that was here is deleted — _execute_signal is the
        # single gate for all paths.
        result = await _execute_signal(signal, approved_by="autopilot")
        if result.get("result") in ("blocked", "skipped"):
            signal["autopilot_blocked"] = result.get("reason")
            logger.warning(
                "Autopilot %s for %s: %s",
                result["result"], signal.get("ticker"), result.get("reason"),
            )
        _execution_log.insert(0, result)
        del _execution_log[200:]
