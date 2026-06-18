"""
Trade Desk routes — execution mode + approval queue for Copilot/Autopilot.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import require_admin_api_key
from app.core.config import settings
from app.services.execution_dispatcher import DispatchStatus, ExecutionDispatcher
from app.services.execution_mode import ExecutionMode, execution_mode_manager
from app.services.guardrails import PortfolioState
from app.services.kill_switch import kill_switch_service
from app.services.risk_manager import PortfolioRiskState, ProposedTrade, RiskManager
from app.services.unified_risk import RiskDecision, UnifiedRiskEngine

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
_order_gate_lock = asyncio.Lock()
_unified_risk_engine = UnifiedRiskEngine()
_risk_manager = RiskManager()


class RiskStateUnavailable(RuntimeError):
    """Raised when risk/guardrail state cannot be read safely."""


class KillSwitchEngaged(RuntimeError):
    """Raised when the kill switch blocks the order gate."""


@dataclass
class OrderIntent:
    signal_id: str
    ticker: str
    asset_type: str
    action: str
    strategy: str
    approved_by: str
    trade_plan: dict
    spread: dict
    requested_quantity: int
    entry_price: Decimal
    max_loss_per_unit: Decimal
    option_type: str | None = None
    expiration: date | None = None
    short_strike: Decimal | None = None
    long_strike: Decimal | None = None
    net_credit: Decimal = Decimal("0")


@dataclass
class OrderRiskContext:
    portfolio_state: PortfolioState
    portfolio_risk_state: PortfolioRiskState
    proposed_trade: ProposedTrade
    size_multiplier: float


@dataclass
class OrderDispatchOutcome:
    status: str
    order_id: str
    fill_price: Decimal | None = None
    message: str | None = None
    raw: object | None = None


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
    """Submit a manual equity order through the same fail-closed gate as signals."""
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
    Single fail-closed order pipeline for every order entry point.

    Stages:
      1. kill switch
      2. unified risk
      3. sizing
      4. execution dispatcher
      5. fill-confirmed recording
    """
    executed_at = datetime.now(timezone.utc).isoformat()
    intent = await _build_order_intent(signal, approved_by)

    async with _order_gate_lock:
        try:
            await _check_kill_switch_stage(intent)
        except KillSwitchEngaged as exc:
            return _blocked(intent, "kill_switch", executed_at, str(exc))
        try:
            context = await _load_order_context_stage(intent)
        except RiskStateUnavailable as exc:
            logger.error("Order blocked for %s — risk state unavailable: %s", intent.ticker, exc)
            return _blocked(intent, "risk_state_unavailable", executed_at, str(exc))

        risk_decision = _run_unified_risk_stage(intent, context)
        if not risk_decision.allowed:
            logger.warning("Order blocked for %s — %s", intent.ticker, risk_decision.reason)
            return _blocked(
                intent,
                "risk_block",
                executed_at,
                risk_decision.reason,
                flags=risk_decision.flags,
            )

        quantity = _size_order_stage(intent, context)
        if quantity <= 0:
            logger.info("Order skipped for %s — size returned zero", intent.ticker)
            return {
                "signal_id": intent.signal_id,
                "ticker": intent.ticker,
                "asset_type": intent.asset_type,
                "result": "skipped",
                "reason": "zero_size",
                "approved_by": approved_by,
                "executed_at": executed_at,
            }

        # Final hard stop immediately before broker/dispatcher call.
        try:
            await _check_kill_switch_stage(intent)
        except KillSwitchEngaged as exc:
            return _blocked(intent, "kill_switch", executed_at, str(exc))
        dispatch = await _dispatch_order_stage(intent, quantity)
        if dispatch.status != "filled":
            return {
                "signal_id": intent.signal_id,
                "ticker": intent.ticker,
                "asset_type": intent.asset_type,
                "strategy": intent.strategy,
                "result": dispatch.status,
                "reason": dispatch.message,
                "order_id": dispatch.order_id,
                "approved_by": approved_by,
                "executed_at": executed_at,
            }

        await _record_filled_order_stage(intent, quantity, dispatch)
        return {
            "signal_id": intent.signal_id,
            "ticker": intent.ticker,
            "asset_type": intent.asset_type,
            "strategy": intent.strategy,
            "action": intent.action,
            "quantity": quantity,
            "order_id": dispatch.order_id,
            "fill_price": float(dispatch.fill_price) if dispatch.fill_price is not None else None,
            "result": "filled",
            "approved_by": approved_by,
            "executed_at": executed_at,
        }


