"""
Strategy Registry — the canonical, read-side view over research experiments.

The registry is NOT a new store; it's a projection of `research_experiments`
(the Research Lab funnel) that answers portfolio-level questions: what strategies
exist, what lifecycle stage each is in, which are in production, and whether their
metadata is complete enough to be allocated capital.

Pure functions over experiment dicts (each shaped like
`ResearchExperiment.as_dict()`), so it's trivially testable and reused by the API,
the allocation engine, and the meta-strategy layer.
"""

from __future__ import annotations

from app.services.research_lab import (
    ARCHIVED, BACKTESTED, DRAFT, PAPER, PROMOTED, STAGES, WALK_FORWARD,
)

# How "advanced" each stage is, for picking a strategy's current stage when it has
# several experiments. Archived ranks lowest (retired).
STAGE_ORDER: dict[str, int] = {
    ARCHIVED: 0, DRAFT: 1, BACKTESTED: 2, WALK_FORWARD: 3, PAPER: 4, PROMOTED: 5,
}

# Metadata a strategy must carry before it's eligible for capital allocation.
REQUIRED_METADATA = ("version", "author", "asset_class", "risk_profile")


def validate_metadata(experiment: dict) -> tuple[bool, list[str]]:
    """True when all registry metadata fields are present and non-empty."""
    missing = [f for f in REQUIRED_METADATA if not experiment.get(f)]
    return (not missing), missing


def is_production(experiment: dict) -> bool:
    return experiment.get("stage") == PROMOTED


def production_strategies(experiments: list[dict]) -> list[dict]:
    """Experiments live-eligible for capital (PROMOTED), newest-ranked first."""
    return [e for e in experiments if is_production(e)]


def by_strategy(experiments: list[dict]) -> dict[str, dict]:
    """
    Collapse experiments to one row per strategy name with its most-advanced
    stage, experiment count, and production flag.
    """
    out: dict[str, dict] = {}
    for e in experiments:
        strat = e.get("strategy")
        if not strat:
            continue
        stage = e.get("stage", DRAFT)
        rank = STAGE_ORDER.get(stage, 0)
        row = out.get(strat)
        if row is None:
            out[strat] = {
                "strategy": strat,
                "current_stage": stage,
                "best_rank": rank,
                "experiments": 1,
                "in_production": stage == PROMOTED,
            }
            continue
        row["experiments"] += 1
        row["in_production"] = row["in_production"] or (stage == PROMOTED)
        if rank > row["best_rank"]:
            row["best_rank"] = rank
            row["current_stage"] = stage
    for row in out.values():
        row.pop("best_rank", None)
    return out


def summarize(experiments: list[dict]) -> dict:
    """Registry overview: totals, counts by stage, by asset class, production set."""
    by_stage = {s: 0 for s in STAGES}
    by_asset: dict[str, int] = {}
    for e in experiments:
        stage = e.get("stage", DRAFT)
        by_stage[stage] = by_stage.get(stage, 0) + 1
        ac = e.get("asset_class") or "unspecified"
        by_asset[ac] = by_asset.get(ac, 0) + 1
    prod = production_strategies(experiments)
    return {
        "total_experiments": len(experiments),
        "total_strategies": len(by_strategy(experiments)),
        "by_stage": by_stage,
        "by_asset_class": by_asset,
        "production_count": len(prod),
        "production_strategies": sorted({e.get("strategy") for e in prod if e.get("strategy")}),
    }
