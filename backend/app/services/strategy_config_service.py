"""
Verified strategy preset and snapshot service.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_preset import StrategyPreset
from app.models.strategy_snapshot import StrategySnapshot


@dataclass(frozen=True)
class PresetSeed:
    preset_id: str
    strategy_id: str
    category: str
    preset_name: str
    version: str
    market_regime_requirements: List[str]
    volatility_requirements: List[str]
    timeframe: str
    entry_rules: Dict[str, Any]
    exit_rules: Dict[str, Any]
    risk_rules: Dict[str, Any]
    position_sizing_policy: Dict[str, Any]
    confidence_threshold: float
    event_risk_restrictions: List[str]
    max_allocation_pct: float
    risk_profile_compatibility: List[str]
    validation_status: str
    paper_validated: bool
    live_validated: bool
    author: str
    approval_owner: str
    approval_notes: str
    approved_at: date


PRESET_SEEDS = (
    PresetSeed(
        preset_id="options_income_bull_put_v1",
        strategy_id="bull_put_spread",
        category="Options Income",
        preset_name="Bull Put Spread",
        version="1.0.0",
        market_regime_requirements=["low_vol_trending", "normal_mean_revert"],
        volatility_requirements=["moderate", "elevated"],
        timeframe="30-45 DTE",
        entry_rules={"short_delta_max": 0.30, "min_credit_to_width": 0.2, "min_iv_rank": 30},
        exit_rules={"profit_target_pct": 0.5, "stop_loss_multiple": 2.0, "dte_exit": 21},
        risk_rules={"defined_risk_only": True, "earnings_blackout_days": 7},
        position_sizing_policy={"risk_per_trade_pct": 0.02, "sizing_model": "vol_adjusted"},
        confidence_threshold=0.65,
        event_risk_restrictions=["avoid_new_short_premium_before_cpi", "avoid_fomc_window"],
        max_allocation_pct=0.08,
        risk_profile_compatibility=["conservative", "balanced", "aggressive"],
        validation_status="paper_validated",
        paper_validated=True,
        live_validated=False,
        author="OlbosTrade",
        approval_owner="Risk Committee",
        approval_notes="Verified baseline income preset.",
        approved_at=date(2026, 6, 28),
    ),
    PresetSeed(
        preset_id="options_income_bear_call_v1",
        strategy_id="bear_call_spread",
        category="Options Income",
        preset_name="Bear Call Spread",
        version="1.0.0",
        market_regime_requirements=["normal_mean_revert", "high_vol_trending"],
        volatility_requirements=["moderate", "elevated"],
        timeframe="21-35 DTE",
        entry_rules={"short_delta_max": 0.28, "min_credit_to_width": 0.2, "min_iv_rank": 30},
        exit_rules={"profit_target_pct": 0.5, "stop_loss_multiple": 1.8, "dte_exit": 14},
        risk_rules={"defined_risk_only": True, "macro_gate_required": True},
        position_sizing_policy={"risk_per_trade_pct": 0.02, "sizing_model": "vol_adjusted"},
        confidence_threshold=0.67,
        event_risk_restrictions=["avoid_naked_short_vol", "avoid_fomc_window"],
        max_allocation_pct=0.08,
        risk_profile_compatibility=["conservative", "balanced", "aggressive"],
        validation_status="live_validated",
        paper_validated=True,
        live_validated=True,
        author="OlbosTrade",
        approval_owner="Risk Committee",
        approval_notes="Current highest-confidence autopilot baseline.",
        approved_at=date(2026, 6, 29),
    ),
    PresetSeed(
        preset_id="options_directional_bull_call_v1",
        strategy_id="bull_call_debit_spread",
        category="Options Directional",
        preset_name="Bull Call Spread",
        version="1.0.0",
        market_regime_requirements=["low_vol_trending", "high_vol_trending"],
        volatility_requirements=["subdued", "moderate"],
        timeframe="14-30 DTE",
        entry_rules={"trend_confirmation": True, "breakout_required": True},
        exit_rules={"profit_target_pct": 0.75, "stop_loss_multiple": 1.0, "dte_exit": 10},
        risk_rules={"event_blackout_days": 3, "gap_risk_buffer": True},
        position_sizing_policy={"risk_per_trade_pct": 0.015, "sizing_model": "conviction_weighted"},
        confidence_threshold=0.68,
        event_risk_restrictions=["avoid_earnings_week"],
        max_allocation_pct=0.06,
        risk_profile_compatibility=["balanced", "aggressive"],
        validation_status="paper_validated",
        paper_validated=True,
        live_validated=False,
        author="OlbosTrade",
        approval_owner="Research",
        approval_notes="Directional debit preset pending live validation.",
        approved_at=date(2026, 6, 27),
    ),
    PresetSeed(
        preset_id="equity_etf_rotation_v1",
        strategy_id="equity_signal",
        category="Equity and ETF",
        preset_name="ETF Rotation",
        version="1.0.0",
        market_regime_requirements=["low_vol_trending", "high_vol_trending"],
        volatility_requirements=["subdued", "moderate"],
        timeframe="swing_2_10_days",
        entry_rules={"top_relative_strength": 3, "sector_leadership_required": True},
        exit_rules={"trail_atr_multiple": 2.0, "time_stop_days": 10},
        risk_rules={"correlation_cap": 2, "earnings_blackout_days": 5},
        position_sizing_policy={"risk_per_trade_pct": 0.01, "sizing_model": "heat_budget"},
        confidence_threshold=0.70,
        event_risk_restrictions=["avoid_cpi_open", "avoid_fomc_window"],
        max_allocation_pct=0.10,
        risk_profile_compatibility=["balanced", "aggressive"],
        validation_status="limited_live_validation",
        paper_validated=True,
        live_validated=False,
        author="OlbosTrade",
        approval_owner="Research",
        approval_notes="Validated in paper and being tracked in limited live workflow.",
        approved_at=date(2026, 6, 30),
    ),
)


def _payload_from_seed(seed: PresetSeed) -> Dict[str, Any]:
    return {
        "preset_id": seed.preset_id,
        "timeframe": seed.timeframe,
        "entry_rules": seed.entry_rules,
        "exit_rules": seed.exit_rules,
        "risk_rules": seed.risk_rules,
        "position_sizing_policy": seed.position_sizing_policy,
        "confidence_threshold": seed.confidence_threshold,
        "event_risk_restrictions": seed.event_risk_restrictions,
        "max_allocation_pct": seed.max_allocation_pct,
        "market_regime_requirements": seed.market_regime_requirements,
        "volatility_requirements": seed.volatility_requirements,
    }


def serialize_preset(preset: StrategyPreset) -> Dict[str, Any]:
    return {
        "preset_id": preset.preset_id,
        "strategy_id": preset.strategy_id,
        "category": preset.category,
        "preset_name": preset.preset_name,
        "version": preset.version,
        "market_regime_requirements": preset.market_regime_requirements,
        "volatility_requirements": preset.volatility_requirements,
        "timeframe": preset.timeframe,
        "entry_rules": preset.entry_rules,
        "exit_rules": preset.exit_rules,
        "risk_rules": preset.risk_rules,
        "position_sizing_policy": preset.position_sizing_policy,
        "confidence_threshold": preset.confidence_threshold,
        "event_risk_restrictions": preset.event_risk_restrictions,
        "max_allocation_pct": preset.max_allocation_pct,
        "risk_profile_compatibility": preset.risk_profile_compatibility,
        "validation_status": preset.validation_status,
        "paper_validated": preset.paper_validated,
        "live_validated": preset.live_validated,
        "author": preset.author,
        "approval_owner": preset.approval_owner,
        "approval_notes": preset.approval_notes,
        "approved_at": preset.approved_at.isoformat() if preset.approved_at else None,
        "enabled": preset.enabled,
    }


def serialize_snapshot(snapshot: StrategySnapshot, preset: Optional[StrategyPreset] = None) -> Dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "strategy_id": snapshot.strategy_id,
        "preset_id": preset.preset_id if preset else None,
        "version": snapshot.version,
        "label": snapshot.label,
        "notes": snapshot.notes,
        "risk_profile": snapshot.risk_profile,
        "lifecycle_status": snapshot.lifecycle_status,
        "validation_status": snapshot.validation_status,
        "config_payload": snapshot.config_payload,
        "is_active": snapshot.is_active,
        "inherited_from_verified_preset": snapshot.inherited_from_verified_preset,
        "created_by": snapshot.created_by,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
    }


def compare_snapshots(left: StrategySnapshot, right: StrategySnapshot) -> Dict[str, Any]:
    diff = {}
    left_payload = left.config_payload or {}
    right_payload = right.config_payload or {}
    keys = sorted(set(left_payload.keys()) | set(right_payload.keys()))
    for key in keys:
        if left_payload.get(key) != right_payload.get(key):
            diff[key] = {"left": left_payload.get(key), "right": right_payload.get(key)}
    meta = {}
    for field in ("risk_profile", "validation_status", "lifecycle_status", "label"):
        lv = getattr(left, field)
        rv = getattr(right, field)
        if lv != rv:
            meta[field] = {"left": lv, "right": rv}
    return {"config_diff": diff, "meta_diff": meta}


class StrategyConfigService:
    async def ensure_seeded(self, session: AsyncSession) -> None:
        existing = await session.execute(select(StrategyPreset.preset_id))
        if existing.first():
            return
        preset_models = []
        for seed in PRESET_SEEDS:
            preset = StrategyPreset(
                preset_id=seed.preset_id,
                strategy_id=seed.strategy_id,
                category=seed.category,
                preset_name=seed.preset_name,
                version=seed.version,
                market_regime_requirements=seed.market_regime_requirements,
                volatility_requirements=seed.volatility_requirements,
                timeframe=seed.timeframe,
                entry_rules=seed.entry_rules,
                exit_rules=seed.exit_rules,
                risk_rules=seed.risk_rules,
                position_sizing_policy=seed.position_sizing_policy,
                confidence_threshold=seed.confidence_threshold,
                event_risk_restrictions=seed.event_risk_restrictions,
                max_allocation_pct=seed.max_allocation_pct,
                risk_profile_compatibility=seed.risk_profile_compatibility,
                validation_status=seed.validation_status,
                paper_validated=seed.paper_validated,
                live_validated=seed.live_validated,
                author=seed.author,
                approval_owner=seed.approval_owner,
                approval_notes=seed.approval_notes,
                approved_at=seed.approved_at,
                enabled=True,
            )
            session.add(preset)
            preset_models.append((seed, preset))
        await session.flush()
        for seed, preset in preset_models:
            session.add(
                StrategySnapshot(
                    snapshot_id=f"{seed.strategy_id}.baseline.v1",
                    strategy_id=seed.strategy_id,
                    preset_id=preset.id,
                    version=seed.version,
                    label=f"{seed.preset_name} Verified Baseline",
                    notes=f"Seeded from verified preset {seed.preset_id}",
                    risk_profile=(seed.risk_profile_compatibility[0] if seed.risk_profile_compatibility else "balanced"),
                    lifecycle_status=seed.validation_status,
                    validation_status=seed.validation_status,
                    config_payload=_payload_from_seed(seed),
                    is_active=True,
                    inherited_from_verified_preset=True,
                    created_by="OlbosTrade",
                )
            )
        await session.flush()

    async def list_presets(self, session: AsyncSession, strategy_id: Optional[str] = None) -> List[StrategyPreset]:
        await self.ensure_seeded(session)
        stmt = select(StrategyPreset).order_by(StrategyPreset.category, StrategyPreset.preset_name)
        if strategy_id:
            stmt = stmt.where(StrategyPreset.strategy_id == strategy_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_snapshots(self, session: AsyncSession, strategy_id: str) -> List[StrategySnapshot]:
        await self.ensure_seeded(session)
        result = await session.execute(
            select(StrategySnapshot)
            .where(StrategySnapshot.strategy_id == strategy_id)
            .order_by(StrategySnapshot.is_active.desc(), StrategySnapshot.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_snapshot(self, session: AsyncSession, snapshot_id: str) -> Optional[StrategySnapshot]:
        await self.ensure_seeded(session)
        result = await session.execute(
            select(StrategySnapshot).where(StrategySnapshot.snapshot_id == snapshot_id)
        )
        return result.scalar_one_or_none()

    async def get_active_snapshot(self, session: AsyncSession, strategy_id: str) -> Optional[StrategySnapshot]:
        await self.ensure_seeded(session)
        result = await session.execute(
            select(StrategySnapshot)
            .where(StrategySnapshot.strategy_id == strategy_id, StrategySnapshot.is_active.is_(True))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_snapshot(
        self,
        session: AsyncSession,
        *,
        strategy_id: str,
        preset_key: Optional[str],
        label: str,
        notes: Optional[str],
        risk_profile: str,
        lifecycle_status: str,
        validation_status: str,
        config_payload: Dict[str, Any],
        created_by: str,
        activate: bool,
    ) -> StrategySnapshot:
        await self.ensure_seeded(session)
        preset_model = None
        inherited = False
        if preset_key:
            preset_result = await session.execute(
                select(StrategyPreset).where(StrategyPreset.preset_id == preset_key)
            )
            preset_model = preset_result.scalar_one_or_none()
            inherited = preset_model is not None
        if activate:
            await self._deactivate_snapshots(session, strategy_id)
        snap = StrategySnapshot(
            snapshot_id=f"{strategy_id}.{uuid.uuid4().hex[:12]}",
            strategy_id=strategy_id,
            preset_id=preset_model.id if preset_model else None,
            version="1.0.0",
            label=label,
            notes=notes,
            risk_profile=risk_profile,
            lifecycle_status=lifecycle_status,
            validation_status=validation_status,
            config_payload=config_payload,
            is_active=activate,
            inherited_from_verified_preset=inherited,
            created_by=created_by,
        )
        session.add(snap)
        await session.flush()
        return snap

    async def restore_snapshot(self, session: AsyncSession, snapshot_id: str) -> Optional[StrategySnapshot]:
        snapshot = await self.get_snapshot(session, snapshot_id)
        if snapshot is None:
            return None
        await self._deactivate_snapshots(session, snapshot.strategy_id)
        snapshot.is_active = True
        await session.flush()
        return snapshot

    async def get_preset_for_snapshot(
        self, session: AsyncSession, snapshot: StrategySnapshot
    ) -> Optional[StrategyPreset]:
        if snapshot.preset_id is None:
            return None
        result = await session.execute(select(StrategyPreset).where(StrategyPreset.id == snapshot.preset_id))
        return result.scalar_one_or_none()

    async def _deactivate_snapshots(self, session: AsyncSession, strategy_id: str) -> None:
        result = await session.execute(
            select(StrategySnapshot).where(StrategySnapshot.strategy_id == strategy_id)
        )
        for row in result.scalars().all():
            row.is_active = False
        await session.flush()


strategy_config_service = StrategyConfigService()
