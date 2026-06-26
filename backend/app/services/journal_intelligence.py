"""
Trade Journal Intelligence.

Mines closed-trade history for patterns a human would otherwise miss: which
regimes and strategies actually make money, whether high-signal-score trades win
more, how winners and losers differ in hold time, and which (strategy × regime)
setups recur as losers. Pure stats over trade dicts → feeds the dashboard and
grounds the AI Research Assistant with real numbers.

Each trade dict: {"pnl", "strategy", "regime", "signal_score",
                  "entry_date", "exit_date"} (missing fields tolerated).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional


def _to_date(v) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except Exception:
        return None


def _bucket_stats(rows: list[dict], key: str) -> dict[str, dict]:
    """win-rate / total-pnl / expectancy grouped by a categorical key."""
    groups: dict[str, list[float]] = {}
    for t in rows:
        groups.setdefault(str(t.get(key) or "unknown"), []).append(float(t["pnl"]))
    out: dict[str, dict] = {}
    for k, pnls in groups.items():
        wins = [p for p in pnls if p > 0]
        out[k] = {
            "trades": len(pnls),
            "win_rate": round(len(wins) / len(pnls), 4) if pnls else 0.0,
            "total_pnl": round(sum(pnls), 2),
            "expectancy": round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
        }
    return out


def _hold_days(t: dict) -> Optional[int]:
    e, x = _to_date(t.get("entry_date")), _to_date(t.get("exit_date"))
    return (x - e).days if e and x else None


def _best_worst(stats: dict[str, dict], metric: str = "expectancy"):
    if not stats:
        return None, None
    ranked = sorted(stats.items(), key=lambda kv: kv[1][metric])
    return ranked[-1][0], ranked[0][0]   # best, worst


def analyze(trades: list[dict], min_setup_sample: int = 3) -> dict:
    """Full journal-intelligence report over closed trades with known P&L."""
    rows = [t for t in trades if t.get("pnl") is not None]
    if not rows:
        return {"total_trades": 0, "by_regime": {}, "by_strategy": {},
                "best_regime": None, "worst_regime": None,
                "best_strategy": None, "worst_strategy": None,
                "hold_time": {}, "signal_score": {},
                "recurring_losing_setups": [], "insights": ["No closed trades yet."]}

    by_regime = _bucket_stats(rows, "regime")
    by_strategy = _bucket_stats(rows, "strategy")
    best_regime, worst_regime = _best_worst(by_regime)
    best_strategy, worst_strategy = _best_worst(by_strategy)

    # Hold-time: winners vs losers.
    win_holds = [d for t in rows if t["pnl"] > 0 and (d := _hold_days(t)) is not None]
    loss_holds = [d for t in rows if t["pnl"] <= 0 and (d := _hold_days(t)) is not None]
    hold_time = {
        "avg_winner_days": round(sum(win_holds) / len(win_holds), 1) if win_holds else None,
        "avg_loser_days": round(sum(loss_holds) / len(loss_holds), 1) if loss_holds else None,
    }

    # Does signal score predict wins?
    win_scores = [float(t["signal_score"]) for t in rows
                  if t["pnl"] > 0 and t.get("signal_score") is not None]
    loss_scores = [float(t["signal_score"]) for t in rows
                   if t["pnl"] <= 0 and t.get("signal_score") is not None]
    signal_score = {
        "avg_winner_score": round(sum(win_scores) / len(win_scores), 3) if win_scores else None,
        "avg_loser_score": round(sum(loss_scores) / len(loss_scores), 3) if loss_scores else None,
    }

    # Recurring losing setups: (strategy × regime) with negative expectancy.
    setups: dict[tuple, list[float]] = {}
    for t in rows:
        setups.setdefault((str(t.get("strategy") or "unknown"),
                           str(t.get("regime") or "unknown")), []).append(float(t["pnl"]))
    recurring = []
    for (strat, regime), pnls in setups.items():
        if len(pnls) >= min_setup_sample and sum(pnls) < 0:
            recurring.append({
                "strategy": strat, "regime": regime, "trades": len(pnls),
                "total_pnl": round(sum(pnls), 2),
                "win_rate": round(len([p for p in pnls if p > 0]) / len(pnls), 4),
            })
    recurring.sort(key=lambda r: r["total_pnl"])

    insights = _insights(by_regime, best_regime, worst_regime,
                         best_strategy, worst_strategy, hold_time, signal_score, recurring)

    return {
        "total_trades": len(rows),
        "by_regime": by_regime,
        "by_strategy": by_strategy,
        "best_regime": best_regime, "worst_regime": worst_regime,
        "best_strategy": best_strategy, "worst_strategy": worst_strategy,
        "hold_time": hold_time,
        "signal_score": signal_score,
        "recurring_losing_setups": recurring,
        "insights": insights,
    }


def _insights(by_regime, best_regime, worst_regime, best_strategy, worst_strategy,
              hold_time, signal_score, recurring) -> list[str]:
    out: list[str] = []
    if best_strategy and best_strategy != worst_strategy:
        out.append(f"Strongest strategy: {best_strategy}; weakest: {worst_strategy}.")
    if best_regime and best_regime != worst_regime:
        out.append(f"Best regime to trade: {best_regime}; worst: {worst_regime}.")
    aw, al = hold_time.get("avg_winner_days"), hold_time.get("avg_loser_days")
    if aw is not None and al is not None and al > aw:
        out.append(f"Losers are held longer ({al}d) than winners ({aw}d) — "
                   "consider tighter stops.")
    ws, ls = signal_score.get("avg_winner_score"), signal_score.get("avg_loser_score")
    if ws is not None and ls is not None:
        if ws > ls:
            out.append("Higher signal scores correlate with wins — the ranker is informative.")
        else:
            out.append("Signal score does NOT separate winners from losers — review the ranker.")
    if recurring:
        top = recurring[0]
        out.append(f"Recurring losing setup: {top['strategy']} in {top['regime']} "
                   f"({top['trades']} trades, ${top['total_pnl']}).")
    if not out:
        out.append("Not enough signal yet to surface strong patterns.")
    return out
