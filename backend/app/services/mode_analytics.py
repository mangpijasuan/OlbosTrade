"""
Mode Analytics — Performance breakdown by trading mode.

Answers the core question:
"Which mode makes me the most money?"

Compares Conservative, Balanced, Aggressive, and Scalper
across win rate, avg P&L, Sharpe ratio, max drawdown,
and expectancy — so you can see clearly which mode
is earning and which is dragging.

Every trade tagged with trading_mode_at_entry feeds
into this module automatically. No manual logging needed.

Integration:
    GET /api/analytics/by-mode         → full breakdown
    GET /api/analytics/mode-comparison → head-to-head table
    GET /api/analytics/mode/{mode}     → single mode deep dive
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
import math

from app.utils.logger import get_logger

logger = get_logger(__name__)

ALL_MODES = ["conservative", "balanced", "aggressive", "scalper"]


@dataclass
class ModeTrade:
    """Minimal trade record for mode analytics."""
    trade_id:     str
    mode:         str
    strategy:     str
    pnl:          float
    pnl_pct:      float
    entry_date:   date
    exit_date:    Optional[date]
    hold_days:    int
    signal_score: float
    exit_reason:  str
    iv_rank:      float = 0.0


@dataclass
class ModeStats:
    """
    Complete performance statistics for one trading mode.
    This is what shows on the mode comparison dashboard.
    """
    mode:              str
    display_name:      str
    trade_count:       int
    win_count:         int
    loss_count:        int

    # Core metrics
    win_rate:          float        # 0.0 – 1.0
    avg_win:           float        # average winning trade in dollars
    avg_loss:          float        # average losing trade in dollars (negative)
    expectancy:        float        # (win_rate × avg_win) + (loss_rate × avg_loss)
    profit_factor:     float        # gross wins / gross losses

    # Return metrics
    total_pnl:         float
    avg_pnl_per_trade: float
    total_return_pct:  float        # vs starting capital

    # Risk metrics
    max_drawdown_pct:  float
    sharpe_ratio:      float
    avg_hold_days:     float

    # Signal quality
    avg_signal_score:  float
    score_vs_outcome:  float        # correlation: does higher score = better outcome?

    # Exit analysis
    profit_target_exits: int        # closed at profit target
    stop_loss_exits:     int        # closed at stop loss
    dte_exits:           int        # closed at DTE threshold
    other_exits:         int

    # Trend
    last_5_trades_pnl:  list[float] = field(default_factory=list)
    is_improving:        bool = False   # last 5 better than overall avg?

    # UI
    ui_color:            str = "blue"
    recommendation:      str = ""


@dataclass
class ModeComparison:
    """
    Head-to-head comparison of all active modes.
    The top-level view on the analytics dashboard.
    """
    generated_at:    datetime
    starting_capital: float
    date_range:       str
    total_trades:     int
    modes:            dict[str, ModeStats]
    best_mode:        str           # by Sharpe ratio
    most_trades:      str           # by volume
    highest_win_rate: str
    best_expectancy:  str
    recommendation:   str


class ModeAnalyticsEngine:
    """
    Computes performance statistics broken down by trading mode.

    Input:  List of ModeTrade records (loaded from DB)
    Output: ModeComparison with full stats per mode

    All calculations are pure functions — no DB access here.
    DB loading happens in the API route.
    """

    def __init__(self, starting_capital: float = 25000.0) -> None:
        self.starting_capital = starting_capital

    def compute_comparison(
        self,
        trades: list[ModeTrade],
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> ModeComparison:
        """
        Compute full mode comparison from a list of trades.

        Args:
            trades:     All closed trades with mode tags
            date_from:  Optional filter start date
            date_to:    Optional filter end date

        Returns:
            ModeComparison with stats per mode
        """
        # Filter by date range
        filtered = trades
        if date_from:
            filtered = [t for t in filtered if t.entry_date >= date_from]
        if date_to:
            filtered = [t for t in filtered if t.entry_date <= date_to]

        # Group by mode
        by_mode: dict[str, list[ModeTrade]] = {m: [] for m in ALL_MODES}
        for trade in filtered:
            mode = trade.mode.lower()
            if mode in by_mode:
                by_mode[mode].append(trade)
            else:
                by_mode.setdefault(mode, []).append(trade)

        # Compute stats per mode
        mode_stats: dict[str, ModeStats] = {}
        for mode, mode_trades in by_mode.items():
            if mode_trades:
                stats = self._compute_mode_stats(mode, mode_trades)
                mode_stats[mode] = stats

        if not mode_stats:
            return self._empty_comparison(date_from, date_to, len(filtered))

        # Find best performers
        best_sharpe   = max(mode_stats.values(), key=lambda s: s.sharpe_ratio)
        most_trades   = max(mode_stats.values(), key=lambda s: s.trade_count)
        highest_wr    = max(mode_stats.values(), key=lambda s: s.win_rate)
        best_exp      = max(mode_stats.values(), key=lambda s: s.expectancy)

        recommendation = self._generate_recommendation(mode_stats)

        date_str = (
            f"{date_from} to {date_to}"
            if date_from and date_to
            else "all time"
        )

        return ModeComparison(
            generated_at=datetime.utcnow(),
            starting_capital=self.starting_capital,
            date_range=date_str,
            total_trades=len(filtered),
            modes=mode_stats,
            best_mode=best_sharpe.mode,
            most_trades=most_trades.mode,
            highest_win_rate=highest_wr.mode,
            best_expectancy=best_exp.mode,
            recommendation=recommendation,
        )

    def _compute_mode_stats(
        self, mode: str, trades: list[ModeTrade]
    ) -> ModeStats:
        """Compute all statistics for a single mode."""
        pnls    = [t.pnl for t in trades]
        wins    = [p for p in pnls if p > 0]
        losses  = [p for p in pnls if p <= 0]

        trade_count = len(trades)
        win_count   = len(wins)
        loss_count  = len(losses)
        win_rate    = win_count / trade_count if trade_count > 0 else 0.0

        avg_win  = sum(wins)  / len(wins)  if wins   else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        # Expectancy: what you expect to make per trade on average
        expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

        # Profit factor: gross wins / gross losses
        gross_wins   = sum(wins)
        gross_losses = abs(sum(losses))
        profit_factor = (
            gross_wins / gross_losses if gross_losses > 0
            else float("inf") if gross_wins > 0 else 0.0
        )

        total_pnl         = sum(pnls)
        avg_pnl_per_trade = total_pnl / trade_count if trade_count > 0 else 0.0
        total_return_pct  = total_pnl / self.starting_capital

        # Max drawdown from this mode's equity curve
        equity = self.starting_capital
        peak   = equity
        max_dd = 0.0
        for pnl in pnls:
            equity += pnl
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        # Sharpe ratio (annualized from trade returns)
        returns = [p / self.starting_capital for p in pnls]
        sharpe  = self._sharpe(returns)

        avg_hold = (
            sum(t.hold_days for t in trades) / trade_count
            if trade_count > 0 else 0.0
        )

        avg_signal_score = (
            sum(t.signal_score for t in trades) / trade_count
            if trade_count > 0 else 0.0
        )

        # Signal score vs outcome correlation
        score_vs_outcome = self._score_outcome_correlation(trades)

        # Exit reason breakdown
        exit_counts = {
            "profit_target": 0,
            "stop_loss": 0,
            "dte_exit": 0,
            "other": 0,
        }
        for t in trades:
            reason = t.exit_reason.lower()
            if "profit" in reason or "target" in reason:
                exit_counts["profit_target"] += 1
            elif "stop" in reason or "loss" in reason:
                exit_counts["stop_loss"] += 1
            elif "dte" in reason or "time" in reason or "expir" in reason:
                exit_counts["dte_exit"] += 1
            else:
                exit_counts["other"] += 1

        # Last 5 trades trend
        last_5 = [t.pnl for t in sorted(trades, key=lambda t: t.entry_date)[-5:]]
        last_5_avg = sum(last_5) / len(last_5) if last_5 else 0.0
        is_improving = last_5_avg > avg_pnl_per_trade

        # UI color and display name
        color_map = {
            "conservative": "green",
            "balanced":     "blue",
            "aggressive":   "orange",
            "scalper":      "red",
        }
        name_map = {
            "conservative": "Conservative",
            "balanced":     "Balanced",
            "aggressive":   "Aggressive",
            "scalper":      "Scalper",
        }

        recommendation = self._mode_recommendation(
            mode, win_rate, expectancy, sharpe, trade_count, is_improving
        )

        return ModeStats(
            mode=mode,
            display_name=name_map.get(mode, mode.title()),
            trade_count=trade_count,
            win_count=win_count,
            loss_count=loss_count,
            win_rate=round(win_rate, 4),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            expectancy=round(expectancy, 2),
            profit_factor=round(min(profit_factor, 99.99), 4),
            total_pnl=round(total_pnl, 2),
            avg_pnl_per_trade=round(avg_pnl_per_trade, 2),
            total_return_pct=round(total_return_pct, 6),
            max_drawdown_pct=round(max_dd, 4),
            sharpe_ratio=round(sharpe, 4),
            avg_hold_days=round(avg_hold, 1),
            avg_signal_score=round(avg_signal_score, 4),
            score_vs_outcome=round(score_vs_outcome, 4),
            profit_target_exits=exit_counts["profit_target"],
            stop_loss_exits=exit_counts["stop_loss"],
            dte_exits=exit_counts["dte_exit"],
            other_exits=exit_counts["other"],
            last_5_trades_pnl=last_5,
            is_improving=is_improving,
            ui_color=color_map.get(mode, "blue"),
            recommendation=recommendation,
        )

    def _sharpe(self, returns: list[float], rf: float = 0.05) -> float:
        """Annualized Sharpe from a list of per-trade returns."""
        if len(returns) < 3:
            return 0.0
        n   = len(returns)
        avg = sum(returns) / n
        excess = [r - (rf / 252) for r in returns]
        avg_excess = sum(excess) / n
        variance = sum((r - avg_excess) ** 2 for r in excess) / max(n - 1, 1)
        std = math.sqrt(variance) if variance > 0 else 0.0
        if std == 0:
            return 0.0
        # Annualize assuming ~252 trades/year (rough for monthly strategies)
        return round((avg_excess / std) * math.sqrt(252), 4)

    def _score_outcome_correlation(self, trades: list[ModeTrade]) -> float:
        """
        Pearson correlation between signal score and trade P&L.
        Positive = higher scores predict better outcomes (model is working).
        Negative = higher scores predict worse outcomes (model is backwards).
        Near zero = score has no predictive value.
        """
        if len(trades) < 5:
            return 0.0
        scores = [t.signal_score for t in trades]
        pnls   = [t.pnl for t in trades]
        n = len(scores)
        mean_s = sum(scores) / n
        mean_p = sum(pnls) / n
        num   = sum((s - mean_s) * (p - mean_p) for s, p in zip(scores, pnls))
        den_s = math.sqrt(sum((s - mean_s) ** 2 for s in scores))
        den_p = math.sqrt(sum((p - mean_p) ** 2 for p in pnls))
        if den_s == 0 or den_p == 0:
            return 0.0
        return num / (den_s * den_p)

    def _mode_recommendation(
        self,
        mode: str,
        win_rate: float,
        expectancy: float,
        sharpe: float,
        trade_count: int,
        is_improving: bool,
    ) -> str:
        """Generate a one-line recommendation for this mode."""
        if trade_count < 10:
            return f"Need {10 - trade_count} more trades for reliable statistics."
        if expectancy <= 0:
            return "Negative expectancy — this mode is losing money on average. Consider disabling."
        if sharpe < 0.3:
            return "Low Sharpe ratio — returns are not worth the risk. Review entry conditions."
        if win_rate < 0.50:
            return "Win rate below 50%. Check if signal threshold needs raising for this mode."
        if is_improving:
            return "Recent performance improving. Mode is gaining edge."
        if sharpe > 1.0 and win_rate > 0.60:
            return "Strong performance. Consider increasing position size slightly."
        return "Performing within expected range. Maintain current settings."

    def _generate_recommendation(self, mode_stats: dict[str, ModeStats]) -> str:
        """Overall portfolio recommendation across all modes."""
        if not mode_stats:
            return "No trade data yet."

        # Find negative expectancy modes
        losing = [s.mode for s in mode_stats.values()
                  if s.expectancy < 0 and s.trade_count >= 10]
        if losing:
            return (
                f"Disable {', '.join(losing)} mode(s) — negative expectancy "
                f"after 10+ trades. Focus capital on profitable modes."
            )

        # Find best Sharpe
        by_sharpe = sorted(mode_stats.values(), key=lambda s: s.sharpe_ratio, reverse=True)
        best = by_sharpe[0]
        if best.sharpe_ratio > 1.0:
            return (
                f"{best.display_name} mode leads with Sharpe {best.sharpe_ratio:.2f}. "
                f"Consider allocating more capital to it."
            )

        return "All active modes showing positive expectancy. Keep running consistently."

    def _empty_comparison(
        self,
        date_from: Optional[date],
        date_to: Optional[date],
        total: int,
    ) -> ModeComparison:
        return ModeComparison(
            generated_at=datetime.utcnow(),
            starting_capital=self.starting_capital,
            date_range="no data",
            total_trades=total,
            modes={},
            best_mode="",
            most_trades="",
            highest_win_rate="",
            best_expectancy="",
            recommendation="No trades recorded yet. Start paper trading to generate data.",
        )
