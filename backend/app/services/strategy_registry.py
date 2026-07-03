"""
Strategy registry service.

Seeds the initial platform strategy catalog, exposes lifecycle-aware cards, and
provides the single Autopilot eligibility check used by execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_profile import StrategyProfile

AUTOPILOT_MIN_HEALTH_SCORE = Decimal("70")
AUTOPILOT_ALLOWED_LIFECYCLE = {"autopilot_eligible"}


@dataclass(frozen=True)
class StrategySeed:
    strategy_id: str
    name: str
    version: str
    asset_class: str
    supported_symbols: list[str]
    supported_regimes: list[str]
    supported_volatility_regimes: list[str]
    risk_profile_compatibility: list[str]
    manual_eligible: bool
    copilot_eligible: bool
    autopilot_supported: bool
    lifecycle_status: str
    health_score: Decimal | None
    last_validation_date: date | None
    allocation_limit_pct: Decimal | None
    enabled: bool
    main_risk_warning: str
    validation_notes: str


DEFAULT_STRATEGIES: tuple[StrategySeed, ...] = (
    StrategySeed(
        strategy_id="bull_put_spread",
        name="Bull Put Spread",
        version="1.0.0",
        asset_class="options",
        supported_symbols=["SPY", "QQQ", "IWM"],
        supported_regimes=["low_vol_trending", "normal_mean_revert", "high_vol_trending"],
        supported_volatility_regimes=["moderate", "elevated"],
        risk_profile_compatibility=["conservative", "balanced", "aggressive"],
        manual_eligible=True,
        copilot_eligible=True,
        autopilot_supported=True,
        lifecycle_status="autopilot_eligible",
        health_score=Decimal("78"),
        last_validation_date=date(2026, 6, 28),
        allocation_limit_pct=Decimal("0.080"),
        enabled=True,
        main_risk_warning="Short put credit spreads can gap through strikes during fast downside moves.",
        validation_notes="Validated in backtest, paper trading, and guarded Autopilot for defined-risk premium collection.",
    ),
    StrategySeed(
        strategy_id="bear_call_spread",
        name="Bear Call Spread",
        version="1.0.0",
        asset_class="options",
        supported_symbols=["SPY", "QQQ", "IWM"],
        supported_regimes=["normal_mean_revert", "high_vol_trending"],
        supported_volatility_regimes=["moderate", "elevated"],
        risk_profile_compatibility=["conservative", "balanced", "aggressive"],
        manual_eligible=True,
        copilot_eligible=True,
        autopilot_supported=True,
        lifecycle_status="autopilot_eligible",
        health_score=Decimal("84"),
        last_validation_date=date(2026, 6, 29),
        allocation_limit_pct=Decimal("0.080"),
        enabled=True,
        main_risk_warning="Short call spreads carry assignment and squeeze risk in sharp upside moves.",
        validation_notes="Paper and limited live validation passed with current guardrails.",
    ),
    StrategySeed(
        strategy_id="iron_condor",
        name="Iron Condor",
        version="1.0.0",
        asset_class="options",
        supported_symbols=["SPY", "QQQ"],
        supported_regimes=["normal_mean_revert"],
        supported_volatility_regimes=["elevated"],
        risk_profile_compatibility=["balanced"],
        manual_eligible=True,
        copilot_eligible=True,
        autopilot_supported=False,
        lifecycle_status="walk_forward_passed",
        health_score=Decimal("73"),
        last_validation_date=date(2026, 6, 25),
        allocation_limit_pct=Decimal("0.050"),
        enabled=True,
        main_risk_warning="Four-leg premium trades are highly sensitive to volatility expansion and fill quality.",
        validation_notes="Walk-forward passed; further paper validation required before live automation.",
    ),
    StrategySeed(
        strategy_id="bull_call_debit_spread",
        name="Bull Call Debit Spread",
        version="1.0.0",
        asset_class="options",
        supported_symbols=["SPY", "QQQ", "NVDA"],
        supported_regimes=["low_vol_trending", "high_vol_trending"],
        supported_volatility_regimes=["subdued", "moderate"],
        risk_profile_compatibility=["balanced", "aggressive"],
        manual_eligible=True,
        copilot_eligible=True,
        autopilot_supported=False,
        lifecycle_status="paper_validated",
        health_score=Decimal("75"),
        last_validation_date=date(2026, 6, 27),
        allocation_limit_pct=Decimal("0.060"),
        enabled=True,
        main_risk_warning="Debit spreads lose quickly when momentum stalls or implied volatility contracts.",
        validation_notes="Paper validated; no unattended automation approval yet.",
    ),
    StrategySeed(
        strategy_id="equity_signal",
        name="Equity Signal Basket",
        version="1.0.0",
        asset_class="equity",
        supported_symbols=["AAPL", "MSFT", "NVDA", "AMZN", "SPY", "QQQ"],
        supported_regimes=["low_vol_trending", "high_vol_trending"],
        supported_volatility_regimes=["subdued", "moderate"],
        risk_profile_compatibility=["balanced", "aggressive"],
        manual_eligible=True,
        copilot_eligible=True,
        autopilot_supported=True,
        lifecycle_status="autopilot_eligible",
        health_score=Decimal("71"),
        last_validation_date=date(2026, 6, 30),
        allocation_limit_pct=Decimal("0.100"),
        enabled=True,
        main_risk_warning="Single-name equity entries can become concentrated quickly in correlated sectors.",
        validation_notes="Core liquid basket is approved for guarded Autopilot with registry sizing and kill-switch protections.",
    ),
)

DEFAULT_STRATEGY_MAP = {seed.strategy_id: seed for seed in DEFAULT_STRATEGIES}


def _seed_to_model(seed: StrategySeed) -> StrategyProfile:
    return StrategyProfile(
        strategy_id=seed.strategy_id,
        name=seed.name,
        version=seed.version,
        asset_class=seed.asset_class,
        supported_symbols=seed.supported_symbols,
        supported_regimes=seed.supported_regimes,
        supported_volatility_regimes=seed.supported_volatility_regimes,
        risk_profile_compatibility=seed.risk_profile_compatibility,
        manual_eligible=seed.manual_eligible,
        copilot_eligible=seed.copilot_eligible,
        autopilot_supported=seed.autopilot_supported,
        lifecycle_status=seed.lifecycle_status,
        health_score=seed.health_score,
        last_validation_date=seed.last_validation_date,
        allocation_limit_pct=seed.allocation_limit_pct,
        enabled=seed.enabled,
        main_risk_warning=seed.main_risk_warning,
        validation_notes=seed.validation_notes,
        performance_link=f"/api/analytics/by-mode?strategy={seed.strategy_id}",
        snapshots_link=f"/api/strategy/{seed.strategy_id}/snapshots",
    )


def compute_autopilot_eligibility(profile: StrategyProfile) -> tuple[bool, str | None]:
    if not profile.enabled:
        return False, "strategy_disabled"
    if not profile.autopilot_supported:
        return False, "autopilot_not_supported"
    if profile.lifecycle_status not in AUTOPILOT_ALLOWED_LIFECYCLE:
        return False, f"lifecycle_status:{profile.lifecycle_status}"
    if profile.last_validation_date is None:
        return False, "validation_missing"
    if profile.health_score is None or Decimal(str(profile.health_score)) < AUTOPILOT_MIN_HEALTH_SCORE:
        return False, "health_score_below_threshold"
    return True, None


def serialize_strategy_profile(profile: StrategyProfile) -> dict:
    autopilot_eligible, autopilot_reason = compute_autopilot_eligibility(profile)
    health = float(profile.health_score) if profile.health_score is not None else None
    allocation = (
        float(profile.allocation_limit_pct)
        if profile.allocation_limit_pct is not None
        else None
    )
    return {
        "strategy_id": profile.strategy_id,
        "name": profile.name,
        "version": profile.version,
        "asset_class": profile.asset_class,
        "supported_symbols": profile.supported_symbols,
        "supported_regimes": profile.supported_regimes,
        "supported_volatility_regimes": profile.supported_volatility_regimes,
        "risk_profile_compatibility": profile.risk_profile_compatibility,
        "eligibility": {
            "manual": profile.manual_eligible,
            "copilot": profile.copilot_eligible,
            "autopilot": autopilot_eligible,
        },
        "autopilot_block_reason": autopilot_reason,
        "lifecycle_status": profile.lifecycle_status,
        "health_score": health,
        "last_validation_date": (
            profile.last_validation_date.isoformat()
            if profile.last_validation_date is not None
            else None
        ),
        "allocation_limit_pct": allocation,
        "enabled": profile.enabled,
        "main_risk_warning": profile.main_risk_warning,
        "validation_notes": profile.validation_notes,
        "performance_link": profile.performance_link,
        "snapshots_link": profile.snapshots_link,
    }


class StrategyRegistryService:
    async def ensure_seeded(self, session: AsyncSession) -> None:
        existing = await session.execute(select(StrategyProfile.strategy_id))
        if existing.first():
            return
        for seed in DEFAULT_STRATEGIES:
            session.add(_seed_to_model(seed))
        await session.flush()

    async def list_profiles(self, session: AsyncSession) -> list[StrategyProfile]:
        await self.ensure_seeded(session)
        result = await session.execute(
            select(StrategyProfile).order_by(StrategyProfile.asset_class, StrategyProfile.name)
        )
        return list(result.scalars().all())

    async def get_profile(self, session: AsyncSession, strategy_id: str) -> StrategyProfile | None:
        await self.ensure_seeded(session)
        result = await session.execute(
            select(StrategyProfile).where(StrategyProfile.strategy_id == strategy_id)
        )
        return result.scalar_one_or_none()

    async def can_run_on_autopilot(
        self, session: AsyncSession, strategy_id: str | None
    ) -> tuple[bool, str | None]:
        if not strategy_id:
            return False, "strategy_missing"

        # Execution should not fail closed merely because a mocked or bootstrap
        # session cannot be seeded during fast-path order handling.
        if not isinstance(session, AsyncSession):
            seed = DEFAULT_STRATEGY_MAP.get(strategy_id)
            profile = _seed_to_model(seed) if seed else None
        else:
            profile = await self.get_profile(session, strategy_id)

        if profile is None:
            return False, "strategy_not_registered"
        return compute_autopilot_eligibility(profile)


strategy_registry_service = StrategyRegistryService()
