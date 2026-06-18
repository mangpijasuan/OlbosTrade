"""Strategy config and signal routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from app.api.auth import require_admin_api_key

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
        state = trading_mode_manager.current          # TradingModeState
        mode_name = state.active_mode.value if hasattr(state, "active_mode") else "balanced"
        allowed = getattr(state, "strategies_allowed", {}) or {}
        return {
            "strategies": [
                {"name": s, "enabled": allowed.get(s, True) if isinstance(allowed, dict) else True}
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


@router.put("/config", dependencies=[Depends(require_admin_api_key)])
async def update_strategy_config(config: StrategyConfig):
    return {"updated": True, "strategy": config.strategy,
            "message": "Use /api/mode/set to change the active trading mode and strategy set."}


@router.get("/signals/current")
async def get_current_signals():
    """
    Returns current actionable signals:
    - Equity signals from the equity scan engine (BUY/SELL above confidence threshold)
    - Options signals from regime-gated strategy list
    """
    from datetime import datetime, timezone
    from app.core.config import settings

    signals = []

    # ── Equity signals ────────────────────────────────────────────────────────
    try:
        from app.api.routes.equity import _recent_signals
        from app.main import _current_regime

        min_conf = settings.equity_min_confidence
        equity_sigs = [
            s for s in _recent_signals
            if s.get("action") in ("BUY", "SELL")
            and s.get("confidence", 0) >= min_conf
        ][:5]

        for s in equity_sigs:
            signals.append({
                "type":        "equity",
                "ticker":      s["ticker"],
                "action":      s["action"],
                "confidence":  s["confidence"],
                "generated_at": s["generated_at"],
                "trade_plan":  s.get("trade_plan", {}),
                "indicators":  s.get("indicators", {}),
                "regime_gated": _current_regime.equity_allowed if _current_regime else False,
            })
    except Exception:
        pass

    # ── Options signals ───────────────────────────────────────────────────────
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


@router.get("/options-recommendations")
async def get_options_recommendations(
    symbols: str = "",
    limit: int = 5,
):
    """
    Return ranked option buying setups with strikes, DTE, risk, and rationale.

    Uses live IBKR option-chain mids when connected. If the chain is unavailable,
    it still returns estimated setups from yfinance technicals so the UI always
    shows the intended strikes/DTE and can be reviewed before execution.
    """
    from app.broker.broker_factory import get_broker
    from app.services.options_recommender import OptionsSetupRecommender

    parsed = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None
    safe_limit = max(1, min(limit, 10))
    try:
        broker = get_broker()
    except Exception:
        broker = None
    recommender = OptionsSetupRecommender(broker=broker)
    return await recommender.recommend(symbols=parsed, limit=safe_limit)


@router.get("/signals/{signal_id}/explanation")
async def get_signal_explanation(signal_id: str):
    """Explain the reasoning behind an equity signal."""
    try:
        from app.api.routes.equity import _recent_signals
        sig = next((s for s in _recent_signals if s.get("id") == signal_id), None)
        if not sig:
            return {"signal_id": signal_id, "explanation": None, "error": "Signal not found"}
        return {
            "signal_id":   signal_id,
            "ticker":      sig["ticker"],
            "action":      sig["action"],
            "confidence":  sig["confidence"],
            "explanation": {
                "reasons":         sig.get("reasons", {}),
                "indicators":      sig.get("indicators", {}),
                "orderflow_score": sig.get("orderflow_score"),
                "iv_boost":        sig.get("iv_overlay_boost"),
                "earnings_gated":  sig.get("earnings_gated"),
            },
        }
    except Exception as exc:
        return {"signal_id": signal_id, "explanation": None, "error": str(exc)}
