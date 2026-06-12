"""
Portfolio performance metrics.
Used by the backtester and strategy ranker.
All functions are pure — no DB access, no side effects.
"""

import math
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional


@dataclass
class PerformanceMetrics:
    """Full set of metrics returned after a backtest or live period."""
    total_return_pct: float
    annualized_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown_pct: float
    max_drawdown_duration_days: int
    win_rate: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: float
    avg_loss: float
    avg_hold_days: float
    commission_drag_pct: float
    expectancy: float


def calculate_sharpe(returns: pd.Series, risk_free_rate: float = 0.05) -> float:
    """Annualized Sharpe ratio from daily returns."""
    if len(returns) < 2 or returns.std() == 0:
        return 0.0
    excess = returns - (risk_free_rate / 252)
    return float((excess.mean() / excess.std()) * math.sqrt(252))


def calculate_sortino(returns: pd.Series, risk_free_rate: float = 0.05) -> float:
    """Sortino ratio — penalizes downside volatility only."""
    if len(returns) < 2:
        return 0.0
    excess = returns - (risk_free_rate / 252)
    downside = returns[returns < 0]
    if len(downside) == 0 or downside.std() == 0:
        return float("inf") if excess.mean() > 0 else 0.0
    return float((excess.mean() / downside.std()) * math.sqrt(252))


def calculate_max_drawdown(equity_curve: pd.Series) -> tuple[float, int]:
    """
    Maximum drawdown as a percentage and its duration in days.
    Returns (max_drawdown_pct, max_duration_days).
    max_drawdown_pct is negative (e.g. -0.15 = -15%).
    """
    if len(equity_curve) < 2:
        return 0.0, 0
    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    max_dd = float(drawdown.min())

    # Duration: longest time spent below previous high
    underwater = drawdown < 0
    durations = []
    current = 0
    for is_under in underwater:
        if is_under:
            current += 1
        else:
            if current > 0:
                durations.append(current)
            current = 0
    if current > 0:
        durations.append(current)
    max_duration = max(durations) if durations else 0
    return max_dd, max_duration


def calculate_calmar(annualized_return: float, max_drawdown: float) -> float:
    """Calmar ratio = annualized return / abs(max drawdown)."""
    if max_drawdown == 0:
        return 0.0
    return annualized_return / abs(max_drawdown)


def calculate_profit_factor(gross_wins: float, gross_losses: float) -> float:
    """Profit factor = gross wins / gross losses. > 1 is profitable."""
    if gross_losses == 0:
        return float("inf") if gross_wins > 0 else 0.0
    return gross_wins / abs(gross_losses)


def calculate_all_metrics(
    pnl_series: list[float],
    hold_days: list[int],
    starting_capital: float,
    total_commissions: float,
    equity_curve: Optional[pd.Series] = None,
    risk_free_rate: float = 0.05,
) -> PerformanceMetrics:
    """
    Compute all performance metrics from a list of trade P&Ls.

    Args:
        pnl_series:        List of per-trade P&L in dollars
        hold_days:         Days held per trade
        starting_capital:  Starting account value
        total_commissions: Total commissions paid across all trades
        equity_curve:      Optional daily equity series for drawdown
        risk_free_rate:    Annual risk-free rate (default 5%)
    """
    if not pnl_series:
        return PerformanceMetrics(
            total_return_pct=0, annualized_return_pct=0, sharpe_ratio=0,
            sortino_ratio=0, calmar_ratio=0, max_drawdown_pct=0,
            max_drawdown_duration_days=0, win_rate=0, profit_factor=0,
            total_trades=0, winning_trades=0, losing_trades=0,
            avg_win=0, avg_loss=0, avg_hold_days=0,
            commission_drag_pct=0, expectancy=0,
        )

    pnl = np.array(pnl_series)
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]

    total_trades = len(pnl)
    winning_trades = len(wins)
    losing_trades = len(losses)
    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

    total_pnl = float(pnl.sum())
    total_return_pct = total_pnl / starting_capital

    avg_hold = float(np.mean(hold_days)) if hold_days else 0.0
    total_days = sum(hold_days) if hold_days else 252
    years = max(total_days / 252, 1 / 252)
    annualized_return = (1 + total_return_pct) ** (1 / years) - 1

    gross_wins = float(wins.sum()) if len(wins) > 0 else 0.0
    gross_losses = float(losses.sum()) if len(losses) > 0 else 0.0
    profit_factor = calculate_profit_factor(gross_wins, gross_losses)

    avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(losses.mean()) if len(losses) > 0 else 0.0
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

    commission_drag = total_commissions / starting_capital

    # Sharpe/Sortino from trade returns
    returns = pd.Series(pnl / starting_capital)
    sharpe = calculate_sharpe(returns, risk_free_rate)
    sortino = calculate_sortino(returns, risk_free_rate)

    if equity_curve is not None and len(equity_curve) > 1:
        max_dd, max_dd_days = calculate_max_drawdown(equity_curve)
    else:
        cumulative = starting_capital + np.cumsum(pnl)
        max_dd, max_dd_days = calculate_max_drawdown(pd.Series(cumulative))

    calmar = calculate_calmar(annualized_return, max_dd)

    return PerformanceMetrics(
        total_return_pct=round(total_return_pct, 6),
        annualized_return_pct=round(annualized_return, 6),
        sharpe_ratio=round(sharpe, 4),
        sortino_ratio=round(sortino, 4),
        calmar_ratio=round(calmar, 4),
        max_drawdown_pct=round(max_dd, 6),
        max_drawdown_duration_days=max_dd_days,
        win_rate=round(win_rate, 4),
        profit_factor=round(profit_factor, 4),
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        avg_win=round(avg_win, 4),
        avg_loss=round(avg_loss, 4),
        avg_hold_days=round(avg_hold, 1),
        commission_drag_pct=round(commission_drag, 6),
        expectancy=round(expectancy, 4),
    )
