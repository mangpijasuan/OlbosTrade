"""
Trade Desk routes — execution mode + approval queue for Copilot/Autopilot.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import require_api_key
from app.services.execution_mode import ExecutionMode, execution_mode_manager
from app.services.kill_switch import kill_switch_service

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Kill switch ────────────────────────────────────────────────────────────────
# Single source of truth: kill_switch_service (services/kill_switch.py). Its
# `is_engaged` is a cheap sync property, so the hot path reads it directly — no
# separate mirror to drift out of sync.


def _is_kill_switch_active() -> bool:
    return kill_switch_service.is_engaged

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


@router.post("/kill-switch", dependencies=[Depends(require_api_key)])
async def set_kill_switch(body: KillSwitchRequest):
    """Engage or reset the kill switch (authoritative service is the single source of truth)."""
    if body.engaged:
        await kill_switch_service.engage("manual via trade-desk API")
        logger.warning("KILL SWITCH ENGAGED via API — all order submission halted")
    else:
        await kill_switch_service.reset("OLBOSQUANT_MANUAL_RESET")
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


@router.post("/approve/{signal_id}", dependencies=[Depends(require_api_key)])
async def approve_signal(signal_id: str):
    """User approves a pending signal → executes order."""
    if signal_id not in _pending_approvals:
        raise HTTPException(404, "Signal not found in pending queue")

    signal = _pending_approvals.pop(signal_id)
    result = await _execute_signal(signal, approved_by="user")
    _execution_log.insert(0, {**result, "signal_id": signal_id, "approved_by": "user"})
    del _execution_log[200:]
    return result


@router.post("/reject/{signal_id}", dependencies=[Depends(require_api_key)])
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

@router.post("/manual-trade", dependencies=[Depends(require_api_key)])
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

    # Route through the SAME fail-closed gate as every other order — no manual
    # bypass. The gate runs kill switch → unified risk → sizing → dispatch → record.
    result = await _execute_signal(signal, approved_by="manual")
    _execution_log.insert(0, {**result, "approved_by": "manual"})
    del _execution_log[200:]
    if result.get("result") in ("blocked", "rejected", "error"):
        raise HTTPException(
            403, result.get("reason") or result.get("error") or "rejected by risk gate"
        )
    return result


# ── Execution log ──────────────────────────────────────────────────────────────

@router.get("/execution-log")
async def get_execution_log(limit: int = 50):
    return {"log": _execution_log[:limit], "total": len(_execution_log)}


# ── Internal execution helper ──────────────────────────────────────────────────

async def _execute_signal(signal: dict, approved_by: str = "autopilot") -> dict:
    """
    Submit a signal through the SINGLE fail-closed order gate
    (kill switch -> unified risk -> sizing -> dispatch -> fill recording).
    This is the one choke point; manual / copilot / autopilot all funnel here.
    """
    from app.services.order_gate import order_gate
    return await order_gate.submit(signal, approved_by=approved_by)


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
        # All risk gating now lives in the single order gate — no duplicate
        # guardrail block here (kill switch + unified risk run inside the gate).
        result = await _execute_signal(signal, approved_by="autopilot")
        _execution_log.insert(0, result)
        del _execution_log[200:]
