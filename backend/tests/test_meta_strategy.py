"""Tests for the Meta-Strategy selection layer."""

from __future__ import annotations

from app.services.meta_strategy import (
    MetaDecision, active_strategies, decide, sanctioned_strategies, tilts,
)
from app.services.strategy_health import DEGRADED, HEALTHY, INSUFFICIENT, WATCH


def _h(strategy, status, score):
    return {"strategy": strategy, "status": status, "score": score}


# ── regime sanction ───────────────────────────────────────────────────────────────
def test_sanctioned_includes_options_and_equity():
    s = sanctioned_strategies("normal_mean_revert")
    assert "bull_put_spread" in s and "iron_condor" in s
    assert "momentum_long" in s          # equity strategies merged in


def test_sanctioned_crisis_and_unknown_empty():
    assert sanctioned_strategies("crisis") == set()
    assert sanctioned_strategies("not_a_regime") == set()


# ── decide ─────────────────────────────────────────────────────────────────────────
def test_unsanctioned_strategy_inactive():
    # iron_condor is NOT sanctioned in low_vol_trending (debit spreads only)
    d = decide("low_vol_trending", [_h("iron_condor", HEALTHY, 90)])[0]
    assert not d.active and d.tilt == 0.0 and not d.regime_sanctioned
    assert "not sanctioned" in d.reason


def test_degraded_sanctioned_strategy_suspended():
    d = decide("normal_mean_revert", [_h("bull_put_spread", DEGRADED, 40)])[0]
    assert not d.active and d.tilt == 0.0 and d.regime_sanctioned
    assert "degraded" in d.reason


def test_insufficient_gets_half_tilt():
    d = decide("normal_mean_revert", [_h("bull_put_spread", INSUFFICIENT, 0)])[0]
    assert d.active and d.tilt == 0.5


def test_watch_reduced_tilt():
    d = decide("normal_mean_revert", [_h("bull_put_spread", WATCH, 80)])[0]
    assert d.active and d.tilt == 0.4    # 0.5 * 80/100
    assert "watch" in d.reason


def test_healthy_full_tilt_with_floor():
    high = decide("normal_mean_revert", [_h("bull_put_spread", HEALTHY, 90)])[0]
    low = decide("normal_mean_revert", [_h("bull_put_spread", HEALTHY, 30)])[0]
    assert high.tilt == 0.9
    assert low.tilt == 0.6               # floored at 0.60


def test_active_strategies_and_tilts_helpers():
    decisions = decide("normal_mean_revert", [
        _h("bull_put_spread", HEALTHY, 90),
        _h("iron_condor", DEGRADED, 20),
        _h("bear_call_spread", WATCH, 70),
    ])
    assert set(active_strategies(decisions)) == {"bull_put_spread", "bear_call_spread"}
    t = tilts(decisions)
    assert t["iron_condor"] == 0.0 and t["bull_put_spread"] == 0.9


def test_decision_as_dict_shape():
    d = decide("normal_mean_revert", [_h("bull_put_spread", HEALTHY, 90)])[0]
    out = d.as_dict()
    for k in ("strategy", "active", "tilt", "health_status", "health_score",
              "regime_sanctioned", "reason"):
        assert k in out


def test_decide_empty():
    assert decide("normal_mean_revert", []) == []
