"""Tests for the Strategy Health Monitor (deterministic, no network)."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.strategy_health import (
    DEFAULT_BASELINES,
    DEGRADED,
    HEALTHY,
    INSUFFICIENT,
    WATCH,
    StrategyBaseline,
    StrategyHealth,
    baseline_for,
    evaluate_all,
    evaluate_strategy_health,
    is_suspended,
    _max_losing_streak,
)

CAP = 100_000.0


def _trades(pnls, start_day=1):
    """Build dated trades in order; one trade per day."""
    out = []
    for i, p in enumerate(pnls):
        d = date(2024, 1, 1 + ((start_day + i) % 27))
        out.append({"pnl": float(p), "entry_date": d, "exit_date": d})
    return out


# ── helpers ────────────────────────────────────────────────────────────────────
def test_max_losing_streak():
    assert _max_losing_streak([]) == 0
    assert _max_losing_streak([1, 2, 3]) == 0
    assert _max_losing_streak([-1, -1, 2, -1]) == 2
    assert _max_losing_streak([-1, -1, -1]) == 3
    assert _max_losing_streak([2, -1, -1, -1, 5, -1]) == 3


def test_baseline_for_known_unknown_and_override():
    assert baseline_for("bull_put_spread") is DEFAULT_BASELINES["bull_put_spread"]
    fb = baseline_for("totally_unknown")
    assert isinstance(fb, StrategyBaseline)
    custom = StrategyBaseline(win_rate=0.9, expectancy=99.0)
    assert baseline_for("bull_put_spread", {"bull_put_spread": custom}) is custom


# ── grading ─────────────────────────────────────────────────────────────────────
def test_insufficient_data_when_below_min_sample():
    h = evaluate_strategy_health("bull_put_spread", _trades([50, 60, -20]), CAP, min_sample=20)
    assert h.status == INSUFFICIENT and h.action == "none"
    assert not is_suspended(h)
    assert "collecting data" in h.reasons[0]


def test_healthy_at_or_above_baseline():
    # 25 trades, ~80% winners, healthy expectancy vs baseline 50
    pnls = [60] * 20 + [-40] * 5
    h = evaluate_strategy_health("bull_put_spread", _trades(pnls), CAP, min_sample=20)
    assert h.status == HEALTHY and h.action == "none"
    assert h.win_rate == pytest.approx(0.8, abs=0.01)
    assert h.expectancy_ratio is not None and h.expectancy_ratio >= 0.8


def test_degraded_on_negative_expectancy():
    pnls = [40] * 8 + [-60] * 17        # net negative
    h = evaluate_strategy_health("bull_put_spread", _trades(pnls), CAP, min_sample=20)
    assert h.status == DEGRADED and h.action == "suspend"
    assert is_suspended(h)
    assert any("negative live expectancy" in r for r in h.reasons)


def test_degraded_on_expectancy_below_half_baseline():
    # positive but tiny expectancy: baseline 50 → suspend under 25
    # 21 wins of 30, 9 losses of -60 over 30 trades → expectancy = (630-540)/30 = 3
    pnls = [30] * 21 + [-60] * 9
    h = evaluate_strategy_health("bull_put_spread", _trades(pnls), CAP, min_sample=20)
    assert h.status == DEGRADED
    assert any("of baseline" in r for r in h.reasons)


def test_degraded_on_losing_streak():
    base = StrategyBaseline(win_rate=0.8, expectancy=50.0, max_losing_streak=4)
    # strong overall expectancy but a 5-loss streak at the end trips suspend
    pnls = [200] * 20 + [-10, -10, -10, -10, -10]
    h = evaluate_strategy_health("x", _trades(pnls), CAP, baseline=base, min_sample=20)
    assert h.status == DEGRADED
    assert any("losing streak" in r for r in h.reasons)


def test_degraded_on_drawdown_breach():
    base = StrategyBaseline(win_rate=0.5, expectancy=10.0, max_drawdown_pct=0.01,
                            max_losing_streak=99)
    pnls = [50] * 20 + [-500] * 5
    h = evaluate_strategy_health("x", _trades(pnls), CAP, baseline=base, min_sample=20)
    assert h.status == DEGRADED
    assert any("drawdown" in r for r in h.reasons)


def test_watch_on_softening_expectancy():
    base = StrategyBaseline(win_rate=0.5, expectancy=100.0, max_losing_streak=99,
                            max_drawdown_pct=100.0)
    # expectancy 70 → 70% of baseline (between 50% and 80%) → watch/reduce
    pnls = [90] * 20 + [-10] * 5     # (1800-50)/25 = 70
    h = evaluate_strategy_health("x", _trades(pnls), CAP, baseline=base, min_sample=20)
    assert h.status == WATCH and h.action == "reduce"
    assert not is_suspended(h)


def test_watch_on_low_win_rate_with_ok_expectancy():
    # baseline win_rate 0.9 but live 0.6; expectancy healthy via big winners
    base = StrategyBaseline(win_rate=0.9, expectancy=10.0, max_losing_streak=99,
                            max_drawdown_pct=100.0)
    pnls = [100] * 15 + [-20] * 10     # 60% win rate, strong expectancy
    h = evaluate_strategy_health("x", _trades(pnls), CAP, baseline=base, min_sample=20)
    assert h.status == WATCH
    assert any("win rate" in r for r in h.reasons)


def test_expectancy_ratio_none_when_baseline_zero():
    base = StrategyBaseline(win_rate=0.5, expectancy=0.0, max_losing_streak=99,
                            max_drawdown_pct=100.0)
    pnls = [50] * 20 + [-10] * 5
    h = evaluate_strategy_health("x", _trades(pnls), CAP, baseline=base, min_sample=20)
    assert h.expectancy_ratio is None
    assert h.status in (HEALTHY, WATCH, DEGRADED)


def test_as_dict_shape():
    h = evaluate_strategy_health("bull_put_spread", _trades([60] * 20 + [-40] * 5),
                                 CAP, min_sample=20)
    d = h.as_dict()
    for k in ("strategy", "status", "action", "sample_size", "win_rate",
              "expectancy", "profit_factor", "drawdown_pct", "losing_streak",
              "expectancy_ratio", "reasons"):
        assert k in d


def test_as_dict_expectancy_ratio_none_serialises():
    h = StrategyHealth("x", HEALTHY, "none", 25, 0.8, 50.0, 2.0, 1.0, 0, None, [])
    assert h.as_dict()["expectancy_ratio"] is None


# ── evaluate_all ─────────────────────────────────────────────────────────────────
def test_evaluate_all_sorts_worst_first():
    healthy = _trades([60] * 20 + [-40] * 5)
    degraded = _trades([40] * 8 + [-60] * 17)
    thin = _trades([10, 20])
    res = evaluate_all(
        {"bull_put_spread": healthy, "bear_call_spread": degraded, "iron_condor": thin},
        CAP, min_sample=20,
    )
    statuses = [h.status for h in res]
    assert statuses[0] == DEGRADED               # worst first
    assert statuses.index(DEGRADED) < statuses.index(HEALTHY)
    assert statuses[-1] == INSUFFICIENT          # thin sample last


def test_evaluate_all_empty():
    assert evaluate_all({}, CAP) == []


def test_evaluate_all_respects_overrides():
    custom = StrategyBaseline(win_rate=0.99, expectancy=10_000.0)
    res = evaluate_all({"bull_put_spread": _trades([60] * 20 + [-40] * 5)},
                       CAP, overrides={"bull_put_spread": custom}, min_sample=20)
    # impossible baseline → live expectancy is a tiny fraction → degraded
    assert res[0].status == DEGRADED


def test_is_suspended_only_degraded():
    mk = lambda s: StrategyHealth("x", s, "none", 25, 0.8, 50, 2, 1, 0, 1.0, [])
    assert is_suspended(mk(DEGRADED))
    assert not is_suspended(mk(WATCH))
    assert not is_suspended(mk(HEALTHY))
    assert not is_suspended(mk(INSUFFICIENT))


def test_no_trades_grades_insufficient():
    h = evaluate_strategy_health("bull_put_spread", [], CAP, min_sample=20)
    assert h.status == INSUFFICIENT and h.sample_size == 0 and h.losing_streak == 0
