"""
Portfolio performance analytics.

Computes the institutional metric set from closed trades: win rate, profit factor,
expectancy, payoff ratio, average winner/loser, plus equity-curve metrics
(CAGR, max drawdown, Sharpe, Sortino, Calmar, volatility) and average hold time.

Pure functions over a list of trade dicts so it's trivially testable and reusable
by the dashboard, the analytics API, and reports.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd


def _to_date(v) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return pd.Timestamp(v).date()
    except Exception:
        return None


def _curve_metrics(daily_values: list[float]) -> dict:
    """Sharpe / Sortino / Calmar / CAGR / max-DD / vol from a daily equity curve."""
    if len(daily_values) < 2:
        return {"cagr_pct": 0.0, "max_drawdown_pct": 0.0, "sharpe": 0.0,
                "sortino": 0.0, "calmar": 0.0, "volatility_pct": 0.0}
    arr = np.asarray(daily_values, dtype=float)
    daily = np.diff(arr) / arr[:-1]
    years = max(len(arr) / 252.0, 1e-9)
    cagr = (arr[-1] / arr[0]) ** (1 / years) - 1.0 if arr[0] > 0 else 0.0
    vol = float(np.std(daily) * np.sqrt(252)) if len(daily) else 0.0
    sharpe = float(np.mean(daily) / np.std(daily) * np.sqrt(252)) if np.std(daily) > 1e-12 else 0.0
    downside = daily[daily < 0]
    dstd = float(np.std(downside)) if len(downside) else 0.0
    sortino = float(np.mean(daily) / dstd * np.sqrt(252)) if dstd > 1e-12 else 0.0
    peak = np.maximum.accumulate(arr)
    max_dd = float(np.min(arr / peak - 1.0))
    calmar = float(cagr / abs(max_dd)) if max_dd < -1e-9 else 0.0
    return {
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(abs(max_dd) * 100, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "calmar": round(calmar, 2),
        "volatility_pct": round(vol * 100, 2),
    }


def _empty() -> dict:
    return {
        "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
        "total_pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "expectancy": 0.0,
        "profit_factor": 0.0, "payoff_ratio": 0.0, "avg_hold_days": 0.0,
        "cagr_pct": 0.0, "max_drawdown_pct": 0.0, "sharpe": 0.0,
        "sortino": 0.0, "calmar": 0.0, "volatility_pct": 0.0,
        "sample_size_warning": True,
    }


def compute_performance(trades: list[dict], starting_capital: float,
                        min_sample: int = 30) -> dict:
    """
    trades: list of {"pnl": float, "entry_date": date|datetime, "exit_date": ...}.
    Only trades with a non-None pnl are counted.
    """
    rows = [t for t in trades if t.get("pnl") is not None]
    if not rows:
        return _empty()

    pnls = [float(t["pnl"]) for t in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    n = len(pnls)
    total_pnl = float(sum(pnls))
    gross_profit = float(sum(wins))
    gross_loss = float(abs(sum(losses)))
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0

    # Average hold time (days) where both dates exist.
    holds = []
    for t in rows:
        e, x = _to_date(t.get("entry_date")), _to_date(t.get("exit_date"))
        if e and x:
            holds.append((x - e).days)
    avg_hold = float(np.mean(holds)) if holds else 0.0

    # Daily equity curve from exit dates → curve metrics.
    dated = [(d, float(t["pnl"])) for t in rows
             if (d := _to_date(t.get("exit_date"))) is not None]
    curve_metrics = {"cagr_pct": 0.0, "max_drawdown_pct": 0.0, "sharpe": 0.0,
                     "sortino": 0.0, "calmar": 0.0, "volatility_pct": 0.0}
    if dated:
        dated.sort(key=lambda x: x[0])
        s = pd.Series({d: p for d, p in _group_by_day(dated)})
        idx = pd.date_range(s.index.min(), s.index.max(), freq="D")
        daily_pnl = s.reindex(idx, fill_value=0.0)
        equity = float(starting_capital) + daily_pnl.cumsum()
        curve_metrics = _curve_metrics([float(starting_capital)] + list(equity.values))

    return {
        "total_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n, 4),
        "total_pnl": round(total_pnl, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": round(total_pnl / n, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0,
        "payoff_ratio": round(avg_win / abs(avg_loss), 2) if avg_loss < 0 else 0.0,
        "avg_hold_days": round(avg_hold, 1),
        **curve_metrics,
        "sample_size_warning": n < min_sample,
    }


def _group_by_day(dated: list[tuple]) -> list[tuple]:
    """Sum P&L per calendar day (pd.Timestamp keys)."""
    agg: dict = {}
    for d, p in dated:
        ts = pd.Timestamp(d)
        agg[ts] = agg.get(ts, 0.0) + p
    return sorted(agg.items())