async def _check_kill_switch_stage(intent: OrderIntent) -> None:
    await asyncio.sleep(0)
    if _is_kill_switch_active():
        logger.warning("Order blocked for %s — kill switch is engaged", intent.ticker)
        raise KillSwitchEngaged("Kill switch is engaged")


async def _build_order_intent(signal: dict, approved_by: str) -> OrderIntent:
    asset_type = signal.get("asset_type", "equity")
    ticker = str(signal.get("ticker", "")).upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Signal missing ticker")

    if asset_type == "options":
        spread = signal.get("spread", {}) or {}
        short_str = Decimal(str(spread.get("short_strike", 0)))
        long_str = Decimal(str(spread.get("long_strike", 0)))
        credit = Decimal(str(spread.get("net_credit", 0)))
        width = abs(short_str - long_str)
        max_loss = Decimal(str(spread.get("max_loss", 0)))
        if max_loss <= 0 and width > 0:
            max_loss = max((width - credit) * Decimal("100"), Decimal("1"))
        expiry_raw = spread.get("expiration")
        expiry = date.fromisoformat(expiry_raw) if expiry_raw else date.today()
        strategy = signal.get("strategy", "bull_put_spread")
        option_type = spread.get("option_type", "call" if "call" in strategy else "put")
        return OrderIntent(
            signal_id=str(signal.get("id", uuid.uuid4())),
            ticker=ticker,
            asset_type="options",
            action=signal.get("action", "SELL_SPREAD"),
            strategy=strategy,
            approved_by=approved_by,
            trade_plan={},
            spread=spread,
            requested_quantity=int(spread.get("quantity") or signal.get("quantity") or 1),
            entry_price=credit,
            max_loss_per_unit=max_loss,
            option_type=option_type,
            expiration=expiry,
            short_strike=short_str,
            long_strike=long_str,
            net_credit=credit,
        )

    try:
        requested = int((signal.get("trade_plan", {}) or {}).get("shares") or 1)
    except Exception:
        requested = 1
    trade_plan = dict(signal.get("trade_plan", {}) or {})
    trade_plan["order_type"] = signal.get("order_type", trade_plan.get("order_type", "limit"))
    entry = Decimal(str(trade_plan.get("entry_price") or signal.get("entry_price") or 0))
    return OrderIntent(
        signal_id=str(signal.get("id", uuid.uuid4())),
        ticker=ticker,
        asset_type="equity",
        action=str(signal.get("action", "")).upper(),
        strategy="equity",
        approved_by=approved_by,
        trade_plan=trade_plan,
        spread={},
        requested_quantity=max(requested, 0),
        entry_price=entry,
        max_loss_per_unit=entry if entry > 0 else Decimal("0"),
    )


