"""
Walk-Forward Strategy Optimizer.

Grid-searches exit-rule parameters (profit target %, stop-loss multiplier,
DTE exit, min IV rank) for one of the 4 options strategies, scoring each
candidate against a REAL walk-forward backtest (via Backtester.run()) over
a training window, then validating the winner out-of-sample on a following
window. Only accepted if validation confirms the improvement.

No production caller yet (backend-only for now — see the Track 2D plan).
No regime-stratified scoring in this version: Backtester/BacktestTrade
carry no regime label, so this uses the same pooled-Sharpe path
calculate_all_metrics() already computes — a deliberate v1 simplification,
not a silent regression. Regime-aware backtesting is separate, future scope.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from itertools import product
from typing import Optional, TYPE_CHECKING

import numpy as np
import pandas as pd

from app.services.strategy_engine import StrategyExitParams
from app.utils.logger import get_logger
from app.utils.metrics import calculate_all_metrics

if TYPE_CHECKING:
    from app.services.backtester import Backtester, BacktestResult

logger = get_logger(__name__)


@dataclass
class StrategyParams:
    """
    Tunable parameters for a single strategy.
    Defaults match the original Master_Project_File spec.
    """
    strategy_name:         str
    profit_target_pct:     float = 0.50   # Close at 50% of max profit
    stop_loss_multiplier:  float = 2.0    # Stop at 2x credit received
    dte_exit:              int   = 21     # Exit at 21 DTE
    min_iv_rank:           float = 30.0  # Minimum IV rank to enter
    min_credit_to_width:   float = 0.20  # Min credit/width ratio
    size_pct_of_portfolio: float = 0.02  # Risk per trade
    last_optimized:        Optional[datetime] = None
    optimization_sharpe:   Optional[float] = None
    validation_sharpe:     Optional[float] = None


@dataclass
class OptimizationResult:
    """Result of a walk-forward optimization run."""
    strategy_name:        str
    original_params:      StrategyParams
    optimized_params:     StrategyParams
    optimization_sharpe:  float       # Sharpe on training window
    validation_sharpe:    float       # Sharpe on validation window (out-of-sample)
    improvement_pct:      float       # % improvement vs original params
    accepted:             bool        # True if validation confirms improvement
    n_trades_train:       int
    n_trades_validate:    int
    grid_points_tested:   int
    completed_at:         datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    rejection_reason:     Optional[str] = None

    @property
    def is_meaningful_improvement(self) -> bool:
        """Only accept if improvement > 10% to avoid noise."""
        return self.accepted and self.improvement_pct > 10.0


class StrategyOptimizer:
    """
    Walk-forward parameter optimizer.

    Grid searches over tunable exit-rule parameters, scoring each candidate
    against a real Backtester.run() over a training window, then validating
    the winner out-of-sample. Validates on out-of-sample period before
    accepting new parameters.
    """

    # ── Parameter search grid ─────────────────────────────────────────────────
    # Full grid (opt-in via optimize(full_grid=True) — 320 combinations,
    # each a real backtest; wall-clock cost not yet measured, see plan).
    PARAM_GRID = {
        "profit_target_pct":    [0.35, 0.40, 0.50, 0.60, 0.65],
        "stop_loss_multiplier": [1.5, 2.0, 2.5, 3.0],
        "dte_exit":             [14, 18, 21, 25],
        "min_iv_rank":          [25.0, 30.0, 35.0, 40.0],
    }
    # Default grid — 18 combinations. min_iv_rank dropped: not yet wired
    # into any strategy's generate_signal(), so varying it never changes
    # an entry decision (a dead axis) — see strategy_engine.StrategyExitParams.
    REDUCED_PARAM_GRID = {
        "profit_target_pct":    [0.40, 0.50, 0.60],
        "stop_loss_multiplier": [1.5, 2.0, 3.0],
        "dte_exit":             [14, 21],
    }

    # ── Validation gates ──────────────────────────────────────────────────────
    MIN_TRADES_TO_OPTIMIZE = 30      # Need at least 30 trades to optimize
    MIN_VALIDATION_TRADES  = 8       # Need at least 8 validation trades
    IMPROVEMENT_THRESHOLD  = 0.10    # Must improve by >10% to accept
    MAX_SHARPE_DEGRADATION = 0.15    # Allow at most 15% worse on validation

    def __init__(
        self,
        backtester: "Backtester",
        current_params: Optional[dict[str, StrategyParams]] = None,
    ) -> None:
        self.backtester = backtester
        self.params: dict[str, StrategyParams] = current_params or {}
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        defaults = ["bull_put_spread", "bear_call_spread", "iron_condor", "bull_call_debit_spread"]
        for name in defaults:
            if name not in self.params:
                self.params[name] = StrategyParams(strategy_name=name)

    def get_params(self, strategy_name: str) -> StrategyParams:
        """Get current parameters for a strategy."""
        return self.params.get(strategy_name, StrategyParams(strategy_name=strategy_name))

    async def _fetch_window(self, window_start: str, window_end: str) -> tuple[pd.DataFrame, Optional[pd.DataFrame]]:
        """
        Fetch SPY OHLCV (with 60-day warmup buffer, matching
        Backtester.run()'s own warmup convention) and VIX once for a date
        window, for reuse across every grid-point backtest over that same
        window — avoids N redundant fetches for what is otherwise the
        identical network call repeated per candidate.
        """
        warmup_start = (pd.Timestamp(window_start) - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
        spy_df = await self.backtester.fetcher.fetch_ohlcv("SPY", warmup_start, window_end)

        vix_df: Optional[pd.DataFrame] = None
        try:
            import yfinance as _yf
            loop = asyncio.get_running_loop()
            _vix_raw = await loop.run_in_executor(
                None,
                lambda: _yf.Ticker("^VIX").history(start=warmup_start, end=window_end, auto_adjust=True),
            )
            if not _vix_raw.empty:
                _vix_raw.index = pd.to_datetime(_vix_raw.index).tz_localize(None)
                vix_df = _vix_raw
        except Exception as exc:
            logger.warning("Optimizer: failed to pre-fetch VIX (%s) — falling back to RV proxy", exc)

        return spy_df, vix_df

    async def _run_and_score(
        self,
        strategy_name: str,
        params: StrategyParams,
        start: str,
        end: str,
        spy_df: pd.DataFrame,
        vix_df: Optional[pd.DataFrame],
    ) -> tuple["BacktestResult", float]:
        exit_params = StrategyExitParams(
            profit_target_pct=params.profit_target_pct,
            stop_loss_multiplier=params.stop_loss_multiplier,
            dte_exit=params.dte_exit,
            min_iv_rank=params.min_iv_rank,
        )
        result = await self.backtester.run(
            strategy_name, start, end,
            strategy_params=exit_params, spy_df=spy_df, vix_df=vix_df,
        )
        return result, self._score_params(result)

    async def optimize(
        self,
        strategy_name: str,
        end_date: Optional[str] = None,
        train_months: int = 6,
        validate_months: int = 1,
        full_grid: bool = False,
    ) -> OptimizationResult:
        """
        Walk-forward optimization for a single strategy, scored against
        real Backtester.run() calls (not a post-hoc heuristic).

        Algorithm:
          1. Compute train/validate date windows (calendar-cutoff, same
             arithmetic as before)
          2. Grid search: real backtest per candidate over the train window
          3. Select the candidate with the best Sharpe on the train window
          4. Validate the winner (and the current baseline) on the
             out-of-sample validate window
          5. Accept only if validation confirms the improvement

        Args:
            strategy_name:    Strategy to optimize
            end_date:         "YYYY-MM-DD", defaults to today
            train_months:     Months of history for the training window
            validate_months:  Out-of-sample validation window, in months
            full_grid:        Use the full 320-combo PARAM_GRID instead of
                              the smaller REDUCED_PARAM_GRID default — real
                              backtests, real wall-clock cost, not yet
                              measured for the full grid.

        Returns:
            OptimizationResult — check .accepted and .is_meaningful_improvement
        """
        current_params = self.get_params(strategy_name)

        today = pd.Timestamp(end_date) if end_date else pd.Timestamp(date.today())
        validate_end   = today
        validate_start = validate_end - pd.Timedelta(days=validate_months * 30)
        train_end      = validate_start
        train_start    = train_end - pd.Timedelta(days=train_months * 30)

        train_start_s, train_end_s = train_start.strftime("%Y-%m-%d"), train_end.strftime("%Y-%m-%d")
        validate_start_s, validate_end_s = validate_start.strftime("%Y-%m-%d"), validate_end.strftime("%Y-%m-%d")

        logger.info(
            "Optimizer starting: %s | train %s→%s | validate %s→%s",
            strategy_name, train_start_s, train_end_s, validate_start_s, validate_end_s,
        )

        train_spy_df, train_vix_df = await self._fetch_window(train_start_s, train_end_s)

        # ── Baseline: score current params on the training window ─────────────
        baseline_result, baseline_sharpe = await self._run_and_score(
            strategy_name, current_params, train_start_s, train_end_s, train_spy_df, train_vix_df,
        )
        n_trades_train = len(baseline_result.trades)
        logger.info(
            "Baseline Sharpe on training window: %.3f (%d trades)",
            baseline_sharpe, n_trades_train,
        )

        if n_trades_train < self.MIN_TRADES_TO_OPTIMIZE:
            reason = (
                f"Only {n_trades_train} trades in training window "
                f"(need {self.MIN_TRADES_TO_OPTIMIZE}) — check empirically whether "
                f"this threshold suits a single-strategy backtest window"
            )
            return OptimizationResult(
                strategy_name=strategy_name,
                original_params=current_params,
                optimized_params=current_params,
                optimization_sharpe=baseline_sharpe,
                validation_sharpe=0.0,
                improvement_pct=0.0,
                accepted=False,
                n_trades_train=n_trades_train,
                n_trades_validate=0,
                grid_points_tested=0,
                rejection_reason=reason,
            )

        # ── Grid search — real backtest per candidate, train window ────────────
        best_params   = current_params
        best_sharpe   = baseline_sharpe
        grid_points   = 0

        grid = self.PARAM_GRID if full_grid else self.REDUCED_PARAM_GRID
        iv_rank_values = grid.get("min_iv_rank", [current_params.min_iv_rank])
        param_combinations = list(product(
            grid["profit_target_pct"],
            grid["stop_loss_multiplier"],
            grid["dte_exit"],
            iv_rank_values,
        ))

        for pt, sl, dte, iv_r in param_combinations:
            candidate = StrategyParams(
                strategy_name=strategy_name,
                profit_target_pct=pt,
                stop_loss_multiplier=sl,
                dte_exit=dte,
                min_iv_rank=iv_r,
                min_credit_to_width=current_params.min_credit_to_width,
                size_pct_of_portfolio=current_params.size_pct_of_portfolio,
            )
            _, sharpe = await self._run_and_score(
                strategy_name, candidate, train_start_s, train_end_s, train_spy_df, train_vix_df,
            )
            grid_points += 1

            if sharpe > best_sharpe:
                best_sharpe  = sharpe
                best_params  = candidate

        improvement_pct = (
            ((best_sharpe - baseline_sharpe) / abs(baseline_sharpe)) * 100
            if baseline_sharpe != 0 else 0.0
        )

        logger.info(
            "Grid search complete: %d combinations tested | "
            "best Sharpe=%.3f (baseline=%.3f, +%.1f%%)",
            grid_points, best_sharpe, baseline_sharpe, improvement_pct,
        )

        # ── Validate on out-of-sample window ────────────────────────────────────
        validate_spy_df, validate_vix_df = await self._fetch_window(validate_start_s, validate_end_s)

        validate_new_result, validation_sharpe_new = await self._run_and_score(
            strategy_name, best_params, validate_start_s, validate_end_s, validate_spy_df, validate_vix_df,
        )
        _, validation_sharpe_baseline = await self._run_and_score(
            strategy_name, current_params, validate_start_s, validate_end_s, validate_spy_df, validate_vix_df,
        )
        n_trades_validate = len(validate_new_result.trades)

        if n_trades_validate < self.MIN_VALIDATION_TRADES:
            reason = (
                f"Only {n_trades_validate} validation trades "
                f"(need {self.MIN_VALIDATION_TRADES}) — "
                f"cannot validate out-of-sample. Waiting for more history."
            )
            return OptimizationResult(
                strategy_name=strategy_name,
                original_params=current_params,
                optimized_params=best_params,
                optimization_sharpe=best_sharpe,
                validation_sharpe=0.0,
                improvement_pct=improvement_pct,
                accepted=False,
                n_trades_train=n_trades_train,
                n_trades_validate=n_trades_validate,
                grid_points_tested=grid_points,
                rejection_reason=reason,
            )

        # Accept if: validation improves OR doesn't degrade by more than threshold
        sharpe_change = validation_sharpe_new - validation_sharpe_baseline
        accepted = (
            improvement_pct > self.IMPROVEMENT_THRESHOLD * 100
            and sharpe_change > -self.MAX_SHARPE_DEGRADATION
        )

        rejection_reason = None
        if not accepted:
            if improvement_pct <= self.IMPROVEMENT_THRESHOLD * 100:
                rejection_reason = (
                    f"Improvement {improvement_pct:.1f}% below threshold "
                    f"{self.IMPROVEMENT_THRESHOLD * 100:.0f}% — keeping current params"
                )
            else:
                rejection_reason = (
                    f"Validation Sharpe degraded by {-sharpe_change:.3f} "
                    f"(max allowed: {self.MAX_SHARPE_DEGRADATION:.2f}) — "
                    f"optimized params may be overfit"
                )

        if accepted:
            best_params.last_optimized     = datetime.now(timezone.utc)
            best_params.optimization_sharpe = best_sharpe
            best_params.validation_sharpe   = validation_sharpe_new
            self.params[strategy_name]      = best_params
            logger.info(
                "Optimization ACCEPTED for %s: "
                "profit_target=%.0f%% stop=%.1fx dte=%d iv_rank=%.0f "
                "| validation_sharpe=%.3f",
                strategy_name,
                best_params.profit_target_pct * 100,
                best_params.stop_loss_multiplier,
                best_params.dte_exit,
                best_params.min_iv_rank,
                validation_sharpe_new,
            )
        else:
            logger.info(
                "Optimization REJECTED for %s: %s",
                strategy_name, rejection_reason,
            )

        return OptimizationResult(
            strategy_name=strategy_name,
            original_params=current_params,
            optimized_params=best_params if accepted else current_params,
            optimization_sharpe=best_sharpe,
            validation_sharpe=validation_sharpe_new,
            improvement_pct=improvement_pct,
            accepted=accepted,
            n_trades_train=n_trades_train,
            n_trades_validate=n_trades_validate,
            grid_points_tested=grid_points,
            rejection_reason=rejection_reason,
        )

    def _score_params(self, backtest_result: "BacktestResult") -> float:
        """
        Sharpe ratio of a real backtest's trades. No regime stratification
        (BacktestTrade carries no regime label) — pooled Sharpe only, same
        formula this file's old fallback path already used when regime data
        was unavailable.
        """
        pnl_series = [t.pnl for t in backtest_result.trades]
        hold_days  = [t.hold_days for t in backtest_result.trades]

        if len(pnl_series) < 3:
            return -999.0  # Penalize parameter sets that produce too few trades to score

        metrics = calculate_all_metrics(
            pnl_series=pnl_series,
            hold_days=hold_days,
            starting_capital=25000.0,
            total_commissions=len(pnl_series) * 0.65 * 4,  # 4 legs avg
        )
        return metrics.sharpe_ratio

    def kelly_position_size(
        self,
        strategy_name: str,
        pnls: list[float],
        fractional: float = 0.25,
    ) -> float:
        """
        Kelly Criterion position sizing.

        Full Kelly is too aggressive for options — we use 25% Kelly (quarter Kelly)
        which reduces risk of ruin while capturing most of the expected growth.

        Returns recommended risk percentage of portfolio per trade.
        Capped at 3% regardless of Kelly output (hard safety limit).

        Args:
            strategy_name:  Strategy being sized (logging only — pnls is
                            already the caller's own filtered trade history)
            pnls:           Recent per-trade P&L, e.g. from closed Trade
                            rows or a BacktestResult (last 30-50 trades)
            fractional:     Kelly fraction (0.25 = quarter Kelly)
        """
        if len(pnls) < 20:
            logger.info(
                "Kelly: not enough trades for %s (%d < 20) — using default 2%%",
                strategy_name, len(pnls),
            )
            return 0.02  # Default from Master_Project_File

        pnl_arr = np.array(pnls)
        wins    = pnl_arr[pnl_arr > 0]
        losses  = pnl_arr[pnl_arr <= 0]

        if len(wins) == 0 or len(losses) == 0:
            return 0.02

        win_rate = len(wins) / len(pnls)
        avg_win  = float(wins.mean())
        avg_loss = abs(float(losses.mean()))

        if avg_loss == 0:
            return 0.02

        # Kelly formula: f* = W/L - (1-W)/W_avg
        # Where W = win rate, L = loss rate, W_avg = avg win / avg loss
        win_loss_ratio = avg_win / avg_loss
        kelly_full = win_rate - (1 - win_rate) / win_loss_ratio
        kelly_frac = kelly_full * fractional

        # Hard cap at 3% risk per trade
        kelly_capped = min(max(kelly_frac, 0.005), 0.03)

        logger.info(
            "Kelly sizing for %s: win_rate=%.1f%% avg_win=$%.0f avg_loss=$%.0f "
            "full_kelly=%.3f quarter_kelly=%.3f capped=%.3f",
            strategy_name, win_rate * 100, avg_win, avg_loss,
            kelly_full, kelly_frac, kelly_capped,
        )
        return round(kelly_capped, 4)
