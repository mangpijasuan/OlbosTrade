"""Strategy config and signal routes."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class StrategyConfig(BaseModel):
    strategy: str
    enabled: bool
    signal_threshold: Optional[float] = None


@router.get("/config")
async def get_strategy_config():
    return {
        "strategies": [
            {"name": "bull_put_spread", "enabled": True},
            {"name": "bear_call_spread", "enabled": True},
            {"name": "iron_condor", "enabled": True},
            {"name": "bull_call_debit_spread", "enabled": True},
        ]
    }


@router.put("/config")
async def update_strategy_config(config: StrategyConfig):
    return {"updated": True, "strategy": config.strategy}


@router.get("/signals/current")
async def get_current_signals():
    return {"signals": [], "generated_at": None}


@router.get("/signals/{signal_id}/explanation")
async def get_signal_explanation(signal_id: str):
    return {"signal_id": signal_id, "explanation": {}}
