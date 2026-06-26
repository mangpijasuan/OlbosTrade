"""Tests for the Strategy Registry view over research experiments."""

from __future__ import annotations

from app.services import strategy_registry as reg
from app.services.research_lab import (
    ARCHIVED, BACKTESTED, DRAFT, PAPER, PROMOTED, WALK_FORWARD,
)


def _exp(strategy, stage, **kw):
    base = {"strategy": strategy, "stage": stage}
    base.update(kw)
    return base


# ── metadata validation ─────────────────────────────────────────────────────────────
def test_validate_metadata_complete():
    ok, missing = reg.validate_metadata(
        {"version": "1.0", "author": "me", "asset_class": "options", "risk_profile": "moderate"})
    assert ok and missing == []


def test_validate_metadata_missing():
    ok, missing = reg.validate_metadata({"version": "1.0"})
    assert not ok
    assert set(missing) == {"author", "asset_class", "risk_profile"}


# ── production ───────────────────────────────────────────────────────────────────────
def test_is_production_and_production_strategies():
    exps = [_exp("a", PROMOTED), _exp("b", PAPER), _exp("c", PROMOTED)]
    assert reg.is_production(exps[0]) and not reg.is_production(exps[1])
    prod = reg.production_strategies(exps)
    assert {e["strategy"] for e in prod} == {"a", "c"}


# ── by_strategy ──────────────────────────────────────────────────────────────────────
def test_by_strategy_picks_most_advanced_stage():
    exps = [
        _exp("alpha", DRAFT),
        _exp("alpha", BACKTESTED),
        _exp("alpha", PAPER),       # most advanced
        _exp("beta", WALK_FORWARD),
    ]
    rows = reg.by_strategy(exps)
    assert rows["alpha"]["current_stage"] == PAPER
    assert rows["alpha"]["experiments"] == 3
    assert rows["beta"]["current_stage"] == WALK_FORWARD
    assert "best_rank" not in rows["alpha"]   # internal key stripped


def test_by_strategy_production_flag():
    exps = [_exp("alpha", PAPER), _exp("alpha", PROMOTED)]
    rows = reg.by_strategy(exps)
    assert rows["alpha"]["in_production"] is True
    assert rows["alpha"]["current_stage"] == PROMOTED


def test_by_strategy_skips_missing_name():
    rows = reg.by_strategy([{"stage": PAPER}, _exp("x", DRAFT)])
    assert set(rows) == {"x"}


def test_by_strategy_unknown_stage_rank_zero():
    rows = reg.by_strategy([_exp("x", "weird_stage"), _exp("x", DRAFT)])
    assert rows["x"]["current_stage"] == DRAFT   # DRAFT outranks unknown


# ── summarize ────────────────────────────────────────────────────────────────────────
def test_summarize_counts():
    exps = [
        _exp("a", PROMOTED, asset_class="options"),
        _exp("b", PAPER, asset_class="options"),
        _exp("c", DRAFT),                      # no asset_class → unspecified
        _exp("a", BACKTESTED, asset_class="options"),
    ]
    s = reg.summarize(exps)
    assert s["total_experiments"] == 4
    assert s["total_strategies"] == 3
    assert s["by_stage"][PROMOTED] == 1 and s["by_stage"][PAPER] == 1
    assert s["by_asset_class"]["options"] == 3
    assert s["by_asset_class"]["unspecified"] == 1
    assert s["production_count"] == 1
    assert s["production_strategies"] == ["a"]


def test_summarize_empty():
    s = reg.summarize([])
    assert s["total_experiments"] == 0 and s["total_strategies"] == 0
    assert s["production_strategies"] == []
    assert all(v == 0 for v in s["by_stage"].values())
