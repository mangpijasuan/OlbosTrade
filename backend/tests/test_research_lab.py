"""Tests for the Research Lab promotion funnel (pure state machine + gates)."""

from __future__ import annotations

import pytest

from app.services.strategy_health import StrategyBaseline
from app.services.research_lab import (
    ARCHIVED, BACKTESTED, DRAFT, PAPER, PROMOTED, WALK_FORWARD,
    DEFAULT_GATES, PromotionGates,
    baseline_from_performance, baselines_from_experiments,
    can_transition, evaluate_backtest_gate, evaluate_paper_gate,
    evaluate_walkforward_gate, transition,
)

_STRONG_BT = {"sharpe": 1.5, "total_return_pct": 20, "max_drawdown_pct": 8}
_GOOD_WF = {"oos_sharpe": 1.1, "oos_return_pct": 12, "max_drawdown_pct": 9, "is_sharpe": 1.4}


# ── gates ────────────────────────────────────────────────────────────────────────
def test_backtest_gate_pass():
    ok, reasons = evaluate_backtest_gate(
        {"sharpe": 1.2, "total_return_pct": 18.0, "max_drawdown_pct": 12.0})
    assert ok and "cleared" in reasons[0]


def test_backtest_gate_no_metrics():
    ok, reasons = evaluate_backtest_gate({})
    assert not ok and "no backtest metrics" in reasons


@pytest.mark.parametrize("m,frag", [
    ({"sharpe": 0.1, "total_return_pct": 10, "max_drawdown_pct": 5}, "sharpe"),
    ({"sharpe": 1.0, "total_return_pct": -5, "max_drawdown_pct": 5}, "return"),
    ({"sharpe": 1.0, "total_return_pct": 10, "max_drawdown_pct": 99}, "drawdown"),
])
def test_backtest_gate_failures(m, frag):
    ok, reasons = evaluate_backtest_gate(m)
    assert not ok and any(frag in r for r in reasons)


def test_paper_gate_pass():
    ok, reasons = evaluate_paper_gate(
        {"total_trades": 30, "win_rate": 0.7, "expectancy": 25.0})
    assert ok and "cleared" in reasons[0]


def test_paper_gate_no_perf():
    ok, reasons = evaluate_paper_gate({})
    assert not ok and "no paper results" in reasons


@pytest.mark.parametrize("p,frag", [
    ({"total_trades": 5, "win_rate": 0.8, "expectancy": 10}, "trades"),
    ({"total_trades": 30, "win_rate": 0.2, "expectancy": 10}, "win rate"),
    ({"total_trades": 30, "win_rate": 0.8, "expectancy": -5}, "expectancy"),
])
def test_paper_gate_failures(p, frag):
    ok, reasons = evaluate_paper_gate(p)
    assert not ok and any(frag in r for r in reasons)


# ── baseline derivation ───────────────────────────────────────────────────────────
def test_baseline_from_performance_uses_paper_stats():
    b = baseline_from_performance(
        {"win_rate": 0.72, "expectancy": 44.0, "max_drawdown_trades_pct": 14.0})
    assert isinstance(b, StrategyBaseline)
    assert b.win_rate == 0.72 and b.expectancy == 44.0 and b.max_drawdown_pct == 14.0


def test_baseline_drawdown_never_below_floor():
    b = baseline_from_performance({"win_rate": 0.6, "expectancy": 30.0,
                                   "max_drawdown_trades_pct": 2.0})
    assert b.max_drawdown_pct == 10.0   # floored at 10%


def test_baseline_takes_worst_drawdown():
    b = baseline_from_performance(
        {"win_rate": 0.6, "expectancy": 30.0, "max_drawdown_trades_pct": 12.0},
        backtest_metrics={"max_drawdown_pct": 22.0})
    assert b.max_drawdown_pct == 22.0   # backtest DD worse → used


# ── transition structural rules ────────────────────────────────────────────────────
def test_can_transition_valid_and_invalid():
    assert can_transition(DRAFT, BACKTESTED)[0]
    assert not can_transition(DRAFT, PROMOTED)[0]
    assert not can_transition("bogus", DRAFT)[0]
    assert not can_transition(DRAFT, "bogus")[0]
    assert can_transition(PROMOTED, ARCHIVED)[0]
    assert can_transition(ARCHIVED, DRAFT)[0]


def test_transition_rejects_illegal_move():
    r = transition({"stage": DRAFT}, PROMOTED)
    assert not r.ok and "cannot move" in r.reason and r.patch == {}


# ── transition: backtested ─────────────────────────────────────────────────────────
def test_transition_to_backtested_requires_metrics():
    r = transition({"stage": DRAFT}, BACKTESTED)
    assert not r.ok and "requires metrics" in r.reason


def test_transition_to_backtested_stores_metrics():
    m = {"sharpe": 1.0, "total_return_pct": 10, "max_drawdown_pct": 8}
    r = transition({"stage": DRAFT}, BACKTESTED, metrics=m)
    assert r.ok and r.patch["stage"] == BACKTESTED and r.patch["backtest_metrics"] == m


# ── walk-forward gate ───────────────────────────────────────────────────────────────
def test_walkforward_gate_pass():
    ok, reasons = evaluate_walkforward_gate(_GOOD_WF)
    assert ok and "cleared" in reasons[0]


def test_walkforward_gate_no_metrics():
    ok, reasons = evaluate_walkforward_gate({})
    assert not ok and "no walk-forward metrics" in reasons


