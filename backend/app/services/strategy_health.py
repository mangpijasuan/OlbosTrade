"""
Strategy Health Monitor.

Tracks each strategy's *live* behaviour against an expected baseline and flags
degradation early — before a quietly-decaying edge bleeds the account. For every
strategy it computes win rate, expectancy, profit factor, the worst recent
losing streak, and a trade-ordered drawdown, then grades it:

    healthy  → trading normally, no action
    watch    → softening vs baseline → reduce size
    degraded → broken vs baseline    → suspend new entries
    insufficient_data → too few closed trades to judge → no action

The core rule (per spec): live expectancy below half the baseline, or a negative
live expectancy, suspends the strategy. A long losing streak or a deep recent
drawdown also suspends. This is advisory state the autopilot and UI consume — it
never closes existing positions (that stays the Kill Switch's job); it only gates
NEW entries via `is_suspended()`.

Pure functions over trade dicts so it's trivially testable and reusable by the
API, the dashboard, and the execution gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.performance_analytics import compute_performance


# ── Status / action vocabulary ──────────────────────────────────────────────────
HEALTHY = "healthy"
WATCH = "watch"
DEGRADED = "degraded"
INSUFFICIENT = "insufficient_data"

ACTION_NONE = "none"
ACTION_REDUCE = "reduce"
ACTION_SUSPEND = "suspend"

# Statuses that stop NEW entries for the strategy.
_SUSPENDED = {DEGRADED}


@dataclass(frozen=True)
class StrategyBaseline:
    """Expected, healthy behaviour for a strategy (from backtest / design intent)."""
    win_rate:         float          # expected win rate 0..1
    expectancy:       float          # expected $ P&L per trade
    max_drawdown_pct: float = 25.0   # tolerated trade-ordered drawdown
    max_losing_streak: int = 6       # consecutive losses that trip a suspend


# Conservative design-intent baselines. Replaced per-strategy by stored backtest
# results once the Research Lab (Batch D) persists them; callers may override.
DEFAULT_BASELINES: dict[str, StrategyBaseline] = {
    "bull_put_spread":        StrategyBaseline(win_rate=0.80, expectancy=50.0),
    "bear_call_spread":       StrategyBaseline(win_rate=0.80, expectancy=50.0),
    "iron_condor":            StrategyBaseline(win_rate=0.75, expectancy=40.0),
    "bull_call_debit_spread": StrategyBaseline(win_rate=0.45, expectancy=60.0,
                                               max_losing_streak=8),
    "equity":                 StrategyBaseline(win_rate=0.50, expectancy=40.0,
                                               max_losing_streak=8),
}

_FALLBACK_BASELINE = StrategyBaseline(win_rate=0.55, expectancy=40.0)

# Ratio of live-to-baseline expectancy below which a strategy is suspended /
# put on watch.
_SUSPEND_RATIO = 0.50
_WATCH_RATIO = 0.80
_WATCH_WIN_RATE_GAP = 0.10   # win rate this far under baseline → watch


@dataclass
class StrategyHealth:
    strategy:          str
    status:            str
    action:            str
    sample_size:       int
    win_rate:          float
    expectancy:        float
    profit_factor:     float
    drawdown_pct:      float
    losing_streak:     int
    expectancy_ratio:  float | None   # live / baseline (None if baseline ≤ 0)
    reasons:           list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "status": self.status,
            "action": self.action,
            "sample_size": self.sample_size,
            "win_rate": round(self.win_rate, 4),
            "expectancy": round(self.expectancy, 2),
            "profit_factor": round(self.profit_factor, 2),
            "drawdown_pct": round(self.drawdown_pct, 2),
            "losing_streak": self.losing_streak,
            "expectancy_ratio": (round(self.expectancy_ratio, 2)
                                 if self.expectancy_ratio is not None else None),
            "reasons": self.reasons,
        }


def _max_losing_streak(pnls: list[float]) -> int:
    """Longest run of consecutive losing trades (pnl < 0)."""
    best = run = 0
    for p in pnls:
        if p < 0:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def baseline_for(strategy: str,
                 overrides: dict[str, StrategyBaseline] | None = None) -> StrategyBaseline:
    if overrides and strategy in overrides:
        return overrides[strategy]
    return DEFAULT_BASELINES.get(strategy, _FALLBACK_BASELINE)


def evaluate_strategy_health(
    strategy: str,
    trades: list[dict],
    starting_capital: float,
    baseline: StrategyBaseline | None = None,
    min_sample: int = 20,
) -> StrategyHealth:
    """
    trades: closed trades for ONE strategy, each {"pnl", "entry_date", "exit_date"}.
    Returns a graded StrategyHealth. Empty / tiny samples grade INSUFFICIENT.
    """
    base = baseline or baseline_for(strategy)
    perf = compute_performance(trades, starting_capital, min_sample=min_sample)
    pnls = [float(t["pnl"]) for t in trades if t.get("pnl") is not None]
    n = perf["total_trades"]
    streak = _max_losing_streak(
        [float(t["pnl"]) for t in sorted(
            trades, key=lambda t: (t.get("exit_date") or t.get("entry_date") or 0))
         if t.get("pnl") is not None]
    ) if pnls else 0

    win_rate = perf["win_rate"]
    expectancy = perf["expectancy"]
    profit_factor = perf["profit_factor"]
    dd = perf["rolling_max_dd_30_pct"]
    ratio = (expectancy / base.expectancy) if base.expectancy > 0 else None

    reasons: list[str] = []

    # Not enough evidence to grade.
    if n < min_sample:
        reasons.append(f"only {n}/{min_sample} closed trades — collecting data")
        return StrategyHealth(strategy, INSUFFICIENT, ACTION_NONE, n, win_rate,
                              expectancy, profit_factor, dd, streak, ratio, reasons)

    # ── Degraded (suspend) checks ────────────────────────────────────────────
    if expectancy <= 0:
        reasons.append(f"negative live expectancy ({expectancy:.2f})")
    if ratio is not None and ratio < _SUSPEND_RATIO:
        reasons.append(f"expectancy {ratio:.0%} of baseline (< {_SUSPEND_RATIO:.0%})")
    if streak >= base.max_losing_streak:
        reasons.append(f"losing streak {streak} ≥ {base.max_losing_streak}")
    if dd > base.max_drawdown_pct:
        reasons.append(f"rolling drawdown {dd:.1f}% > {base.max_drawdown_pct:.1f}%")
    if reasons:
        return StrategyHealth(strategy, DEGRADED, ACTION_SUSPEND, n, win_rate,
                              expectancy, profit_factor, dd, streak, ratio, reasons)

    # ── Watch (reduce) checks ────────────────────────────────────────────────
    if ratio is not None and ratio < _WATCH_RATIO:
        reasons.append(f"expectancy {ratio:.0%} of baseline (< {_WATCH_RATIO:.0%})")
    if win_rate < base.win_rate - _WATCH_WIN_RATE_GAP:
        reasons.append(f"win rate {win_rate:.0%} below baseline {base.win_rate:.0%}")
    if reasons:
        return StrategyHealth(strategy, WATCH, ACTION_REDUCE, n, win_rate,
                              expectancy, profit_factor, dd, streak, ratio, reasons)

    reasons.append("performing at or above baseline")
    return StrategyHealth(strategy, HEALTHY, ACTION_NONE, n, win_rate,
                          expectancy, profit_factor, dd, streak, ratio, reasons)


def evaluate_all(
    trades_by_strategy: dict[str, list[dict]],
    starting_capital: float,
    overrides: dict[str, StrategyBaseline] | None = None,
    min_sample: int = 20,
) -> list[StrategyHealth]:
    """Grade every strategy; worst (degraded → watch → …) first for triage."""
    order = {DEGRADED: 0, WATCH: 1, HEALTHY: 2, INSUFFICIENT: 3}
    out = [
        evaluate_strategy_health(strat, trades, starting_capital,
                                 baseline_for(strat, overrides), min_sample)
        for strat, trades in trades_by_strategy.items()
    ]
    return sorted(out, key=lambda h: (order.get(h.status, 9), -h.sample_size))


def is_suspended(health: StrategyHealth) -> bool:
    """True when the strategy should accept NO new entries."""
    return health.status in _SUSPENDED