async def _load_order_context_stage(intent: OrderIntent) -> OrderRiskContext:
    from app.broker.broker_factory import get_broker
    from app.core.database import AsyncSessionLocal
    from app.models.trade import Trade
    from app.services.trading_mode import trading_mode_manager
    from sqlalchemy import and_, func, select

    broker = get_broker()
    try:
        account = await broker.get_account_summary()
        current_value = Decimal(str(account.net_liquidation))
        async with AsyncSessionLocal() as db:
            existing = (await db.execute(
                select(Trade.id).where(
                    Trade.underlying == intent.ticker,
                    Trade.status == "open",
                )
            )).first()
            if existing:
                raise RiskStateUnavailable(f"open trade already exists for {intent.ticker}")

            today = date.today()
            week_start = today - timedelta(days=today.weekday())
            month_start = today.replace(day=1)

            async def _sum_pnl(from_date: date) -> Decimal:
                result = await db.execute(
                    select(func.coalesce(func.sum(Trade.pnl), 0)).where(
                        and_(
                            Trade.status == "closed",
                            func.date(Trade.exit_date) >= from_date,
                        )
                    )
                )
                return Decimal(str(result.scalar() or 0))

            daily_pnl = await _sum_pnl(today)
            weekly_pnl = await _sum_pnl(week_start)
            monthly_pnl = await _sum_pnl(month_start)

            trades_today = int((await db.execute(
                select(func.count(Trade.id)).where(func.date(Trade.entry_date) == today)
            )).scalar() or 0)

            recent = (await db.execute(
                select(Trade.pnl)
                .where(Trade.status == "closed")
                .order_by(Trade.exit_date.desc())
                .limit(20)
            )).scalars().all()
            consecutive_losses = 0
            for pnl in recent:
                if (pnl or 0) < 0:
                    consecutive_losses += 1
                else:
                    break
    except RiskStateUnavailable:
        raise
    except Exception as exc:
        raise RiskStateUnavailable(str(exc)) from exc

    if intent.asset_type == "equity" and intent.max_loss_per_unit <= 0:
        try:
            quote = await broker.get_latest_quote(intent.ticker)
            bid = Decimal(str(quote.bid_price or 0))
            ask = Decimal(str(quote.ask_price or 0))
            if bid > 0 and ask > 0:
                intent.entry_price = (bid + ask) / Decimal("2")
            else:
                intent.entry_price = max(bid, ask)
            intent.max_loss_per_unit = intent.entry_price
        except Exception as exc:
            raise RiskStateUnavailable(f"equity quote unavailable: {exc}") from exc

    try:
        positions = await broker.get_positions()
    except Exception as exc:
        raise RiskStateUnavailable(f"positions unavailable: {exc}") from exc

    positions_by_underlying: dict[str, float] = {}
    net_delta = net_vega = net_theta = 0.0
    for pos in positions:
        qty = abs(int(getattr(pos, "quantity", 0) or 0))
        avg = Decimal(str(getattr(pos, "avg_cost", 0) or 0))
        multiplier = Decimal("1") if getattr(pos, "strike", Decimal("0")) == Decimal("0") else Decimal("100")
        exposure = float(avg * Decimal(qty) * multiplier)
        positions_by_underlying[pos.underlying] = positions_by_underlying.get(pos.underlying, 0.0) + exposure
        greeks = getattr(pos, "greeks", None)
        if greeks:
            net_delta += float(greeks.delta or 0)
            net_vega += float(greeks.vega or 0)
            net_theta += float(greeks.theta or 0)

    portfolio_state = PortfolioState(
        current_value=float(current_value),
        starting_capital=settings.starting_capital,
        daily_pnl=float(daily_pnl),
        weekly_pnl=float(weekly_pnl),
        monthly_pnl=float(monthly_pnl),
        consecutive_losses=consecutive_losses,
        trades_today=trades_today,
    )
    portfolio_risk_state = PortfolioRiskState(
        net_delta=net_delta,
        net_vega=net_vega,
        net_theta=net_theta,
        open_position_count=len(positions),
        portfolio_value=float(current_value),
        positions_by_underlying=positions_by_underlying,
        positions_by_sector={},
    )
    proposed_trade = ProposedTrade(
        strategy=intent.strategy,
        underlying=intent.ticker,
        sector="unknown",
        delta=0.0,
        vega=0.0,
        max_loss_dollars=float(intent.max_loss_per_unit),
        contracts=max(intent.requested_quantity, 1),
    )
    return OrderRiskContext(
        portfolio_state=portfolio_state,
        portfolio_risk_state=portfolio_risk_state,
        proposed_trade=proposed_trade,
        size_multiplier=1.0 if trading_mode_manager.config is None else 1.0,
    )


def _run_unified_risk_stage(intent: OrderIntent, context: OrderRiskContext) -> RiskDecision:
    return _unified_risk_engine.check(
        instrument_type="equity" if intent.asset_type == "equity" else "option",
        ticker=intent.ticker,
        portfolio_state=context.portfolio_state,
        portfolio_risk_state=context.portfolio_risk_state,
        proposed_trade=context.proposed_trade,
        size_multiplier=context.size_multiplier,
    )


def _size_order_stage(intent: OrderIntent, context: OrderRiskContext) -> int:
    from app.services.trading_mode import trading_mode_manager

    risk_pct = trading_mode_manager.config.risk_per_trade_pct
    sized = _risk_manager.calculate_position_size(
        portfolio_value=context.portfolio_risk_state.portfolio_value,
        max_loss_per_spread=float(intent.max_loss_per_unit),
        risk_pct=risk_pct,
        size_multiplier=context.size_multiplier,
    )
    if intent.asset_type == "equity" and intent.requested_quantity > 0:
        return min(intent.requested_quantity, sized)
    return sized


