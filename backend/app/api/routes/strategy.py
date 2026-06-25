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


@router.put("/config")
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


@router.get("/health")
async def get_strategy_health(min_sample: int = 20):
    """
    Per-strategy health: live win rate / expectancy / drawdown vs. baseline, with
    a degradation grade (healthy / watch / degraded / insufficient_data) and a
    recommended action. Suspended strategies should accept no new entries.
    """
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.trade import Trade
    from app.services.strategy_health import evaluate_all
    from sqlalchemy import select

    try:
        async with AsyncSessionLocal() as session:
            trades = (await session.execute(
                select(Trade).where(Trade.status == "closed", Trade.pnl.isnot(None))
            )).scalars().all()
    except Exception as exc:
        return {"strategies": [], "error": str(exc)}

    by_strategy: dict[str, list[dict]] = {}
    for t in trades:
        by_strategy.setdefault(str(t.strategy), []).append(
            {"pnl": float(t.pnl), "entry_date": t.entry_date, "exit_date": t.exit_date}
        )

    health = evaluate_all(by_strategy, settings.starting_capital, min_sample=min_sample)
    suspended = [h.strategy for h in health if h.status == "degraded"]
    return {
        "strategies": [h.as_dict() for h in health],
        "suspended": suspended,
        "total_strategies": len(health),
    }
