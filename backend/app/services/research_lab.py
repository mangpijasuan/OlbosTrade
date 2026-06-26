"""
Research Lab — the strategy promotion pipeline.

A disciplined funnel that moves a strategy idea from hunch to live capital only
when the evidence clears explicit gates:

    DRAFT ──backtest──▶ BACKTESTED ──gate──▶ PAPER ──gate──▶ PROMOTED
      ▲                     │                  │                 │
      └──────── revise ─────┘     (any stage) ─┴──── ARCHIVED ◀──┘

  • DRAFT      — a hypothesis + a Symphony strategy spec, untested.
  • BACKTESTED — has historical metrics attached (Sharpe / return / drawdown).
  • PAPER      — backtest cleared the gate; now accruing paper-traded results.
  • PROMOTED   — paper results cleared the gate; eligible for live capital AND a
                 StrategyBaseline is derived from its real performance, which the
                 Strategy Health Monitor consumes as an override (Batch B hook).
  • ARCHIVED   — retired; can be reopened to DRAFT.

This module is PURE: a state machine + gate evaluators + baseline derivation over
plain dicts. The DB model, route, and UI are thin adapters around it, so the
promotion logic is fully unit-tested with no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.strategy_health import StrategyBaseline


# ── Stages ──────────────────────────────────────────────────────────────────────
DRAFT = "draft"
BACKTESTED = "backtested"
WALK_FORWARD = "walk_forward"
PAPER = "paper"
PROMOTED = "promoted"
ARCHIVED = "archived"

STAGES = (DRAFT, BACKTESTED, WALK_FORWARD, PAPER, PROMOTED, ARCHIVED)

# Mandatory funnel — no strategy may skip walk-forward validation between an
# in-sample backtest and paper trading. (Reopen/demote/archive are escapes.)
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    DRAFT:        {BACKTESTED, ARCHIVED},
    BACKTESTED:   {WALK_FORWARD, DRAFT, ARCHIVED},
    WALK_FORWARD: {PAPER, BACKTESTED, ARCHIVED},
    PAPER:        {PROMOTED, WALK_FORWARD, ARCHIVED},
    PROMOTED:     {PAPER, ARCHIVED},        # demote back to paper or retire
    ARCHIVED:     {DRAFT},                   # reopen
}


# ── Promotion gates ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PromotionGates:
    # Backtest gate (BACKTESTED → WALK_FORWARD)
    min_backtest_sharpe:        float = 0.50
    min_backtest_return_pct:    float = 0.0
    max_backtest_drawdown_pct:  float = 30.0
    # Walk-forward gate (WALK_FORWARD → PAPER): out-of-sample must hold up and not
    # degrade too far from in-sample (overfitting guard).
    min_wf_oos_sharpe:          float = 0.40
    max_wf_degradation_pct:     float = 50.0   # (is_sharpe - oos_sharpe)/is_sharpe
    max_wf_drawdown_pct:        float = 35.0
    # Paper gate (PAPER → PROMOTED)
    min_paper_trades:           int = 20
    min_paper_win_rate:         float = 0.50
    min_paper_expectancy:       float = 0.0


DEFAULT_GATES = PromotionGates()


def evaluate_backtest_gate(metrics: dict,
                           gates: PromotionGates = DEFAULT_GATES) -> tuple[bool, list[str]]:
    """Check Symphony backtest metrics against the backtest gate."""
    reasons: list[str] = []
    if not metrics:
        return False, ["no backtest metrics"]
    sharpe = float(metrics.get("sharpe", 0.0))
    ret = float(metrics.get("total_return_pct", 0.0))
    dd = float(metrics.get("max_drawdown_pct", 999.0))
    if sharpe < gates.min_backtest_sharpe:
        reasons.append(f"sharpe {sharpe:.2f} < {gates.min_backtest_sharpe:.2f}")
    if ret < gates.min_backtest_return_pct:
        reasons.append(f"return {ret:.1f}% < {gates.min_backtest_return_pct:.1f}%")
    if dd > gates.max_backtest_drawdown_pct:
        reasons.append(f"drawdown {dd:.1f}% > {gates.max_backtest_drawdown_pct:.1f}%")
    return (not reasons), (reasons or ["backtest gate cleared"])


def evaluate_walkforward_gate(wf: dict,
                              gates: PromotionGates = DEFAULT_GATES) -> tuple[bool, list[str]]:
    """
    Check walk-forward (out-of-sample) metrics. Expects:
      oos_sharpe, oos_return_pct, max_drawdown_pct, and optionally is_sharpe
      (in-sample) to measure degradation. Guards against overfit strategies that
      look great in-sample but collapse out-of-sample.
    """
    reasons: list[str] = []
    if not wf:
        return False, ["no walk-forward metrics"]
    oos_sharpe = float(wf.get("oos_sharpe", 0.0))
    oos_ret = float(wf.get("oos_return_pct", 0.0))
    dd = float(wf.get("max_drawdown_pct", 999.0))
    is_sharpe = float(wf.get("is_sharpe", 0.0))
    if oos_sharpe < gates.min_wf_oos_sharpe:
        reasons.append(f"OOS sharpe {oos_sharpe:.2f} < {gates.min_wf_oos_sharpe:.2f}")
    if oos_ret < 0:
        reasons.append(f"OOS return {oos_ret:.1f}% < 0%")
    if dd > gates.max_wf_drawdown_pct:
        reasons.append(f"OOS drawdown {dd:.1f}% > {gates.max_wf_drawdown_pct:.1f}%")
    if is_sharpe > 1e-9:
        degradation = (is_sharpe - oos_sharpe) / is_sharpe * 100.0
        if degradation > gates.max_wf_degradation_pct:
            reasons.append(
                f"degradation {degradation:.0f}% > {gates.max_wf_degradation_pct:.0f}%")
    return (not reasons), (reasons or ["walk-forward gate cleared"])


def evaluate_paper_gate(perf: dict,
                        gates: PromotionGates = DEFAULT_GATES) -> tuple[bool, list[str]]:
    """Check paper-trading performance (compute_performance dict) against the gate."""
    reasons: list[str] = []
    if not perf:
        return False, ["no paper results"]
    n = int(perf.get("total_trades", 0))
    wr = float(perf.get("win_rate", 0.0))
    exp = float(perf.get("expectancy", 0.0))
    if n < gates.min_paper_trades:
        reasons.append(f"trades {n} < {gates.min_paper_trades}")
    if wr < gates.min_paper_win_rate:
        reasons.append(f"win rate {wr:.0%} < {gates.min_paper_win_rate:.0%}")
    if exp < gates.min_paper_expectancy:
        reasons.append(f"expectancy {exp:.2f} < {gates.min_paper_expectancy:.2f}")
    return (not reasons), (reasons or ["paper gate cleared"])


def baseline_from_performance(perf: dict,
                              backtest_metrics: dict | None = None) -> StrategyBaseline:
    """
    Derive a Strategy-Health baseline from a promoted strategy's REAL paper
    performance (win rate + expectancy), with the drawdown tolerance taken from
    the worst of paper / backtest drawdown so the live monitor isn't stricter
    than the strategy's own demonstrated risk.
    """
    wr = float(perf.get("win_rate", 0.0))
    exp = float(perf.get("expectancy", 0.0))
    paper_dd = float(perf.get("max_drawdown_trades_pct",
                              perf.get("max_drawdown_pct", 0.0)) or 0.0)
    bt_dd = float((backtest_metrics or {}).get("max_drawdown_pct", 0.0) or 0.0)
    dd_tol = max(paper_dd, bt_dd, 10.0)   # never tighter than 10%
    return StrategyBaseline(win_rate=wr, expectancy=exp, max_drawdown_pct=round(dd_tol, 2))


# ── State machine ────────────────────────────────────────────────────────────────
@dataclass
class TransitionResult:
    ok:       bool
    reason:   str
    patch:    dict                      # fields to persist on the experiment
    baseline: StrategyBaseline | None = None


def can_transition(current: str, target: str) -> tuple[bool, str]:
    if current not in STAGES:
        return False, f"unknown stage {current!r}"
    if target not in STAGES:
        return False, f"unknown target {target!r}"
    if target in ALLOWED_TRANSITIONS.get(current, set()):
        return True, "ok"
    return False, f"cannot move {current} → {target}"


def transition(
    experiment: dict,
    target: str,
    *,
    gates: PromotionGates = DEFAULT_GATES,
    metrics: dict | None = None,
    wf_metrics: dict | None = None,
    perf: dict | None = None,
) -> TransitionResult:
    """
    Validate and compute a stage transition for an experiment dict.

      • → BACKTESTED   : requires `metrics`; stores them.
      • → WALK_FORWARD : requires stored backtest metrics that clear the backtest
                         gate; stores `wf_metrics` if supplied.
      • → PAPER        : requires walk-forward metrics that clear the WF gate.
      • → PROMOTED     : requires `perf` that clears the paper gate; derives a
                         StrategyBaseline.
      • → ARCHIVED / DRAFT / demotions : structural only.

    Returns a TransitionResult; on failure `patch` is empty and nothing changes.
    """
    current = experiment.get("stage", DRAFT)
    ok, reason = can_transition(current, target)
    if not ok:
        return TransitionResult(False, reason, {})

    patch: dict = {"stage": target}

    if target == BACKTESTED:
        if not metrics:
            return TransitionResult(False, "backtest requires metrics", {})
        patch["backtest_metrics"] = metrics
        return TransitionResult(True, "recorded backtest", patch)

    if target == WALK_FORWARD and current == BACKTESTED:
        bt = metrics or experiment.get("backtest_metrics")
        passed, reasons = evaluate_backtest_gate(bt, gates)
        if not passed:
            return TransitionResult(False, "backtest gate failed: " + "; ".join(reasons), {})
        if wf_metrics:
            patch["walk_forward_metrics"] = wf_metrics
        return TransitionResult(True, "advanced to walk-forward", patch)

    if target == PAPER and current == WALK_FORWARD:
        wf = wf_metrics or experiment.get("walk_forward_metrics")
        passed, reasons = evaluate_walkforward_gate(wf, gates)
        if not passed:
            return TransitionResult(False, "walk-forward gate failed: " + "; ".join(reasons), {})
        if wf_metrics:
            patch["walk_forward_metrics"] = wf_metrics
        return TransitionResult(True, "promoted to paper", patch)

    if target == PROMOTED:
        p = perf or experiment.get("paper_perf")
        passed, reasons = evaluate_paper_gate(p, gates)
        if not passed:
            return TransitionResult(False, "paper gate failed: " + "; ".join(reasons), {})
        baseline = baseline_from_performance(p, experiment.get("backtest_metrics"))
        patch["paper_perf"] = p
        patch["baseline"] = {
            "win_rate": baseline.win_rate,
            "expectancy": baseline.expectancy,
            "max_drawdown_pct": baseline.max_drawdown_pct,
        }
        return TransitionResult(True, "promoted to live-eligible", patch, baseline)

    # Structural transitions (archive, reopen, demote, revise).
    return TransitionResult(True, f"moved to {target}", patch)


def baselines_from_experiments(
    experiments: list[dict],
) -> dict[str, StrategyBaseline]:
    """
    Build the Strategy-Health override map from PROMOTED experiments that carry a
    derived baseline. Last promoted wins if a strategy has several.
    """
    out: dict[str, StrategyBaseline] = {}
    for e in experiments:
        if e.get("stage") != PROMOTED:
            continue
        b = e.get("baseline") or {}
        strat = e.get("strategy")
        if not strat or "win_rate" not in b:
            continue
        out[strat] = StrategyBaseline(
            win_rate=float(b["win_rate"]),
            expectancy=float(b["expectancy"]),
            max_drawdown_pct=float(b.get("max_drawdown_pct", 25.0)),
        )
    return out
