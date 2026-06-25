"""
Meta-Strategy layer — decides WHICH strategies should be active and how hard,
given the current market regime and each strategy's health.

This is not a trade predictor; it's a strategy selector. It combines two signals:
  1. Regime sanction — does the active regime endorse this strategy at all?
     (reuses regime_classifier.REGIME_CONFIG — the single source of truth).
  2. Health — degraded strategies are switched off, watch-listed ones are tilted
     down, healthy ones run at a tilt proportional to their 0–100 health score.

Output is a per-strategy `tilt` in [0,1] that the Capital Allocation Engine
(Batch 3) multiplies into target weights. Pure functions over dicts → testable.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.regime_classifier import REGIME_CONFIG, RegimeType
from app.services.strategy_health import DEGRADED, HEALTHY, INSUFFICIENT, WATCH

# Tilt floors/factors.
_HEALTHY_FLOOR = 0.60     # a sanctioned, healthy strategy never tilts below this
_WATCH_FACTOR = 0.50      # watch-listed strategies run at half their score tilt
_NEW_TILT = 0.50          # insufficient-data strategies get a cautious half tilt


@dataclass
class MetaDecision:
    strategy:          str
    active:            bool
    tilt:              float     # 0..1 allocation multiplier
    health_status:     str
    health_score:      float
    regime_sanctioned: bool
    reason:            str

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "active": self.active,
            "tilt": round(self.tilt, 3),
            "health_status": self.health_status,
            "health_score": round(self.health_score, 1),
            "regime_sanctioned": self.regime_sanctioned,
            "reason": self.reason,
        }


def sanctioned_strategies(regime: str) -> set[str]:
    """Strategies the regime endorses (options + equity). Empty for crisis/unknown."""
    try:
        cfg = REGIME_CONFIG.get(RegimeType(regime))
    except Exception:
        return set()
    if not cfg:   # pragma: no cover - every valid RegimeType has a config entry
        return set()
    return set(cfg.get("strategies_allowed", [])) | set(
        cfg.get("equity_strategies_allowed", []))


def decide(regime: str, healths: list[dict]) -> list[MetaDecision]:
    """
    regime: a RegimeType value (e.g. 'normal_mean_revert').
    healths: list of StrategyHealth.as_dict() rows (strategy, status, score, …).
    Returns one MetaDecision per strategy.
    """
    sanctioned = sanctioned_strategies(regime)
    out: list[MetaDecision] = []
    for h in healths:
        strat = h.get("strategy", "")
        status = h.get("status", INSUFFICIENT)
        score = float(h.get("score", 0.0))

        if strat not in sanctioned:
            out.append(MetaDecision(strat, False, 0.0, status, score, False,
                                    f"not sanctioned by regime '{regime}'"))
        elif status == DEGRADED:
            out.append(MetaDecision(strat, False, 0.0, status, score, True,
                                    "health degraded — suspended"))
        elif status == INSUFFICIENT:
            out.append(MetaDecision(strat, True, _NEW_TILT, status, score, True,
                                    "collecting data — cautious half tilt"))
        elif status == WATCH:
            tilt = round(_WATCH_FACTOR * score / 100.0, 3)
            out.append(MetaDecision(strat, True, tilt, status, score, True,
                                    "on watch — reduced tilt"))
        else:  # HEALTHY
            tilt = round(max(_HEALTHY_FLOOR, score / 100.0), 3)
            out.append(MetaDecision(strat, True, tilt, status, score, True,
                                    "healthy — full tilt"))
    return out


def active_strategies(decisions: list[MetaDecision]) -> list[str]:
    return [d.strategy for d in decisions if d.active]


def tilts(decisions: list[MetaDecision]) -> dict[str, float]:
    """Strategy → tilt map for the allocation engine."""
    return {d.strategy: d.tilt for d in decisions}
