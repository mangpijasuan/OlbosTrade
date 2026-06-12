"""
Strategy ranker — runs all 4 strategies on the same date range and ranks by Sharpe.
Used by the Research page and /api/research/comparison endpoint.
"""

from dataclasses import dataclass, field
from typing import Optional

from app.services.backtester import Backtester, BacktestResult
from app.utils.logger import get_logger
from app.utils.metrics import PerformanceMetrics

logger = get_logger(__name__)

STRATEGY_NAMES = [
    "bull_put_spread",
    "bear_call_spread",
    "iron_condor",
    "bull_call_debit_spread",
]


@dataclass
class RankedStrategy:
    """A single strategy with its backtest metrics and rank."""
    rank: int
    strategy: str
    sharpe_ratio: float
    total_return_pct: float
    win_rate: float
    max_drawdown_pct: float
    total_trades: int
    profit_factor: float
    calmar_ratio: float
    commission_drag_pct: float
    metrics: Optional[PerformanceMetrics] = None


@dataclass
class ComparisonResult:
    """Full strategy comparison output."""
    start_date: str
    end_date: str
    starting_capital: float
    rankings: list[RankedStrategy]
    best_strategy: str
    worst_strategy: str
    backtest_results: dict[str, BacktestResult] = field(default_factory=dict)


class StrategyRanker:
    """
    Runs all four strategies on the same date range and ranks by Sharpe ratio.
    """

    def __init__(self, backtester: Backtester) -> None:
        self.backtester = backtester

    async def run_comparison(
        self,
        start_date: str,
        end_date: str,
        starting_capital: float = 25000.0,
    ) -> ComparisonResult:
        """
        Run all 4 strategies on identical conditions and rank them.

        Args:
            start_date:       "YYYY-MM-DD"
            end_date:         "YYYY-MM-DD"
            starting_capital: Same starting capital for all strategies

        Returns:
            ComparisonResult with ranked strategies
        """
        logger.info(
            "Strategy comparison starting: %s → %s, capital=$%.0f",
            start_date, end_date, starting_capital,
        )

        results: dict[str, BacktestResult] = {}

        for strategy_name in STRATEGY_NAMES:
            logger.info("Running %s...", strategy_name)
            try:
                result = await self.backtester.run(
                    strategy_name=strategy_name,
                    start_date=start_date,
                    end_date=end_date,
                    starting_capital=starting_capital,
                )
                results[strategy_name] = result
                logger.info(
                    "  %s: return=%.1f%% Sharpe=%.2f trades=%d",
                    strategy_name,
                    (result.metrics.total_return_pct * 100) if result.metrics else 0,
                    result.metrics.sharpe_ratio if result.metrics else 0,
                    len([t for t in result.trades if t.exit_reason != "backtest_end"]),
                )
            except Exception as exc:
                logger.error("Strategy %s failed: %s", strategy_name, exc)

        if not results:
            raise RuntimeError("All strategies failed — no comparison results")

        # Rank by Sharpe ratio
        ranked = []
        for strategy_name, result in results.items():
            m = result.metrics
            ranked.append(RankedStrategy(
                rank=0,  # set after sort
                strategy=strategy_name,
                sharpe_ratio=m.sharpe_ratio if m else 0.0,
                total_return_pct=m.total_return_pct if m else 0.0,
                win_rate=m.win_rate if m else 0.0,
                max_drawdown_pct=m.max_drawdown_pct if m else 0.0,
                total_trades=m.total_trades if m else 0,
                profit_factor=m.profit_factor if m else 0.0,
                calmar_ratio=m.calmar_ratio if m else 0.0,
                commission_drag_pct=m.commission_drag_pct if m else 0.0,
                metrics=m,
            ))

        ranked.sort(key=lambda x: x.sharpe_ratio, reverse=True)
        for i, r in enumerate(ranked):
            r.rank = i + 1

        best = ranked[0].strategy if ranked else ""
        worst = ranked[-1].strategy if ranked else ""

        logger.info(
            "Comparison complete — Best: %s (Sharpe %.2f), Worst: %s (Sharpe %.2f)",
            best, ranked[0].sharpe_ratio if ranked else 0,
            worst, ranked[-1].sharpe_ratio if ranked else 0,
        )

        return ComparisonResult(
            start_date=start_date,
            end_date=end_date,
            starting_capital=starting_capital,
            rankings=ranked,
            best_strategy=best,
            worst_strategy=worst,
            backtest_results=results,
        )
