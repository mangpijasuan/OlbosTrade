"""Strategy registry, config, and signal routes."""
from __future__ import annotations

from typing import Any, Dict, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.services.strategy_config_service import (
    compare_snapshots,
    serialize_preset,
    serialize_snapshot,
    strategy_config_service,
)
from app.services.strategy_registry import (
    serialize_strategy_profile,
    strategy_registry_service,
)

router = APIRouter()


class StrategyConfig(BaseModel):
    strategy: str
    enabled: bool
    signal_threshold: Optional[float] = None


class SnapshotCreateRequest(BaseModel):
    strategy_id: str
    preset_id: Optional[str] = None
    label: str
    notes: Optional[str] = None
    risk_profile: str = "balanced"
    lifecycle_status: str = "paper_validated"
    validation_status: str = "custom"
    config_payload: Dict[str, Any]
    created_by: str = "operator"
    activate: bool = True


@router.get("/registry")
async def get_strategy_registry(session: AsyncSession = Depends(get_async_session)):
    profiles = await strategy_registry_service.list_profiles(session)
    await strategy_config_service.ensure_seeded(session)
    return {
        "strategies": [serialize_strategy_profile(p) for p in profiles],
        "total": len(profiles),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/registry/{strategy_id}")
async def get_strategy_profile(
    strategy_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    profile = await strategy_registry_service.get_profile(session, strategy_id)
    if profile is None:
        raise HTTPException(404, "Strategy not found")
    return {"strategy": serialize_strategy_profile(profile)}


@router.get("/presets")
async def get_strategy_presets(
    strategy_id: Optional[str] = None,
    session: AsyncSession = Depends(get_async_session),
):
    presets = await strategy_config_service.list_presets(session, strategy_id=strategy_id)
    return {"presets": [serialize_preset(p) for p in presets], "total": len(presets)}


@router.get("/{strategy_id}/presets")
async def get_strategy_presets_for_strategy(
    strategy_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    presets = await strategy_config_service.list_presets(session, strategy_id=strategy_id)
    return {"presets": [serialize_preset(p) for p in presets], "total": len(presets)}


@router.get("/{strategy_id}/snapshots")
async def get_strategy_snapshots(
    strategy_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    snapshots = await strategy_config_service.list_snapshots(session, strategy_id)
    serialized = []
    for snapshot in snapshots:
        preset = await strategy_config_service.get_preset_for_snapshot(session, snapshot)
        serialized.append(serialize_snapshot(snapshot, preset))
    return {"snapshots": serialized, "total": len(serialized)}


@router.post("/snapshots", status_code=201)
async def create_strategy_snapshot(
    body: SnapshotCreateRequest,
    session: AsyncSession = Depends(get_async_session),
):
    snapshot = await strategy_config_service.create_snapshot(
        session,
        strategy_id=body.strategy_id,
        preset_key=body.preset_id,
        label=body.label,
        notes=body.notes,
        risk_profile=body.risk_profile,
        lifecycle_status=body.lifecycle_status,
        validation_status=body.validation_status,
        config_payload=body.config_payload,
        created_by=body.created_by,
        activate=body.activate,
    )
    preset = await strategy_config_service.get_preset_for_snapshot(session, snapshot)
    return {"snapshot": serialize_snapshot(snapshot, preset)}


@router.post("/snapshots/{snapshot_id}/restore")
async def restore_strategy_snapshot(
    snapshot_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    snapshot = await strategy_config_service.restore_snapshot(session, snapshot_id)
    if snapshot is None:
        raise HTTPException(404, "Snapshot not found")
    preset = await strategy_config_service.get_preset_for_snapshot(session, snapshot)
    return {"restored": True, "snapshot": serialize_snapshot(snapshot, preset)}


@router.get("/snapshots/compare")
async def compare_strategy_snapshots(
    left: str,
    right: str,
    session: AsyncSession = Depends(get_async_session),
):
    left_snapshot = await strategy_config_service.get_snapshot(session, left)
    right_snapshot = await strategy_config_service.get_snapshot(session, right)
    if left_snapshot is None or right_snapshot is None:
        raise HTTPException(404, "One or both snapshots not found")
    return {
        "left": serialize_snapshot(left_snapshot),
        "right": serialize_snapshot(right_snapshot),
        "diff": compare_snapshots(left_snapshot, right_snapshot),
    }


@router.get("/config")
async def get_strategy_config(session: AsyncSession = Depends(get_async_session)):
    """Return lifecycle-aware strategy cards for the Strategy page."""
    profiles = await strategy_registry_service.list_profiles(session)
    return {
        "strategies": [serialize_strategy_profile(p) for p in profiles],
        "mode": "registry",
    }


@router.put("/config")
async def update_strategy_config(config: StrategyConfig):
    return {
        "updated": True,
        "strategy": config.strategy,
        "message": (
            "Lifecycle-aware registry is active. Snapshot editing and per-strategy "
            "configuration writes are part of the next module."
        ),
    }


@router.get("/signals/current")
async def get_current_signals(session: AsyncSession = Depends(get_async_session)):
    """
    Returns current actionable signals:
    - Equity signals from the equity scan engine (BUY/SELL above confidence threshold)
    - Options signals from regime-gated strategy list enriched with lifecycle metadata
    """
    from app.core.config import settings

    profiles = {
        p.strategy_id: serialize_strategy_profile(p)
        for p in await strategy_registry_service.list_profiles(session)
    }
    signals = []

    try:
        from app.api.routes.equity import _recent_signals
        from app.main import _current_regime

        min_conf = settings.equity_min_confidence
        equity_sigs = [
            s for s in _recent_signals
            if s.get("action") in ("BUY", "SELL")
            and s.get("confidence", 0) >= min_conf
        ][:5]

        equity_profile = profiles.get("equity_signal")
        for s in equity_sigs:
            signals.append({
                "type": "equity",
                "ticker": s["ticker"],
                "action": s["action"],
                "confidence": s["confidence"],
                "generated_at": s["generated_at"],
                "trade_plan": s.get("trade_plan", {}),
                "indicators": s.get("indicators", {}),
                "regime_gated": _current_regime.equity_allowed if _current_regime else False,
                "strategy_profile": equity_profile,
            })
    except Exception:
        pass

    try:
        from app.main import _current_regime
        if _current_regime and _current_regime.options_allowed:
            for strategy_id in _current_regime.strategies_allowed:
                signals.append({
                    "type": "options",
                    "strategy": strategy_id,
                    "underlying": "SPY",
                    "action": "EVALUATE",
                    "confidence": _current_regime.confidence,
                    "generated_at": _current_regime.classified_at.isoformat(),
                    "regime": _current_regime.regime.value,
                    "size_multiplier": _current_regime.options_size_multiplier,
                    "strategy_profile": profiles.get(strategy_id),
                })
    except Exception:
        pass

    return {
        "signals": signals,
        "total": len(signals),
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
            "signal_id": signal_id,
            "ticker": sig["ticker"],
            "action": sig["action"],
            "confidence": sig["confidence"],
            "explanation": {
                "reasons": sig.get("reasons", {}),
                "indicators": sig.get("indicators", {}),
                "orderflow_score": sig.get("orderflow_score"),
                "iv_boost": sig.get("iv_overlay_boost"),
                "earnings_gated": sig.get("earnings_gated"),
            },
        }
    except Exception as exc:
        return {"signal_id": signal_id, "explanation": None, "error": str(exc)}


async def _evaluate_health(min_sample: int):
    """Shared loader: grade every strategy from closed trades + promoted baselines."""
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.trade import Trade
    from app.models.research_experiment import ResearchExperiment
    from app.services.research_lab import baselines_from_experiments, PROMOTED
    from app.services.strategy_health import evaluate_all
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        trades = (await session.execute(
            select(Trade).where(Trade.status == "closed", Trade.pnl.isnot(None))
        )).scalars().all()
        promoted = (await session.execute(
            select(ResearchExperiment).where(ResearchExperiment.stage == PROMOTED)
        )).scalars().all()
        overrides = baselines_from_experiments([e.as_dict() for e in promoted])

    by_strategy: dict[str, list[dict]] = {}
    for t in trades:
        by_strategy.setdefault(str(t.strategy), []).append(
            {"pnl": float(t.pnl), "entry_date": t.entry_date, "exit_date": t.exit_date}
        )
    return evaluate_all(by_strategy, settings.starting_capital,
                        overrides=overrides, min_sample=min_sample)


@router.get("/health")
async def get_strategy_health(min_sample: int = 20):
    """
    Per-strategy health: live win rate / expectancy / drawdown vs. baseline, a
    0–100 score, a degradation grade (healthy / watch / degraded /
    insufficient_data), and a recommended action. Suspended strategies accept no
    new entries.
    """
    try:
        health = await _evaluate_health(min_sample)
    except Exception as exc:
        return {"strategies": [], "error": str(exc)}
    suspended = [h.strategy for h in health if h.status == "degraded"]
    return {
        "strategies": [h.as_dict() for h in health],
        "suspended": suspended,
        "total_strategies": len(health),
    }


@router.get("/meta")
async def get_meta_strategy(min_sample: int = 20):
    """
    Meta-strategy decisions: given the active regime + each strategy's health,
    which strategies are active and at what allocation tilt. Feeds the Capital
    Allocation Engine.
    """
    from app.services.meta_strategy import decide, active_strategies
    try:
        health = await _evaluate_health(min_sample)
    except Exception as exc:
        return {"regime": None, "decisions": [], "error": str(exc)}

    from app.main import _current_regime
    regime = getattr(getattr(_current_regime, "regime", None), "value", None) or "unknown"
    decisions = decide(regime, [h.as_dict() for h in health])
    return {
        "regime": regime,
        "decisions": [d.as_dict() for d in decisions],
        "active_strategies": active_strategies(decisions),
        "total": len(decisions),
    }