@pytest.mark.parametrize("wf,frag", [
    ({"oos_sharpe": 0.1, "oos_return_pct": 5, "max_drawdown_pct": 5}, "OOS sharpe"),
    ({"oos_sharpe": 1.0, "oos_return_pct": -3, "max_drawdown_pct": 5}, "OOS return"),
    ({"oos_sharpe": 1.0, "oos_return_pct": 5, "max_drawdown_pct": 99}, "OOS drawdown"),
    ({"oos_sharpe": 0.5, "oos_return_pct": 5, "max_drawdown_pct": 5, "is_sharpe": 2.0}, "degradation"),
])
def test_walkforward_gate_failures(wf, frag):
    ok, reasons = evaluate_walkforward_gate(wf)
    assert not ok and any(frag in r for r in reasons)


# ── transition: backtested → walk_forward (backtest gate) ────────────────────────────
def test_transition_to_walkforward_blocks_on_weak_backtest():
    exp = {"stage": BACKTESTED, "backtest_metrics": {"sharpe": 0.1, "total_return_pct": 1, "max_drawdown_pct": 5}}
    r = transition(exp, WALK_FORWARD)
    assert not r.ok and "backtest gate failed" in r.reason


def test_transition_to_walkforward_passes_strong_backtest():
    exp = {"stage": BACKTESTED, "backtest_metrics": _STRONG_BT}
    r = transition(exp, WALK_FORWARD, wf_metrics=_GOOD_WF)
    assert r.ok and r.patch["stage"] == WALK_FORWARD
    assert r.patch["walk_forward_metrics"] == _GOOD_WF


def test_transition_to_walkforward_accepts_inline_metrics():
    r = transition({"stage": BACKTESTED}, WALK_FORWARD, metrics=_STRONG_BT)
    assert r.ok


# ── transition: walk_forward → paper (walk-forward gate) ─────────────────────────────
def test_transition_to_paper_blocks_on_weak_walkforward():
    exp = {"stage": WALK_FORWARD, "walk_forward_metrics": {"oos_sharpe": 0.1, "oos_return_pct": 1, "max_drawdown_pct": 5}}
    r = transition(exp, PAPER)
    assert not r.ok and "walk-forward gate failed" in r.reason


def test_transition_to_paper_passes_strong_walkforward():
    exp = {"stage": WALK_FORWARD, "walk_forward_metrics": _GOOD_WF}
    r = transition(exp, PAPER)
    assert r.ok and r.patch["stage"] == PAPER


def test_transition_to_paper_accepts_inline_wf_metrics():
    r = transition({"stage": WALK_FORWARD}, PAPER, wf_metrics=_GOOD_WF)
    assert r.ok and r.patch["walk_forward_metrics"] == _GOOD_WF


# ── transition: promoted (paper gate + baseline) ───────────────────────────────────
def test_transition_to_promoted_blocks_on_weak_paper():
    exp = {"stage": PAPER, "paper_perf": {"total_trades": 3, "win_rate": 0.5, "expectancy": 1}}
    r = transition(exp, PROMOTED)
    assert not r.ok and "paper gate failed" in r.reason and r.baseline is None


def test_transition_to_promoted_derives_baseline():
    exp = {"stage": PAPER, "backtest_metrics": {"max_drawdown_pct": 15.0}}
    perf = {"total_trades": 40, "win_rate": 0.7, "expectancy": 35.0,
            "max_drawdown_trades_pct": 9.0}
    r = transition(exp, PROMOTED, perf=perf)
    assert r.ok and r.baseline is not None
    assert r.patch["baseline"]["win_rate"] == 0.7
    assert r.patch["baseline"]["expectancy"] == 35.0
    assert r.patch["baseline"]["max_drawdown_pct"] == 15.0   # backtest DD worse
    assert r.patch["paper_perf"] == perf


# ── structural transitions (archive / reopen / demote) ─────────────────────────────
def test_archive_and_reopen():
    r = transition({"stage": PROMOTED}, ARCHIVED)
    assert r.ok and r.patch == {"stage": ARCHIVED}
    r2 = transition({"stage": ARCHIVED}, DRAFT)
    assert r2.ok and r2.patch == {"stage": DRAFT}


def test_demote_promoted_to_paper():
    r = transition({"stage": PROMOTED}, PAPER)
    assert r.ok and r.patch == {"stage": PAPER}   # structural, no gate


# ── baselines_from_experiments ─────────────────────────────────────────────────────
def test_baselines_from_experiments_only_promoted_with_baseline():
    exps = [
        {"stage": PROMOTED, "strategy": "bull_put_spread",
         "baseline": {"win_rate": 0.8, "expectancy": 50, "max_drawdown_pct": 20}},
        {"stage": PAPER, "strategy": "iron_condor",
         "baseline": {"win_rate": 0.7, "expectancy": 40}},   # not promoted → skip
        {"stage": PROMOTED, "strategy": "no_baseline"},       # no baseline → skip
    ]
    out = baselines_from_experiments(exps)
    assert set(out) == {"bull_put_spread"}
    assert out["bull_put_spread"].expectancy == 50


def test_baselines_last_promoted_wins():
    exps = [
        {"stage": PROMOTED, "strategy": "x",
         "baseline": {"win_rate": 0.6, "expectancy": 10, "max_drawdown_pct": 25}},
        {"stage": PROMOTED, "strategy": "x",
         "baseline": {"win_rate": 0.9, "expectancy": 99, "max_drawdown_pct": 15}},
    ]
    out = baselines_from_experiments(exps)
    assert out["x"].expectancy == 99


def test_custom_gates_respected():
    gates = PromotionGates(min_backtest_sharpe=2.0)
    ok, _ = evaluate_backtest_gate({"sharpe": 1.5, "total_return_pct": 50, "max_drawdown_pct": 5}, gates)
    assert not ok
    assert DEFAULT_GATES.min_backtest_sharpe == 0.50
