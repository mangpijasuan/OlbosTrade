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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from decimal import Decimal

from app.api.deps import require_api_key
from app.services.execution_mode import ExecutionMode, execution_mode_manager
from app.services.guardrails import GuardrailEngine, PortfolioState
from app.services.kill_switch import kill_switch_service
from app.services.observability import observability

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
    from app.services.account_state import get_account_value
    from sqlalchemy import select, func

    current_value = await get_account_value()

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

            # Daily trade cap counts every trade ENTERED today, regardless of
            # status — a trade opened and closed the same day still used a slot.
            trades_today = int((await _db.execute(
                select(func.count()).where(
                    func.date(Trade.entry_date) == today,
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


async def _strategy_health_for(strategy: str):
    """
    Live health grade for one strategy from its closed trades, or None on error
    (the caller fails open). Kept thin and DB-scoped so the execution gate stays
    cheap.
    """
    try:
        from app.core.config import settings
        from app.core.database import AsyncSessionLocal
        from app.models.trade import Trade
        from app.services.strategy_health import evaluate_strategy_health
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            trades = (await session.execute(
                select(Trade).where(
                    Trade.strategy == strategy,
                    Trade.status == "closed",
                    Trade.pnl.isnot(None),
                )
            )).scalars().all()
        rows = [{"pnl": float(t.pnl), "entry_date": t.entry_date, "exit_date": t.exit_date}
                for t in trades]
        return evaluate_strategy_health(strategy, rows, settings.starting_capital)
    except Exception as exc:   # pragma: no cover - defensive; gate fails open
        logger.warning("Strategy health check failed for %s: %s", strategy, exc)
        return None

# ── Persisted pending approvals + execution log (Copilot mode / audit trail) ──
# Backed by the execution_events table so a deploy mid-Copilot-session doesn't
# silently drop pending approvals, and the execution log — the only audit trail
# of what autopilot actually did — survives restarts. Mirrors the kill switch's
# own DB-persistence pattern (GuardrailEvent, kill_switch.py).

async def _queue_pending_approval(signal: dict) -> None:
    """Queue a signal for Copilot/manual approval."""
    from app.core.database import AsyncSessionLocal
    from app.models.execution_event import ExecutionEvent

    signal_id = signal.get("id") or str(uuid.uuid4())
    signal["id"] = signal_id
    signal["queued_at"] = datetime.now(timezone.utc).isoformat()
    signal["status"] = "pending_approval"

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(ExecutionEvent(
                kind="pending_approval",
                signal_id=signal_id,
                ticker=signal.get("ticker"),
                asset_type=signal.get("asset_type"),
                status="pending",
                payload=signal,
            ))


async def _get_pending_approvals() -> list[dict]:
    from app.core.database import AsyncSessionLocal
    from app.models.execution_event import ExecutionEvent
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(ExecutionEvent)
            .where(ExecutionEvent.kind == "pending_approval", ExecutionEvent.status == "pending")
            .order_by(ExecutionEvent.created_at.desc())
        )).scalars().all()
    return [r.payload for r in rows]


async def _resolve_pending_approval(signal_id: str, resolution: str) -> Optional[dict]:
    """Mark a pending approval approved/rejected and return its payload, or None if not found/already resolved."""
    from app.core.database import AsyncSessionLocal
    from app.models.execution_event import ExecutionEvent
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        async with session.begin():
            row = (await session.execute(
                select(ExecutionEvent).where(
                    ExecutionEvent.kind == "pending_approval",
                    ExecutionEvent.signal_id == signal_id,
                    ExecutionEvent.status == "pending",
                )
            )).scalar_one_or_none()
            if row is None:
                return None
            payload = row.payload
            row.status = resolution
    return payload


async def _log_execution(entry: dict) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.execution_event import ExecutionEvent

    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                session.add(ExecutionEvent(
                    kind="execution",
                    signal_id=entry.get("signal_id") or entry.get("id"),
                    ticker=entry.get("ticker"),
                    asset_type=entry.get("asset_type"),
                    status=entry.get("result"),
                    payload=entry,
                ))
    except Exception as exc:
        logger.critical(
            "CRITICAL: execution result for %s could not be persisted to the "
            "execution log: %s — result was: %s",
            entry.get("ticker"), exc, entry,
        )


class SetExecutionModeRequest(BaseModel):
    mode: str   # manual | copilot | autopilot


class EquityEvaluateRequest(BaseModel):
    """Advisory evaluation for Equity Desk composer — does not place orders."""
    ticker: str
    action: str = "BUY"
    shares: int = 1
    entry_price: float
    stop_price: float
    target_price: Optional[float] = None
    order_type: str = "limit"


class KillSwitchRequest(BaseModel):
    engaged: bool
    # Required when engaged=False — must match KILL_SWITCH_RESET_CODE on the server.
    authorization_code: Optional[str] = None


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
    """
    Engage or reset the kill switch — syncs both the service and the local event.

    Engage is intentionally unauthenticated at the FastAPI layer (emergency stop;
    nginx Basic Auth still applies in production). Reset requires a server-side
    authorization code and never accepts a hardcoded client secret.
    """
    if body.engaged:
        _kill_switch.set()
        await kill_switch_service.engage("manual via trade-desk API")
        logger.warning("KILL SWITCH ENGAGED via API — all order submission halted")
    else:
        result = await kill_switch_service.reset(body.authorization_code or "")
        if not result.get("reset"):
            raise HTTPException(status_code=403, detail=result)
        _kill_switch.clear()
        logger.info("Kill switch reset via API — order submission resumed")
    return {"engaged": _is_kill_switch_active()}


# ── Execution mode ─────────────────────────────────────────────────────────────

@router.get("/execution-mode")
async def get_execution_mode():
    return execution_mode_manager.summary()


@router.post("/execution-mode", dependencies=[Depends(require_api_key)])
async def set_execution_mode(body: SetExecutionModeRequest):
    try:
        mode = ExecutionMode(body.mode)
    except ValueError:
        raise HTTPException(400, f"Invalid mode. Valid: manual, copilot, autopilot")
    return await execution_mode_manager.set_mode(mode)


# ── Pending approvals (Copilot) ────────────────────────────────────────────────

@router.get("/pending")
async def get_pending():
    """List signals awaiting user approval in Copilot mode."""
    items = sorted(await _get_pending_approvals(),
                   key=lambda x: x.get("queued_at", ""), reverse=True)
    return {
        "mode":    execution_mode_manager.mode.value,
        "pending": items,
        "count":   len(items),
    }


@router.post("/evaluate-equity")
async def evaluate_equity(req: EquityEvaluateRequest):
    """
    Backend-authoritative eligibility preview for the Equity Desk composer.

    Does NOT call _execute_signal and does NOT place orders. Aggregates kill
    switch, market hours, regime, account mode, and guardrail state into a
    TradeIntent-style final_status for UI display.
    """
    from datetime import datetime, timezone
    from app.core.config import settings
    from app.services.account_guard import verify_account_mode

    block_reasons: list[str] = []
    warnings: list[str] = []

    ticker = (req.ticker or "").upper().strip()
    if not ticker:
        block_reasons.append("Ticker is required")
    if req.shares < 1:
        block_reasons.append("Shares must be at least 1")
    if req.entry_price <= 0 or req.stop_price <= 0:
        block_reasons.append("Entry and stop prices must be positive")
    if req.action.upper() not in ("BUY", "SELL"):
        block_reasons.append("Action must be BUY or SELL")

    if req.action.upper() == "BUY" and req.stop_price >= req.entry_price:
        warnings.append("Stop is not below entry for a BUY")
    if req.action.upper() == "SELL" and req.stop_price <= req.entry_price:
        warnings.append("Stop is not above entry for a SELL")

    env = "paper" if settings.is_paper_trading else "live"

    if _is_kill_switch_active():
        block_reasons.append("Kill switch is engaged")

    if getattr(settings, "market_hours_only", True):
        from app.utils.market_hours import is_market_open, market_status
        if not is_market_open():
            st = market_status()
            block_reasons.append(
                f"Market closed ({st.get('session', 'outside RTH')})"
            )

    try:
        from app.main import _current_regime
        if _current_regime is not None and not getattr(
            _current_regime, "equity_allowed", True
        ):
            block_reasons.append(
                f"Regime does not allow equities "
                f"({getattr(getattr(_current_regime, 'regime', None), 'value', 'unknown')})"
            )
    except Exception:
        warnings.append("Regime state unavailable — treat with caution")

    try:
        from app.broker.broker_factory import get_broker
        broker = get_broker()
        _ok, _detail = await verify_account_mode(broker)
        if not _ok:
            block_reasons.append(f"Account mode: {_detail}")
    except Exception as exc:
        warnings.append(f"Account mode check skipped: {exc}")

    try:
        portfolio_state = await _fetch_portfolio_state()
        guardrail = GuardrailEngine().check_all(portfolio_state)
        if not guardrail.trading_allowed:
            block_reasons.append(
                guardrail.reason or f"Guardrails blocked ({guardrail.trading_mode})"
            )
        elif guardrail.trading_mode == "capital_preservation":
            warnings.append("Capital preservation mode — size may be reduced at execution")
        try:
            from app.services.execution_portfolio_gate import check_execution_portfolio
            pg = await check_execution_portfolio(
                {
                    "ticker": ticker,
                    "asset_type": "equity",
                    "trade_plan": {
                        "shares": req.shares,
                        "entry_price": req.entry_price,
                        "stop_price": req.stop_price,
                    },
                },
                portfolio_value=float(portfolio_state.current_value or 0),
            )
            if not pg.allowed:
                block_reasons.append(pg.reason or "Portfolio gate blocked")
        except Exception as pg_exc:
            warnings.append(f"Portfolio gate preview incomplete: {pg_exc}")
    except RiskGateError as exc:
        block_reasons.append(str(exc))
    except Exception as exc:
        warnings.append(f"Guardrail check incomplete: {exc}")

    mode = execution_mode_manager.mode.value
    if block_reasons:
        final_status = "BLOCKED"
    elif mode == "copilot":
        final_status = "COPILOT_REVIEW_REQUIRED"
    elif mode == "manual":
        final_status = "MANUAL_ELIGIBLE"
    elif mode == "autopilot":
        # Scan/composer path still queues — be honest
        final_status = "COPILOT_REVIEW_REQUIRED"
        warnings.append(
            "Autopilot scan/composer auto-execute is disabled; submit queues for approval"
        )
    else:
        final_status = "INFORMATIONAL"

    risk_dollars = abs(req.entry_price - req.stop_price) * req.shares
    notional = req.entry_price * req.shares

    return {
        "final_status": final_status,
        "block_reasons": block_reasons,
        "warnings": warnings,
        "environment": env,
        "execution_mode": mode,
        "ticker": ticker,
        "action": req.action.upper(),
        "shares": req.shares,
        "estimated_notional": round(notional, 2),
        "estimated_max_loss": round(risk_dollars, 2),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_version": "equity-desk-c1",
    }


class OptionsEvaluateRequest(BaseModel):
    """Advisory evaluation for Options Desk — does not place orders."""
    ticker: str
    strategy: str = "bull_put_spread"
    dte: float = 30


@router.post("/evaluate-options")
async def evaluate_options(req: OptionsEvaluateRequest):
    """
    Backend-authoritative eligibility preview for the Options Desk.

    Does NOT call _execute_signal. Blocks naked / iron_condor / 0DTE autopilot
    strategies explicitly. Defined-risk and income strategies may be MANUAL or
    COPILOT eligible subject to kill switch, hours, regime, and guardrails.
    """
    from datetime import datetime, timezone
    from app.core.config import settings
    from app.services.account_guard import verify_account_mode

    block_reasons: list[str] = []
    warnings: list[str] = []

    ticker = (req.ticker or "").upper().strip()
    strategy = (req.strategy or "").lower().strip()
    allowed = {
        "bull_put_spread", "bear_call_spread", "bull_call_spread", "bear_put_spread",
        "cash_secured_put", "covered_call",
    }
    banned = {"naked_call", "naked_put", "iron_condor", "short_straddle", "short_strangle"}

    if not ticker:
        block_reasons.append("Ticker is required")
    if strategy in banned:
        block_reasons.append(f"Strategy '{strategy}' is not permitted")
    elif strategy and strategy not in allowed:
        warnings.append(f"Strategy '{strategy}' is not in the Phase D supported set")

    if req.dte is not None and req.dte <= 1:
        warnings.append("0DTE / 1DTE: Autopilot disabled — Copilot or manual only")
        # Do not block evaluate for read-only desk; warn strongly
        warnings.append("0DTE Autopilot remains disabled by policy")

    env = "paper" if settings.is_paper_trading else "live"

    if _is_kill_switch_active():
        block_reasons.append("Kill switch is engaged")

    if getattr(settings, "market_hours_only", True):
        from app.utils.market_hours import is_market_open, market_status
        if not is_market_open():
            st = market_status()
            block_reasons.append(
                f"Market closed ({st.get('session', 'outside RTH')})"
            )

    try:
        from app.main import _current_regime
        if _current_regime is not None and not getattr(
            _current_regime, "options_allowed", True
        ):
            block_reasons.append(
                f"Regime does not allow options "
                f"({getattr(getattr(_current_regime, 'regime', None), 'value', 'unknown')})"
            )
    except Exception:
        warnings.append("Regime state unavailable — treat with caution")

    try:
        from app.broker.broker_factory import get_broker
        broker = get_broker()
        _ok, _detail = await verify_account_mode(broker)
        if not _ok:
            block_reasons.append(f"Account mode: {_detail}")
    except Exception as exc:
        warnings.append(f"Account mode check skipped: {exc}")

    try:
        portfolio_state = await _fetch_portfolio_state()
        guardrail = GuardrailEngine().check_all(portfolio_state)
        if not guardrail.trading_allowed:
            block_reasons.append(
                guardrail.reason or f"Guardrails blocked ({guardrail.trading_mode})"
            )
        elif guardrail.trading_mode == "capital_preservation":
            warnings.append("Capital preservation mode — size may be reduced at execution")
        try:
            from app.services.execution_portfolio_gate import check_execution_portfolio
            # Preview uses a nominal 1-lot defined-risk placeholder when no spread
            # payload is supplied by the desk composer.
            pg = await check_execution_portfolio(
                {
                    "ticker": ticker,
                    "asset_type": "options",
                    "strategy": strategy or "bull_put_spread",
                    "quantity": 1,
                    "spread": {"max_loss": 250.0},
                },
                portfolio_value=float(portfolio_state.current_value or 0),
            )
            if not pg.allowed:
                block_reasons.append(pg.reason or "Portfolio gate blocked")
        except Exception as pg_exc:
            warnings.append(f"Portfolio gate preview incomplete: {pg_exc}")
    except RiskGateError as exc:
        block_reasons.append(str(exc))
    except Exception as exc:
        warnings.append(f"Guardrail check incomplete: {exc}")

    mode = execution_mode_manager.mode.value
    if block_reasons:
        final_status = "BLOCKED"
    elif mode == "copilot":
        final_status = "COPILOT_REVIEW_REQUIRED"
    elif mode == "manual":
        final_status = "MANUAL_ELIGIBLE"
    elif mode == "autopilot":
        final_status = "COPILOT_REVIEW_REQUIRED"
        warnings.append(
            "Options Autopilot from desk tools queues for approval; 0DTE Autopilot stays off"
        )
    else:
        final_status = "INFORMATIONAL"

    return {
        "final_status": final_status,
        "block_reasons": block_reasons,
        "warnings": warnings,
        "environment": env,
        "execution_mode": mode,
        "ticker": ticker,
        "strategy": strategy,
        "dte": req.dte,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_version": "options-desk-d1",
        "policy": {
            "naked_shorts": False,
            "iron_condor_execute": False,
            "zero_dte_autopilot": False,
        },
    }


@router.post("/approve/{signal_id}", dependencies=[Depends(require_api_key)])
async def approve_signal(signal_id: str):
    """User approves a pending signal → executes order."""
    signal = await _resolve_pending_approval(signal_id, "approved")
    if signal is None:
        raise HTTPException(404, "Signal not found in pending queue")

    result = await _execute_signal(signal, approved_by="user")
    await _log_execution({**result, "signal_id": signal_id, "approved_by": "user"})
    return result


@router.post("/reject/{signal_id}", dependencies=[Depends(require_api_key)])
async def reject_signal(signal_id: str):
    """User rejects a pending signal — no order sent."""
    signal = await _resolve_pending_approval(signal_id, "rejected")
    if signal is None:
        raise HTTPException(404, "Signal not found in pending queue")

    entry = {
        "signal_id":   signal_id,
        "ticker":      signal.get("ticker"),
        "asset_type":  signal.get("asset_type", "equity"),
        "action":      signal.get("action"),
        "result":      "rejected",
        "rejected_at": datetime.now(timezone.utc).isoformat(),
        "rejected_by": "user",
    }
    await _log_execution(entry)
    return entry


# ── Manual trade ──────────────────────────────────────────────────────────────

@router.post("/manual-trade", dependencies=[Depends(require_api_key)])
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
    await _log_execution(result)
    return result


class ClosePositionRequest(BaseModel):
    trade_id: str
    order_type: str = "market"          # market | limit
    limit_price: Optional[float] = None


@router.post("/close-position", dependencies=[Depends(require_api_key)])
async def close_position(req: ClosePositionRequest):
    """
    Manually close an open position — the operator's own "I want out now"
    action, independent of the automated profit-target/stop-loss exit.

    Does NOT go through _execute_signal (that pipeline's duplicate guard
    blocks *any* new order on a ticker with an existing open trade — exactly
    the position this endpoint exists to close — so it would reject a
    closing order as "already_open"). Kill switch is deliberately NOT
    checked here: closing reduces risk, and kill-switch engagement already
    flattens positions on its own — blocking a manual close during a
    kill-switch event would be backwards.

    Equity only for now. Options positions are 2-leg spreads; closing one
    means submitting the mirrored spread order (buy back the short leg,
    sell the long leg) — deliberately deferred rather than half-built.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.trade import Trade
    from sqlalchemy import select

    try:
        trade_uuid = uuid.UUID(req.trade_id)
    except ValueError:
        raise HTTPException(400, "Invalid trade_id")

    async with AsyncSessionLocal() as session:
        trade = (await session.execute(
            select(Trade).where(Trade.id == trade_uuid)
        )).scalar_one_or_none()

    if trade is None:
        raise HTTPException(404, "Trade not found")
    if trade.status != "open":
        raise HTTPException(409, f"Trade is not open (status={trade.status})")

    spread_type = (trade.spread_type or "").lower()
    if spread_type not in ("equity_long", "equity_short"):
        raise HTTPException(
            400,
            "Manual close currently supports equity positions only — "
            "close options spreads directly with the broker for now.",
        )

    close_side = "SELL" if spread_type == "equity_long" else "BUY"
    ticker = trade.underlying
    qty = int(trade.quantity or 1)

    from app.broker.broker_factory import get_broker
    broker = get_broker()

    # Cancel the bracket's still-working stop/take-profit legs first — leaving
    # them live after this close would be a dangling order with no position
    # behind it, able to fire unexpectedly against a later trade in the same ticker.
    cancelled = await broker.cancel_open_orders(ticker)

    result = await broker.place_equity_order(
        ticker=ticker, qty=qty, side=close_side,
        order_type=req.order_type, limit_price=req.limit_price,
    )

    if result.status in ("cancelled", "rejected"):
        raise HTTPException(502, f"Broker did not accept the close order: {result.status}")

    if result.status == "filled" and result.fill_price is not None:
        from app.services.trade_recorder import trade_recorder
        await trade_recorder.record_exit(
            trade_id=req.trade_id,
            cost_to_close=float(result.fill_price),
            exit_reason="manual",
        )
    # else: order is working/pending — the existing fill reconciler (_poll_fills)
    # detects the position disappearing from the broker and closes it out,
    # same as it already does for automated bracket exits.

    entry = {
        "trade_id":  req.trade_id,
        "ticker":    ticker,
        "action":    close_side,
        "quantity":  qty,
        "order_id":  result.order_id,
        "status":    result.status,
        "cancelled_open_orders": cancelled,
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "closed_by": "manual",
    }
    await _log_execution(entry)
    return entry


# ── Execution log ──────────────────────────────────────────────────────────────

@router.get("/execution-log")
async def get_execution_log(limit: int = 50):
    from app.core.database import AsyncSessionLocal
    from app.models.execution_event import ExecutionEvent
    from sqlalchemy import select, func

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(ExecutionEvent)
            .where(ExecutionEvent.kind == "execution")
            .order_by(ExecutionEvent.created_at.desc())
            .limit(limit)
        )).scalars().all()
        total = (await session.execute(
            select(func.count()).where(ExecutionEvent.kind == "execution")
        )).scalar_one()
    return {"log": [r.payload for r in rows], "total": total}


# ── Internal execution helper ──────────────────────────────────────────────────

async def _execute_signal(signal: dict, approved_by: str = "autopilot") -> dict:
    """
    Single fail-closed order pipeline. ALL order entry points must call this.
    Stages (in order — no stage may be skipped):
      1. Kill switch
      1b. Market hours
      1c. Frequency controller (non-manual)
      1d. Strategy health (non-manual; fail-open on error)
      2. Guardrail risk check (fail closed — DB error = refused)
      2b. Portfolio gate — concentration / max positions / heat (Step 8)
      3. Duplicate guard
      4. Broker submission (+ account mode + margin)
      5. Fill-confirmed recording (CRITICAL alert on failure)
    """
    await asyncio.sleep(0)

    observability.incr("execute.attempt")
    ticker      = signal.get("ticker", "")
    asset_type  = signal.get("asset_type", "equity")
    executed_at = datetime.now(timezone.utc).isoformat()

    def _blocked(reason: str) -> dict:
        observability.incr("execute.blocked")
        observability.event("blocked", ticker=ticker, asset_type=asset_type,
                            reason=reason.split(":")[0])
        return {
            "signal_id":  signal.get("id"),
            "ticker":     ticker,
            "asset_type": asset_type,
            "result":     "blocked",
            "reason":     reason,
            "executed_at": executed_at,
        }

    def _skipped(reason: str) -> dict:
        observability.incr("execute.skipped")
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

    # ── Stage 1b: Market hours ─────────────────────────────────────────────────
    # Pause order submission outside US regular trading hours. The scanner keeps
    # generating signals 24/7; execution auto-resumes at the next open. Options
    # don't trade after hours and after-hours equity fills are poor, so this
    # covers every path (autopilot, copilot approval, manual).
    from app.core.config import settings as _mh_cfg
    if getattr(_mh_cfg, "market_hours_only", True):
        from app.utils.market_hours import is_market_open, market_status
        if not is_market_open():
            status = market_status()
            logger.info(
                "Order blocked for %s — market closed (%s, %s)",
                ticker, status["reason"], status["now_et"],
            )
            return _blocked(f"market_closed: {status['reason']}")

    # ── Stage 2: Guardrail risk check (fail closed) ────────────────────────────
    try:
        portfolio_state = await _fetch_portfolio_state()
    except RiskGateError as exc:
        logger.error("Risk gate refused trade for %s (fail closed): %s", ticker, exc)
        return _blocked(f"risk_gate_error: {exc}")

    # ── Stage 1c: Trade Frequency Controller (before the risk engine) ───────────
    # Profitability before activity: per-mode daily cap, min confidence, max risk
    # score, and a positive-EV quality filter. Reuses the portfolio-state read.
    # Manual trades bypass it — the user is overriding signal generation on purpose
    # (they still face the kill switch, market hours, guardrails, and sizing).
    from app.core.config import settings as _tm_cfg
    if approved_by != "manual" and not getattr(_tm_cfg, "execution_test_mode", False):
        from app.services.trade_frequency_controller import trade_frequency_controller
        freq = trade_frequency_controller.evaluate(
            signal, trades_today=portfolio_state.trades_today,
        )
        if not freq.allowed:
            logger.info(
                "Frequency controller blocked %s: %s (score=%.3f risk=%d ev=%.3f)",
                ticker, freq.reason, freq.weighted_score, freq.risk_score, freq.expected_value,
            )
            return _blocked(f"frequency_controller: {freq.reason}")

        # ── Stage 1d: Strategy Health Monitor (auto-suspend) ────────────────────
        # A strategy whose live edge has degraded vs. its baseline accepts no new
        # entries until it recovers. Advisory — fails OPEN on error so a transient
        # DB issue never halts trading (kill switch + guardrails still protect).
        strat = signal.get("strategy", "")
        if strat:
            health = await _strategy_health_for(strat)
            if health is not None and health.status == "degraded":
                logger.warning(
                    "Strategy health blocked %s (%s): %s",
                    ticker, strat, "; ".join(health.reasons),
                )
                return _blocked(
                    f"strategy_health: {strat} degraded — {'; '.join(health.reasons)}")

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

    # ── Stage 2b: Portfolio gate (concentration / max positions / heat) ─────
    # Step 8 — wires RiskManager + portfolio_engine into the live OMS path.
    # Greeks caps remain off unless execution_enforce_portfolio_greeks=true.
    # Rollback: execution_portfolio_gate=false.
    from app.services.execution_portfolio_gate import check_execution_portfolio
    portfolio_gate = await check_execution_portfolio(
        signal, portfolio_value=float(portfolio_state.current_value or 0),
    )
    if not portfolio_gate.allowed:
        logger.warning(
            "Portfolio gate blocked %s: %s flags=%s",
            ticker, portfolio_gate.reason, portfolio_gate.flags,
        )
        return _blocked(f"portfolio_gate: {portfolio_gate.reason}")

    # Fast no-op exits should not hit lifecycle or DB gates.
    if asset_type == "equity":
        trade_plan = signal.get("trade_plan", {})
        shares = trade_plan.get("shares", 1)
        if not shares or shares <= 0:
            return _skipped("zero_size")
    elif asset_type == "options":
        quantity = int(signal.get("quantity", 1) or 0)
        if quantity <= 0:
            return _skipped("zero_size")

    # ── Stage 3: Duplicate guard ───────────────────────────────────────────────
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.trade import Trade
        from sqlalchemy import select
        async with AsyncSessionLocal() as _db:
            existing = (await _db.execute(
                select(Trade.id).where(
                    Trade.underlying == ticker,
                    Trade.status.in_(["open", "pending"]),
                )
            )).first()
        if existing:
            logger.info("Skipping %s — open/pending trade already exists in DB", ticker)
            return _skipped("already_open")
    except Exception as _dup_exc:
        logger.warning("Duplicate check failed for %s: %s", ticker, _dup_exc)

    # ── Stages 4+5: Broker submission + fill recording ─────────────────────────
    action = signal.get("action", "")

    try:
        from app.broker.broker_factory import get_broker
        broker = get_broker()

        # ── Account mode guard (fail closed) — last gate before submission ──────
        # Never place a real-money order when the operator believes they're on
        # paper. Verifies the broker's actual account (DU…=paper, U…=live) matches
        # IBKR_TRADING_MODE; blocks on any mismatch or if it can't be verified.
        # Manual orders are NOT exempt — this is a safety floor.
        from app.services.account_guard import verify_account_mode
        _ok, _detail = await verify_account_mode(broker)
        if not _ok:
            logger.critical("Order blocked for %s — account guard: %s", ticker, _detail)
            return _blocked(f"account_guard: {_detail}")

        # ── Margin guard — block new entries when margin is critical ────────────
        # Fail-OPEN: margin figures are advisory and may be absent (paper); we only
        # block on a positively-detected critical state, never on missing data.
        try:
            from app.services.margin_monitor import evaluate_margin
            from app.core.config import settings as _mg_cfg
            _acct = await broker.get_account_summary()
            if _acct.maintenance_margin is not None:
                _m = evaluate_margin(
                    net_liquidation=float(_acct.net_liquidation or 0),
                    maintenance_margin=float(_acct.maintenance_margin or 0),
                    excess_liquidity=float(_acct.excess_liquidity or 0),
                    buying_power=float(_acct.buying_power or 0),
                    init_margin=float(_acct.init_margin or 0),
                    warn_pct=_mg_cfg.margin_warn_pct,
                    critical_pct=_mg_cfg.margin_critical_pct,
                )
                if _m.status == "critical":
                    logger.warning("Order blocked for %s — margin: %s", ticker, _m.detail)
                    return _blocked(f"margin_critical: {_m.detail}")
        except Exception as _mg_exc:
            logger.debug("Margin guard skipped for %s: %s", ticker, _mg_exc)

        if asset_type == "equity":
            trade_plan = signal.get("trade_plan", {})
            shares     = trade_plan.get("shares", 1)

            result = await broker.place_equity_order(
                ticker=ticker,
                qty=shares,
                side=action,
                order_type=signal.get("order_type", "limit"),
                limit_price=trade_plan.get("entry_price"),
                stop=trade_plan.get("stop_price"),
                take_profit=trade_plan.get("target_price"),
            )

            # A terminated-unfilled order is NOT recorded — recording it would
            # create a phantom position the broker never opened.
            if result.status in ("cancelled", "rejected"):
                logger.info("Equity order for %s %s — not recorded", ticker, result.status)
                return _blocked(f"order_{result.status}")

            # Record as a live position only on a confirmed fill; otherwise record
            # as pending so the fill reconciler promotes/cancels it later.
            entry_status = "open" if result.status == "filled" else "pending"

            # Encode direction so exit P&L is computed with the right sign.
            # SELL = short (profit when price falls), default BUY = long.
            equity_direction = "equity_short" if action.upper() == "SELL" else "equity_long"

            # Stage 5: fill recording — CRITICAL on failure (filled but unrecorded is dangerous)
            from app.services.trade_recorder import trade_recorder
            recorded = await trade_recorder.record_fill(
                strategy="equity",
                underlying=ticker,
                option_type=equity_direction,
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
                status=entry_status,
            )
            if recorded is None:
                logger.critical(
                    "CRITICAL: fill recorded at broker for %s but DB write FAILED — "
                    "position is untracked. Immediate review required.",
                    ticker,
                )

            observability.incr("execute.submitted")
            observability.event("submitted", ticker=ticker, asset_type="equity",
                                order_id=result.order_id)
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

            expiry_date = date.fromisoformat(expiry_str) if expiry_str else date.today()
            if "bear_call" in strategy:
                opt_type = "call"

            from app.core.config import settings as _cfg
            aggression = getattr(_cfg, "limit_price_aggression", 1.0)
            # `credit` (net_credit) is a PER-CONTRACT dollar amount (already x100,
            # e.g. $150 for a $1.50 spread). The broker expects a PER-SHARE net
            # price (1.50) — IB applies the x100 multiplier itself. Passing 150
            # asked for a $150 credit per spread and the order NEVER filled, which
            # is why no options trades were ever executed. Convert back to per-share.
            credit_per_share = float(credit) / 100.0
            limit_px   = Decimal(str(round(credit_per_share * aggression, 2)))

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

            # A terminated-unfilled order is NOT recorded (no phantom position).
            if result.status in ("cancelled", "rejected"):
                logger.info("Options order for %s %s %s — not recorded",
                            strategy, ticker, result.status)
                return _blocked(f"order_{result.status}")

            # "filled"/"partial" → a real position exists now → open.
            # "submitted"/"pending" → still working → pending (reconciler resolves).
            entry_status = "open" if result.status in ("filled", "partial") else "pending"

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
                # Store per-share net credit (1.50, not 150) so record_exit's
                # x100 contract multiplier yields correct dollar P&L.
                entry_credit=credit_per_share,
                spread_width=abs(float(short_str) - float(long_str)),
                signal_score=signal.get("signal_score", 0),
                iv_rank=signal.get("iv_rank", 0),
                regime=signal.get("regime", "unknown"),
                trading_mode=approved_by,
                dispatch_id=result.order_id or signal.get("id", ""),
                status=entry_status,
            )
            if recorded is None:
                logger.critical(
                    "CRITICAL: fill recorded at broker for %s %s but DB write FAILED — "
                    "position is untracked. Immediate review required.",
                    strategy, ticker,
                )

            observability.incr("execute.submitted")
            observability.event("submitted", ticker=ticker, asset_type="options",
                                strategy=strategy, order_id=result.order_id)
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
        observability.incr("execute.error")
        observability.event("error", ticker=ticker, asset_type=asset_type, error=str(exc))
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
        await _queue_pending_approval(signal)

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
        await _log_execution(result)


# ── Scan panel signal submission ────────────────────────────────────────────────

class ScanSignalRequest(BaseModel):
    """Signal from options/equity scan panel or Equity Desk composer."""
    ticker: str
    action: str
    entry_price: float
    stop_price: float
    target_price: float
    entry_ladder: list = []
    kelly_fraction: float = 0.1
    expected_value: float = 0.0
    pop: float = 0.0
    confidence: float = 0.0
    source: str = "scan_engine"  # "options_scan_engine" or "equity_scan_engine"
    # Equity size — composer sends this; scan panel defaults to 1 if omitted.
    shares: int = 1
    asset_type: str = "equity"


@router.post("/signal", dependencies=[Depends(require_api_key)])
async def submit_scan_signal(req: ScanSignalRequest):
    """
    Submit a signal from scan panel / Equity Desk for execution routing.

    Routes through execution mode:
    - MANUAL / COPILOT: queue for approval
    - AUTOPILOT: still queues from this endpoint (scan auto-execute disabled)

    Equity payloads include trade_plan.shares so approve → _execute_signal
    does not silently default to 1 share when the composer sent a larger size.
    """
    signal_id = str(uuid.uuid4())
    shares = max(int(req.shares or 1), 1)

    # Build signal compatible with _execute_signal()
    signal = {
        "id": signal_id,
        "ticker": req.ticker.upper(),
        "action": req.action,
        "asset_type": (req.asset_type or "equity").lower(),
        "entry_price": req.entry_price,
        "stop_price": req.stop_price,
        "target_price": req.target_price,
        "trade_plan": {
            "shares": shares,
            "entry_price": req.entry_price,
            "stop_price": req.stop_price,
            "target_price": req.target_price,
            "risk_reward": (
                abs(req.target_price - req.entry_price) / abs(req.entry_price - req.stop_price)
                if abs(req.entry_price - req.stop_price) > 1e-9 else 0.0
            ),
        },
        "confidence": req.confidence,
        "kelly_fraction": req.kelly_fraction,
        "expected_value": req.expected_value,
        "pop": req.pop,
        "entry_ladder": req.entry_ladder,
        "source": req.source,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "approved_by": "scan_panel",
    }

    mode = execution_mode_manager.mode

    if mode == ExecutionMode.MANUAL:
        # Queue for user approval
        await _queue_pending_approval(signal)
        return {
            "signal_id": signal_id,
            "ticker": req.ticker,
            "status": "pending_approval",
            "shares": shares,
            "message": f"Signal queued for manual approval (execution mode: MANUAL)",
        }

    elif mode == ExecutionMode.COPILOT:
        # Copilot decides
        await _queue_pending_approval(signal)
        return {
            "signal_id": signal_id,
            "ticker": req.ticker,
            "status": "pending_copilot",
            "shares": shares,
            "message": f"Signal submitted to Copilot (execution mode: COPILOT)",
        }

    elif mode == ExecutionMode.AUTOPILOT:
        # SAFETY: scan-driven autopilot auto-execution is intentionally disabled
        # until the scan execution path has test coverage. The scan engine and
        # panels are live for MANUAL/COPILOT; autopilot placing trades directly
        # from scans is gated off. To re-enable, restore the _execute_signal call
        # below and add tests for the scan → _execute_signal path.
        #   result = await _execute_signal(signal, approved_by="scan_autopilot")
        await _queue_pending_approval(signal)
        logger.info(
            "Scan signal %s for %s queued (autopilot scan-execute disabled pending tests)",
            signal_id, req.ticker,
        )
        return {
            "signal_id": signal_id,
            "ticker": req.ticker,
            "status": "pending_approval",
            "shares": shares,
            "message": "Autopilot scan-execute is disabled pending tests — queued for approval.",
        }

    else:
        raise HTTPException(status_code=400, detail=f"Unknown execution mode: {mode}")