async def _dispatch_order_stage(intent: OrderIntent, quantity: int) -> OrderDispatchOutcome:
    from app.broker.broker_factory import get_broker

    broker = get_broker()
    if intent.asset_type == "equity":
        result = await broker.place_equity_order(
            ticker=intent.ticker,
            qty=quantity,
            side=intent.action,
            order_type=intent.trade_plan.get("order_type", "limit"),
            limit_price=float(intent.entry_price) if intent.entry_price > 0 else None,
            stop=intent.trade_plan.get("stop_price"),
        )
        return OrderDispatchOutcome(
            status=result.status,
            order_id=result.order_id,
            fill_price=result.fill_price,
            message=result.message,
            raw=result,
        )

    strategy = _build_multi_leg_from_intent(intent, quantity)
    result = await ExecutionDispatcher(broker).validate_and_dispatch(strategy, dry_run=False)
    return OrderDispatchOutcome(
        status="filled" if result.status == DispatchStatus.FILLED else result.status.value,
        order_id=result.order_id,
        fill_price=Decimal(str(result.net_fill_price)) if result.net_fill_price is not None else None,
        message=result.error,
        raw=result,
    )


def _build_multi_leg_from_intent(intent: OrderIntent, quantity: int):
    from app.broker.contract import EnrichedContract
    from app.services.multi_leg_strategy import LegAction, MultiLegStrategy, StrategyLeg

    width = abs((intent.short_strike or Decimal("0")) - (intent.long_strike or Decimal("0")))
    short_mid = max(float(intent.net_credit) + 0.5, 0.05)
    long_mid = max(0.5, 0.05)
    expiry = intent.expiration or date.today()
    opt_type = intent.option_type or "put"
    short = EnrichedContract(
        underlying_ticker=intent.ticker,
        strike_price=float(intent.short_strike or 1),
        expiration_date=expiry,
        option_type=opt_type,
        bid=max(short_mid - 0.05, 0.01),
        ask=short_mid + 0.05,
        last=short_mid,
        volume=0,
        open_interest=0,
    )
    long = EnrichedContract(
        underlying_ticker=intent.ticker,
        strike_price=float(intent.long_strike or max(Decimal("1"), (intent.short_strike or Decimal("1")) - width)),
        expiration_date=expiry,
        option_type=opt_type,
        bid=max(long_mid - 0.05, 0.01),
        ask=long_mid + 0.05,
        last=long_mid,
        volume=0,
        open_interest=0,
    )
    return MultiLegStrategy(
        strategy_name=intent.strategy,
        underlying=intent.ticker,
        legs=[
            StrategyLeg(short, LegAction.SELL, quantity),
            StrategyLeg(long, LegAction.BUY, quantity),
        ],
    )


async def _record_filled_order_stage(
    intent: OrderIntent,
    quantity: int,
    dispatch: OrderDispatchOutcome,
) -> None:
    from app.services.trade_recorder import trade_recorder

    if intent.asset_type == "equity":
        await trade_recorder.record_fill(
            strategy="equity",
            underlying=intent.ticker,
            option_type="equity",
            short_strike=float(intent.entry_price or 0),
            long_strike=0,
            expiration=date.today(),
            quantity=quantity,
            entry_credit=float(dispatch.fill_price or intent.entry_price or 0),
            trading_mode=intent.approved_by,
            dispatch_id=dispatch.order_id or intent.signal_id,
        )
        return

    await trade_recorder.record_fill(
        strategy=intent.strategy,
        underlying=intent.ticker,
        option_type=intent.option_type or "put",
        short_strike=float(intent.short_strike or 0),
        long_strike=float(intent.long_strike or 0),
        expiration=intent.expiration or date.today(),
        quantity=quantity,
        entry_credit=float(dispatch.fill_price or intent.net_credit or 0),
        spread_width=float(abs((intent.short_strike or Decimal("0")) - (intent.long_strike or Decimal("0")))),
        trading_mode=intent.approved_by,
        dispatch_id=dispatch.order_id or intent.signal_id,
    )


def _blocked(
    intent: OrderIntent,
    reason: str,
    executed_at: str,
    detail: str | None = None,
    flags: list[str] | None = None,
) -> dict:
    return {
        "signal_id": intent.signal_id,
        "ticker": intent.ticker,
        "asset_type": intent.asset_type,
        "result": "blocked",
        "reason": reason,
        **({"detail": detail} if detail else {}),
        **({"flags": flags} if flags else {}),
        "approved_by": intent.approved_by,
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
        result = await _execute_signal(signal, approved_by="autopilot")
        _execution_log.insert(0, result)
        del _execution_log[200:]
