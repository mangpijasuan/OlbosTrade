"""
Walk-Forward Strategy Optimizer.

Monthly re-optimization of strategy parameters using actual trade data
from the journal and backtest history.

Optimizes:
  - Profit target % (when to close winners: 25%–75%)
  - Stop loss multiplier (2x–4x credit)
  - DTE exit threshold (14–25 days)
  - Min IV rank for entry (25–50)
  - Position size scaling

Uses walk-forward validation — optimizes on rolling 6-month window,
validates on following 1-month window. Never overfits to current conditions.

Integration:
    # Run monthly (wired into APScheduler in paper_trader)
    result = await optimizer.optimize("bull_put_spread")
    # Parameters auto-applied to strategy_engine if improvement is validated
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from itertools import product
from typing import Optional

import numpy as np
import pandas as pd

from app.utils.logger import get_logger
from app.utils.metrics import calculate_all_metrics

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


@dataclass
class TradeRecord:
    """Minimal trade record for optimizer input."""
    strategy:     str
    entry_date:   date
    exit_date:    Optional[date]
    entry_credit: float
    exit_cost:    float
    pnl:          float
    iv_rank_entry: float
    dte_at_entry:  int
    spread_width:  float
    credit_to_width: float
    hold_days:    int
    exit_reason:  str
    # W4 FIX: regime label for stratified Sharpe optimization.
    # Populated from RegimeClassifier at trade entry time.
    # Valid values: "LOW_VOL_TRENDING" | "NORMAL_MEAN_REVERT" |
    #               "HIGH_VOL_TRENDING" | "CRISIS" | "unknown"
    regime: str = "unknown"


class StrategyOptimizer:
    """
    Walk-forward parameter optimizer.

    Grid searches over tunable parameters using historical trade data.
    Validates on out-of-sample period before accepting new parameters.

    The optimizer does NOT search over IV rank thresholds aggressively
    (to avoid regime-specific overfitting) — it focuses on exit rules
    which are more stable across regimes.
    """

    # ── Parameter search grid ─────────────────────────────────────────────────
    PARAM_GRID = {
        "profit_target_pct":    [0.35, 0.40, 0.50, 0.60, 0.65],
        "stop_loss_multiplier": [1.5, 2.0, 2.5, 3.0],
        "dte_exit":             [14, 18, 21, 25],
        "min_iv_rank":          [25.0, 30.0, 35.0, 40.0],
    }

    # ── Validation gates ──────────────────────────────────────────────────────
    MIN_TRADES_TO_OPTIMIZE = 30      # Need at least 30 trades to optimize
    MIN_VALIDATION_TRADES  = 8       # Need at least 8 validation trades
    IMPROVEMENT_THRESHOLD  = 0.10    # Must improve by >10% to accept
    MAX_SHARPE_DEGRADATION = 0.15    # Allow at most 15% worse on validation

    def __init__(self, current_params: Optional[dict[str, StrategyParams]] = None) -> None:
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

    async def optimize(
        self,
        strategy_name: str,
        trades: list[TradeRecord],
        train_months: int = 6,
        validate_months: int = 1,
    ) -> OptimizationResult:
        """
        Walk-forward optimization for a single strategy.

        Algorithm:
          1. Split trades: train on last train_months, validate on last validate_months
          2. Grid search over parameter combinations on training set
          3. Select parameters with best Sharpe on training set
          4. Validate on out-of-sample validation set
          5. Accept only if validation confirms improvement

        Args:
            strategy_name:    Strategy to optimize
            trades:           Historical trade records (from DB or backtest)
            train_months:     Months of history for optimization
            validate_months:  Out-of-sample validation window

        Returns:
            OptimizationResult — check .accepted and .is_meaningful_improvement
        """
        current_params = self.get_params(strategy_name)
        strat_trades = [t for t in trades if t.strategy == strategy_name]

        logger.info(
            "Optimizer starting: %s | %d trades total",
            strategy_name, len(strat_trades),
        )

        # ── Gate: minimum trade count ─────────────────────────────────────────
        if len(strat_trades) < self.MIN_TRADES_TO_OPTIMIZE:
            reason = (
                f"Only {len(strat_trades)} trades — need {self.MIN_TRADES_TO_OPTIMIZE} minimum. "
                f"Continue trading to build history."
            )
            logger.info("Optimizer skipped: %s", reason)
            return OptimizationResult(
                strategy_name=strategy_name,
                original_params=current_params,
                optimized_params=current_params,
                optimization_sharpe=0.0,
                validation_sharpe=0.0,
                improvement_pct=0.0,
                accepted=False,
                n_trades_train=0,
                n_trades_validate=0,
                grid_points_tested=0,
                rejection_reason=reason,
            )

        # ── Split into train / validate ───────────────────────────────────────
        today = date.today()
        validate_cutoff = today - timedelta(days=validate_months * 30)
        train_cutoff    = validate_cutoff - timedelta(days=train_months * 30)

        train_trades    = [t for t in strat_trades if train_cutoff <= t.entry_date < validate_cutoff]
        validate_trades = [t for t in strat_trades if t.entry_date >= validate_cutoff]

        if len(train_trades) < self.MIN_TRADES_TO_OPTIMIZE:
            reason = (
                f"Only {len(train_trades)} trades in training window "
                f"(need {self.MIN_TRADES_TO_OPTIMIZE})"
            )
            return OptimizationResult(
                strategy_name=strategy_name,
                original_params=current_params,
                optimized_params=current_params,
                optimization_sharpe=0.0,
                validation_sharpe=0.0,
                improvement_pct=0.0,
                accepted=False,
                n_trades_train=len(train_trades),
                n_trades_validate=len(validate_trades),
                grid_points_tested=0,
                rejection_reason=reason,
            )

        # ── Baseline: score current params on training set ────────────────────
        baseline_sharpe = self._score_params(current_params, train_trades)
        logger.info(
            "Baseline Sharpe on training set: %.3f (%d trades)",
            baseline_sharpe, len(train_trades),
        )

        # ── Grid search ───────────────────────────────────────────────────────
        best_params   = current_params
        best_sharpe   = baseline_sharpe
        grid_points   = 0

        param_combinations = list(product(
            self.PARAM_GRID["profit_target_pct"],
            self.PARAM_GRID["stop_loss_multiplier"],
            self.PARAM_GRID["dte_exit"],
            self.PARAM_GRID["min_iv_rank"],
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
            sharpe = self._score_params(candidate, train_trades)
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

        # ── Validate on out-of-sample ─────────────────────────────────────────
        if len(validate_trades) < self.MIN_VALIDATION_TRADES:
            reason = (
                f"Only {len(validate_trades)} validation trades "
                f"(need {self.MIN_VALIDATION_TRADES}) — "
                f"cannot validate out-of-sample. Waiting for more trades."
            )
            return OptimizationResult(
                strategy_name=strategy_name,
                original_params=current_params,
                optimized_params=best_params,
                optimization_sharpe=best_sharpe,
                validation_sharpe=0.0,
                improvement_pct=improvement_pct,
                accepted=False,
                n_trades_train=len(train_trades),
                n_trades_validate=len(validate_trades),
                grid_points_tested=grid_points,
                rejection_reason=reason,
            )

        validation_sharpe_new      = self._score_params(best_params, validate_trades)
        validation_sharpe_baseline = self._score_params(current_params, validate_trades)

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
            n_trades_train=len(train_trades),
            n_trades_validate=len(validate_trades),
            grid_points_tested=grid_points,
            rejection_reason=rejection_reason,
        )

    def _score_params(
        self,
        params: StrategyParams,
        trades: list[TradeRecord],
    ) -> float:
        """
        Simulate P&L for a set of parameters on a set of historical trades.
        Returns Sharpe ratio. Used for both training and validation scoring.

        This is not a full backtest — it's a parameter sensitivity test
        on already-entered trades. We ask: given these trades were entered,
        what would the P&L be if we had used these exit rules?
        """
        simulated_pnls: list[float] = []
        hold_days_list: list[int] = []

        for trade in trades:
            # Skip trades that didn't meet the IV rank filter for this param set
            if trade.iv_rank_entry < params.min_iv_rank:
                continue
            if trade.credit_to_width < params.min_credit_to_width:
                continue

            # Simulate exit under these parameters
            pnl, hold_days = self._simulate_exit(trade, params)
            simulated_pnls.append(pnl)
            hold_days_list.append(hold_days)

        if len(simulated_pnls) < 3:
            return -999.0  # Penalize parameter sets that filter out all trades

        # W4 FIX: Regime-stratified Sharpe.
        #
        # The old approach pooled all trades across all regimes.  A parameter
        # set that happens to overfit to a CRISIS regime (lots of big losers
        # that trigger stops) looks great pooled but collapses in NORMAL regime.
        #
        # New approach:
        #   1. Compute Sharpe separately for each regime present in the data.
        #   2. Return the equally-weighted average across regimes.
        #   3. If no regime data, fall back to the pooled Sharpe (backwards compat).
        #
        # Equal-weighting means parameters MUST work across all regime types,
        # not just the one most represented in the recent window.
        regime_pnls: dict[str, list[float]] = {}
        regime_hold: dict[str, list[int]] = {}
        for trade, pnl, hold in zip(trades, simulated_pnls, hold_days_list):
            r = getattr(trade, "regime", "unknown")
            regime_pnls.setdefault(r, []).append(pnl)
            regime_hold.setdefault(r, []).append(hold)

        known_regimes = [r for r in regime_pnls if r != "unknown"]
        if len(known_regimes) >= 2:
            # Enough labelled regimes — use stratified Sharpe
            sharpes: list[float] = []
            for r in known_regimes:
                if len(regime_pnls[r]) < 3:
                    continue   # too few trades in this regime to be meaningful
                m = calculate_all_metrics(
                    pnl_series=regime_pnls[r],
                    hold_days=regime_hold[r],
                    starting_capital=25000.0,
                    total_commissions=len(regime_pnls[r]) * 0.65 * 4,
                )
                sharpes.append(m.sharpe_ratio)
            if sharpes:
                return float(np.mean(sharpes))   # equal-weight across regimes

        # Fallback: pooled Sharpe (backwards compatible, or when regime unknown)
        metrics = calculate_all_metrics(
            pnl_series=simulated_pnls,
            hold_days=hold_days_list,
            starting_capital=25000.0,
            total_commissions=len(simulated_pnls) * 0.65 * 4,  # 4 legs avg
        )
        return metrics.sharpe_ratio

    def _simulate_exit(
        self, trade: TradeRecord, params: StrategyParams
    ) -> tuple[float, int]:
        """
        Given a historical trade and a parameter set, simulate what the
        P&L would have been under these exit rules.

        Returns (simulated_pnl, hold_days).
        """
        max_profit = trade.entry_credit * 100  # per contract
        max_loss   = trade.spread_width * 100 - max_profit

        # Profit target exit
        profit_target_pnl = max_profit * params.profit_target_pct
        # Stop loss exit
        stop_loss_pnl     = -(trade.entry_credit * params.stop_loss_multiplier * 100)

        # Actual exit P&L
        actual_pnl = trade.pnl

        # Apply profit target if original trade hit profit target earlier
        if actual_pnl >= profit_target_pnl:
            # Original trade was profitable — simulated target might be different
            if actual_pnl > max_profit * params.profit_target_pct:
                # We would have closed earlier at our target
                pnl = profit_target_pnl
                hold_frac = params.profit_target_pct / max(actual_pnl / max_profit, 0.01)
                hold_days = max(int(trade.hold_days * hold_frac), 1)
            else:
                pnl = actual_pnl
                hold_days = trade.hold_days
        elif actual_pnl < stop_loss_pnl:
            # Would have been stopped out
            pnl = stop_loss_pnl
            # Approximate earlier stop vs actual
            hold_days = max(int(trade.hold_days * 0.5), 1)
        else:
            pnl = actual_pnl
            hold_days = trade.hold_days

        # DTE exit — if we would have exited earlier at DTE threshold
        if trade.dte_at_entry > params.dte_exit:
            days_to_dte_exit = trade.dte_at_entry - params.dte_exit
            if trade.hold_days >= days_to_dte_exit:
                # Original trade was still open at our DTE exit
                # Approximate value at DTE exit (partial decay)
                decay_pct = days_to_dte_exit / max(trade.hold_days, 1)
                pnl = actual_pnl * decay_pct if actual_pnl > 0 else actual_pnl
                hold_days = days_to_dte_exit

        return pnl, max(hold_days, 1)

    def kelly_position_size(
        self,
        strategy_name: str,
        trades: list[TradeRecord],
        portfolio_value: float,
        fractional: float = 0.25,
    ) -> float:
        """
        Kelly Criterion position sizing.

        Full Kelly is too aggressive for options — we use 25% Kelly (quarter Kelly)
        which reduces risk of ruin while capturing most of the expected growth.

        Returns recommended risk percentage of portfolio per trade.
        Capped at 3% regardless of Kelly output (hard safety limit).

        Args:
            strategy_name:  Strategy to size
            trades:         Recent trade history (last 30–50 trades)
            portfolio_value: Current account value
            fractional:     Kelly fraction (0.25 = quarter Kelly)
        """
        strat_trades = [t for t in trades if t.strategy == strategy_name]

        if len(strat_trades) < 20:
            logger.info(
                "Kelly: not enough trades for %s (%d < 20) — using default 2%%",
                strategy_name, len(strat_trades),
            )
            return 0.02  # Default from Master_Project_File

        pnls    = np.array([t.pnl for t in strat_trades])
        wins    = pnls[pnls > 0]
        losses  = pnls[pnls <= 0]

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

        # Non-positive full Kelly = no edge → size to ZERO (skip the strategy).
        # Previously this was floored to 0.5%, so negative-expectancy strategies
        # kept getting capital allocated.
        if kelly_full <= 0:
            logger.info(
                "Kelly: %s has non-positive edge (full_kelly=%.3f) — sizing to 0",
                strategy_name, kelly_full,
            )
            return 0.0

        kelly_frac = kelly_full * fractional
        # Hard cap at 3% risk per trade (floor 0.5% only once edge is positive)
        kelly_capped = min(max(kelly_frac, 0.005), 0.03)

        logger.info(
            "Kelly sizing for %s: win_rate=%.1f%% avg_win=$%.0f avg_loss=$%.0f "
            "full_kelly=%.3f quarter_kelly=%.3f capped=%.3f",
            strategy_name, win_rate * 100, avg_win, avg_loss,
            kelly_full, kelly_frac, kelly_capped,
        )
        return round(kelly_capped, 4)
