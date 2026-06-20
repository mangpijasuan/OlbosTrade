"""Strategy config and signal routes."""
from __future__ import annotations

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
    """Return enabled strategies from current trading mode."""
    try:
        from app.services.trading_mode import trading_mode_manager
        state = trading_mode_manager.current
        mode_name = state.active_mode.value
        allowed = trading_mode_manager.config.summary()["strategies_allowed"]
        return {
            "strategies": [
                {"name": s, "enabled": allowed.get(s, False)}
                for s in ["bull_put_spread", "bear_call_spread", "iron_condor", "bull_call_debit_spread"]
            ],
            "mode": mode_name,
        }
    except Exception:
        return {
            "strategies": [
                {"name": "bull_put_spread",      "enabled": True},
                {"name": "bear_call_spread",     "enabled": True},
                {"name": "iron_condor",          "enabled": True},
                {"name": "bull_call_debit_spread","enabled": True},
            ]
        }


@router.put("/config")
async def update_strategy_config(config: StrategyConfig):
    return {"updated": True, "strategy": config.strategy,
            "message": "Use /api/mode/set to change the active trading mode and strategy set."}


@router.get("/signals/current")
async def get_current_signals():
    """Returns current options signals from regime-gated strategy list."""
    from datetime import datetime, timezone

    signals = []

    try:
        from app.main import _current_regime
        if _current_regime and _current_regime.options_allowed:
            for strategy in _current_regime.strategies_allowed:
                signals.append({
                    "type":       "options",
                    "strategy":   strategy,
                    "underlying": "SPY",
                    "action":     "EVALUATE",
                    "confidence": _current_regime.confidence,
                    "generated_at": _current_regime.classified_at.isoformat(),
                    "regime":     _current_regime.regime.value,
                    "size_multiplier": _current_regime.options_size_multiplier,
                })
    except Exception:
        pass

    return {
        "signals":      signals,
        "total":        len(signals),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/signals/{signal_id}/explanation")
async def get_signal_explanation(signal_id: str):
    """Signal explainability is provided via trade desk execution log and journal."""
    return {
        "signal_id": signal_id,
        "explanation": None,
        "message": "Use trade desk execution log or journal for signal details.",
    }
