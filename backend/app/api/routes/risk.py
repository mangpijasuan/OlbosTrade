"""
Risk monitoring routes.
FIX #11: Kill switch route now fully implemented — cancels orders, flattens positions.
"""
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

from app.core.config import settings
from app.services.kill_switch import kill_switch_service


def _require_api_key(x_api_key: str = Header(default="")) -> None:
    """Require X-Api-Key header to match settings.secret_key for admin endpoints."""
    if not settings.secret_key:
        raise HTTPException(
            status_code=503,
            detail="SECRET_KEY not configured — admin endpoints are disabled",
        )
    if x_api_key != settings.secret_key:
        raise HTTPException(status_code=403, detail="Invalid API key")

router = APIRouter()


class KillSwitchResetRequest(BaseModel):
    authorization_code: str


@router.get("/portfolio-state")
async def get_portfolio_state():
    return {"state": {}}


@router.get("/approval/{trade_id}")
async def get_trade_approval(trade_id: str):
    return {"trade_id": trade_id, "approved": False, "reason": "pending"}


@router.get("/daily-pnl")
async def get_daily_pnl():
    return {"daily_pnl": 0, "daily_pnl_pct": 0}


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
