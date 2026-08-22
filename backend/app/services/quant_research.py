"""
Quant Research & Strategy Lab — core service layer (Phase 1).

Classes
-------
StrategyBuilder      Build and validate strategy configs from building blocks.
ExecutionSimulator   Model realistic fills: slippage, spread, commissions.
PerformanceCalculator Compute the full metric suite from a trade list.
BacktestEngine       Fetch OHLCV data and execute a deterministic backtest.

Design rules
------------
* No external LLM or ML — all logic is deterministic and rule-based.
* Reuses existing utils.metrics helpers for Sharpe, Sortino, drawdown.
* Fetches market data via yfinance (same as the rest of OlbosTrade).
* Never modifies live trading state.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from app.utils.logger import get_logger
from app.utils.metrics import (
    PerformanceMetrics,
    calculate_sharpe,
    calculate_sortino,
    calculate_max_drawdown,
)

logger = get_logger(__name__)

# ── Strategy building blocks ───────────────────────────────────────────────────

INDICATOR_KEYS = [
    "EMA", "SMA", "RSI", "ADX", "MACD", "MACD_SIGNAL", "BB_UPPER", "BB_LOWER",
    "BB_MID", "ATR", "VOLUME", "VOLUME_MA", "CLOSE", "OPEN", "HIGH", "LOW",
]

REGIME_TYPES = [
    "LOW_VOL_TRENDING", "NORMAL_MEAN_REVERT", "HIGH_VOL_TRENDING", "CRISIS", "ANY",
]

TIMEFRAME_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h",
    "1d": "1d", "1wk": "1wk",
}

LAYER_KEYS = ["entry", "filter", "confirmation", "regime", "risk", "exit", "execution"]


@dataclass
class ConditionBlock:
    """A single condition in a strategy layer."""
    indicator: str          # e.g. "EMA"
    period: int             # e.g. 20
    operator: str           # ">" | "<" | ">=" | "<=" | "==" | "crosses_above" | "crosses_below"
    compare_to: str         # indicator key or "VALUE"
    compare_period: int = 0 # period for compare indicator (0 = not applicable)
    value: float = 0.0      # used when compare_to == "VALUE"

    def to_dict(self) -> dict:
        return {
            "indicator":      self.indicator,
            "period":         self.period,
            "operator":       self.operator,
            "compare_to":     self.compare_to,
            "compare_period": self.compare_period,
            "value":          self.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConditionBlock":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class StrategyConfig:
    """
    Fully deterministic strategy configuration.
    Serialises to/from plain JSON — safe to store as an immutable snapshot.
    """
    name: str
    direction: str = "LONG"          # LONG | SHORT | BOTH

    # Per-layer condition lists (joined by logic_op)
    entry: list[dict] = field(default_factory=list)
    entry_logic: str = "AND"         # AND | OR

    filter: list[dict] = field(default_factory=list)
    filter_logic: str = "AND"

    confirmation: list[dict] = field(default_factory=list)
    confirmation_logic: str = "AND"

    regime: str = "ANY"              # must match REGIME_TYPES

    # Risk layer
    stop_atr_mult: float = 1.5       # stop = entry - N * ATR(14)
    target_atr_mult: float = 3.0     # target = entry + N * ATR(14)
    position_size_pct: float = 2.0   # % of equity per trade

    # Exit layer (additional conditions beyond stop/target)
    exit: list[dict] = field(default_factory=list)
    exit_logic: str = "OR"

    # Execution layer
    trading_hours_start: str = "09:30"
    trading_hours_end: str = "16:00"
    max_concurrent_positions: int = 5
    commission_per_share: float = 0.005
    spread_pct: float = 0.001        # 0.1% half-spread
    slippage_pct: float = 0.001      # 0.1% adverse slippage on fill
    max_daily_loss_pct: float = 3.0
    max_drawdown_pct: float = 15.0

    def to_dict(self) -> dict:
        return {
            "name":           self.name,
            "direction":      self.direction,
            "entry":          self.entry,
            "entry_logic":    self.entry_logic,
            "filter":         self.filter,
            "filter_logic":   self.filter_logic,
            "confirmation":   self.confirmation,
            "confirmation_logic": self.confirmation_logic,
            "regime":         self.regime,
            "stop_atr_mult":  self.stop_atr_mult,
            "target_atr_mult": self.target_atr_mult,
            "position_size_pct": self.position_size_pct,
            "exit":           self.exit,
            "exit_logic":     self.exit_logic,
            "trading_hours_start": self.trading_hours_start,
            "trading_hours_end":   self.trading_hours_end,
            "max_concurrent_positions": self.max_concurrent_positions,
            "commission_per_share":     self.commission_per_share,
            "spread_pct":     self.spread_pct,
            "slippage_pct":   self.slippage_pct,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_drawdown_pct":   self.max_drawdown_pct,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StrategyConfig":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


class StrategyBuilder:
    """
    Validate and assemble StrategyConfig objects from user-supplied dicts.
    All methods are pure — no DB access.
    """

    @staticmethod
    def build(data: dict) -> StrategyConfig:
        """Validate and return a StrategyConfig from raw dict input."""
        errors: list[str] = []

        name = (data.get("name") or "").strip()
        if not name:
            errors.append("name is required")

        direction = data.get("direction", "LONG").upper()
        if direction not in ("LONG", "SHORT", "BOTH"):
            errors.append(f"direction must be LONG, SHORT, or BOTH; got {direction!r}")

        regime = data.get("regime", "ANY").upper()
        if regime not in REGIME_TYPES:
            errors.append(f"regime must be one of {REGIME_TYPES}; got {regime!r}")

        entry = data.get("entry", [])
        if not entry:
            errors.append("at least one entry condition is required")

        if errors:
            raise ValueError("; ".join(errors))

        return StrategyConfig(
            name=name,
            direction=direction,
            entry=entry,
            entry_logic=data.get("entry_logic", "AND").upper(),
            filter=data.get("filter", []),
            filter_logic=data.get("filter_logic", "AND").upper(),
            confirmation=data.get("confirmation", []),
            confirmation_logic=data.get("confirmation_logic", "AND").upper(),
            regime=regime,
            stop_atr_mult=float(data.get("stop_atr_mult", 1.5)),
            target_atr_mult=float(data.get("target_atr_mult", 3.0)),
            position_size_pct=float(data.get("position_size_pct", 2.0)),
            exit=data.get("exit", []),
            exit_logic=data.get("exit_logic", "OR").upper(),
            trading_hours_start=data.get("trading_hours_start", "09:30"),
            trading_hours_end=data.get("trading_hours_end", "16:00"),
            max_concurrent_positions=int(data.get("max_concurrent_positions", 5)),
            commission_per_share=float(data.get("commission_per_share", 0.005)),
            spread_pct=float(data.get("spread_pct", 0.001)),
            slippage_pct=float(data.get("slippage_pct", 0.001)),
            max_daily_loss_pct=float(data.get("max_daily_loss_pct", 3.0)),
            max_drawdown_pct=float(data.get("max_drawdown_pct", 15.0)),
        )


# ── Indicator computation ──────────────────────────────────────────────────────

def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all supported technical indicators on a standard OHLCV DataFrame.
    Returns a new DataFrame with additional columns.  Uses only historical data
    at each bar — no look-ahead.
    """
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]
    vol   = df["Volume"]

    out = df.copy()

    # EMA / SMA for common periods
    for p in [5, 10, 20, 50, 100, 200]:
        out[f"EMA_{p}"]  = close.ewm(span=p, adjust=False).mean()
        out[f"SMA_{p}"]  = close.rolling(p).mean()

    # RSI(14)
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    out["RSI_14"] = 100 - (100 / (1 + rs))

    # ATR(14)
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    out["ATR_14"] = tr.rolling(14).mean()

    # ADX(14)
    dm_plus  = (high.diff()).clip(lower=0)
    dm_minus = (-low.diff()).clip(lower=0)
    dm_plus  = dm_plus.where(dm_plus > dm_minus, 0)
    dm_minus = dm_minus.where(dm_minus > dm_plus, 0)
    atr14    = out["ATR_14"]
    di_plus  = 100 * dm_plus.rolling(14).mean()  / atr14.replace(0, np.nan)
    di_minus = 100 * dm_minus.rolling(14).mean() / atr14.replace(0, np.nan)
    dx       = (100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan))
    out["ADX_14"] = dx.rolling(14).mean()

    # MACD (12/26/9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26
    out["MACD"]        = macd
    out["MACD_SIGNAL"] = macd.ewm(span=9, adjust=False).mean()

    # Bollinger Bands (20, 2σ)
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    out["BB_MID"]   = sma20
    out["BB_UPPER"] = sma20 + 2 * std20
    out["BB_LOWER"] = sma20 - 2 * std20

    # Volume MA (20-day)
    out["VOLUME_MA_20"] = vol.rolling(20).mean()
    out["VOLUME"]       = vol
    out["CLOSE"]        = close
    out["OPEN"]         = df["Open"]
    out["HIGH"]         = high
    out["LOW"]          = low

    return out


def _resolve_col(indicator: str, period: int, df: pd.DataFrame) -> Optional[pd.Series]:
    """Map an indicator + period to a DataFrame column."""
    ind = indicator.upper()
    # Try exact match first
    col = f"{ind}_{period}"
    if col in df.columns:
        return df[col]
    # Fall back to base name (CLOSE, VOLUME, etc.)
    if ind in df.columns:
        return df[ind]
    return None


def _eval_condition(cond: dict, df: pd.DataFrame) -> pd.Series:
    """
    Evaluate a single ConditionBlock against every row in df.
    Returns a boolean Series (True = condition met on that bar).
    """
    lhs_col = _resolve_col(cond["indicator"], cond.get("period", 0), df)
    if lhs_col is None:
        logger.warning("Unknown indicator %s_%s — skipping", cond["indicator"], cond.get("period"))
        return pd.Series(False, index=df.index)

    op = cond.get("operator", ">")
    compare_to = cond.get("compare_to", "VALUE")

    if compare_to == "VALUE":
        rhs = float(cond.get("value", 0))
    else:
        rhs_col = _resolve_col(compare_to, cond.get("compare_period", 0), df)
        if rhs_col is None:
            logger.warning("Unknown compare indicator %s — skipping", compare_to)
            return pd.Series(False, index=df.index)
        rhs = rhs_col

    if op == ">":
        result = lhs_col > rhs
    elif op == ">=":
        result = lhs_col >= rhs
    elif op == "<":
        result = lhs_col < rhs
    elif op == "<=":
        result = lhs_col <= rhs
    elif op == "==":
        result = lhs_col == rhs
    elif op == "crosses_above":
        result = (lhs_col > rhs) & (lhs_col.shift(1) <= (rhs if isinstance(rhs, (int, float)) else rhs.shift(1)))
    elif op == "crosses_below":
        result = (lhs_col < rhs) & (lhs_col.shift(1) >= (rhs if isinstance(rhs, (int, float)) else rhs.shift(1)))
    else:
        result = pd.Series(False, index=df.index)

    return result.fillna(False)


def _eval_layer(conditions: list[dict], logic: str, df: pd.DataFrame) -> pd.Series:
    """Combine a list of conditions with AND or OR logic."""
    if not conditions:
        return pd.Series(True, index=df.index)

    results = [_eval_condition(c, df) for c in conditions]
    combined = results[0]
    for r in results[1:]:
        if logic == "OR":
            combined = combined | r
        else:
            combined = combined & r
    return combined


# ── Execution simulator ────────────────────────────────────────────────────────

@dataclass
class SimulatedFill:
    price: float
    commission: float
    slippage: float
    spread_cost: float
    total_cost: float   # commission + slippage + spread_cost


class ExecutionSimulator:
    """
    Models realistic fills without assuming perfect execution.
    All parameters come from StrategyConfig.
    """

    def __init__(self, cfg: StrategyConfig) -> None:
        self.commission_per_share = cfg.commission_per_share
        self.spread_pct           = cfg.spread_pct
        self.slippage_pct         = cfg.slippage_pct

    def simulate_entry(self, price: float, shares: int) -> SimulatedFill:
        """Entry: buy at ask (price * (1 + spread) + slippage)."""
        spread_cost   = price * self.spread_pct
        slippage_cost = price * self.slippage_pct
        fill_price    = price + spread_cost + slippage_cost
        commission    = shares * self.commission_per_share
        return SimulatedFill(
            price=fill_price,
            commission=commission,
            slippage=slippage_cost * shares,
            spread_cost=spread_cost * shares,
            total_cost=commission + slippage_cost * shares + spread_cost * shares,
        )

    def simulate_exit(self, price: float, shares: int) -> SimulatedFill:
        """Exit: sell at bid (price * (1 - spread) - slippage)."""
        spread_cost   = price * self.spread_pct
        slippage_cost = price * self.slippage_pct
        fill_price    = price - spread_cost - slippage_cost
        commission    = shares * self.commission_per_share
        return SimulatedFill(
            price=fill_price,
            commission=commission,
            slippage=slippage_cost * shares,
            spread_cost=spread_cost * shares,
            total_cost=commission + slippage_cost * shares + spread_cost * shares,
        )


# ── Simulated trade record ─────────────────────────────────────────────────────

@dataclass
class QuantTrade:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    entry_date: Optional[date] = None
    exit_date:  Optional[date] = None
    entry_price: float = 0.0
    exit_price:  float = 0.0
    shares: int = 1
    direction: str = "LONG"
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0
    commission_paid: float = 0.0
    hold_days: int = 0
    mfe: float = 0.0  # Maximum Favorable Excursion (gross)
    mae: float = 0.0  # Maximum Adverse Excursion (gross)

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "entry_date":    str(self.entry_date) if self.entry_date else None,
            "exit_date":     str(self.exit_date) if self.exit_date else None,
            "entry_price":   round(self.entry_price, 4),
            "exit_price":    round(self.exit_price, 4),
            "shares":        self.shares,
            "direction":     self.direction,
            "exit_reason":   self.exit_reason,
            "pnl":           round(self.pnl, 2),
            "pnl_pct":       round(self.pnl_pct, 4),
            "commission_paid": round(self.commission_paid, 2),
            "hold_days":     self.hold_days,
            "mfe":           round(self.mfe, 4),
            "mae":           round(self.mae, 4),
        }


# ── Performance calculator ─────────────────────────────────────────────────────

class PerformanceCalculator:
    """
    Compute the full metric suite from a completed trade list + equity curve.
    All calculations are pure functions — no side effects.
    """

    @staticmethod
    def compute(
        trades: list[QuantTrade],
        equity_curve: pd.Series,
        starting_capital: float,
        years: float,
    ) -> dict:
        if not trades:
            return PerformanceCalculator._empty_metrics(starting_capital)

        pnls = [t.pnl for t in trades]
        wins  = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        total_pnl     = sum(pnls)
        total_return  = total_pnl / starting_capital
        cagr          = (1 + total_return) ** (1 / max(years, 0.01)) - 1 if total_return > -1 else -1.0
        win_rate      = len(wins) / len(trades)
        gross_win     = sum(wins)  or 0.0
        gross_loss    = abs(sum(losses)) or 1e-9
        profit_factor = gross_win / gross_loss
        expectancy    = total_pnl / len(trades)
        avg_duration  = sum(t.hold_days for t in trades) / len(trades)

        # Returns series from equity curve
        if len(equity_curve) > 1:
            daily_returns = equity_curve.pct_change().dropna()
            sharpe  = calculate_sharpe(daily_returns)
            sortino = calculate_sortino(daily_returns)
            max_dd, max_dd_days = calculate_max_drawdown(equity_curve)
        else:
            sharpe = sortino = 0.0
            max_dd = 0.0
            max_dd_days = 0

        consecutive_losses = PerformanceCalculator._max_consecutive_losses(pnls)
        avg_mfe = sum(t.mfe for t in trades) / len(trades)
        avg_mae = sum(t.mae for t in trades) / len(trades)

        ending_capital = starting_capital + total_pnl

        return {
            # Return metrics
            "total_return_pct":    round(total_return * 100, 4),
            "cagr_pct":            round(cagr * 100, 4),
            "total_pnl":           round(total_pnl, 2),
            "ending_capital":      round(ending_capital, 2),
            "avg_return_per_trade": round(expectancy, 2),
            # Risk metrics
            "sharpe_ratio":        round(sharpe, 4),
            "sortino_ratio":       round(sortino, 4),
            "max_drawdown_pct":    round(max_dd * 100, 4),
            "max_drawdown_days":   max_dd_days,
            "consecutive_losses":  consecutive_losses,
            # Trade quality
            "win_rate":            round(win_rate * 100, 4),
            "profit_factor":       round(profit_factor, 4),
            "expectancy":          round(expectancy, 2),
            "avg_trade_duration":  round(avg_duration, 1),
            "avg_mfe":             round(avg_mfe, 4),
            "avg_mae":             round(avg_mae, 4),
            "total_trades":        len(trades),
            "winning_trades":      len(wins),
            "losing_trades":       len(losses),
            # Disclaimer
            "disclaimer":          "BACKTESTED — NOT LIVE PERFORMANCE",
        }

    @staticmethod
    def _max_consecutive_losses(pnls: list[float]) -> int:
        max_c = cur = 0
        for p in pnls:
            if p <= 0:
                cur += 1
                max_c = max(max_c, cur)
            else:
                cur = 0
        return max_c

    @staticmethod
    def _empty_metrics(starting_capital: float) -> dict:
        return {
            "total_return_pct": 0.0, "cagr_pct": 0.0, "total_pnl": 0.0,
            "ending_capital": starting_capital, "avg_return_per_trade": 0.0,
            "sharpe_ratio": 0.0, "sortino_ratio": 0.0,
            "max_drawdown_pct": 0.0, "max_drawdown_days": 0,
            "consecutive_losses": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "expectancy": 0.0, "avg_trade_duration": 0.0,
            "avg_mfe": 0.0, "avg_mae": 0.0,
            "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
            "disclaimer": "BACKTESTED — NOT LIVE PERFORMANCE",
        }


# ── Backtest engine ────────────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    run_id: str
    symbol: str
    start_date: date
    end_date: date
    starting_capital: float
    metrics: dict
    equity_curve: list[dict]   # [{date, equity}]
    drawdown_curve: list[dict] # [{date, drawdown_pct}]
    trades: list[dict]         # serialised QuantTrade dicts
    monthly_returns: list[dict] # [{year, month, return_pct}]


class BacktestEngine:
    """
    Walk-forward backtester for equity strategies defined with StrategyConfig.

    Execution model
    ---------------
    * Entry  → next bar's open (signal generated at bar close, filled at next open).
    * Slippage, spread, and commission applied via ExecutionSimulator.
    * Stops and targets checked against each bar's High/Low (intra-bar).
    * MFE/MAE tracked per trade.
    * Position sizing = position_size_pct % of current equity.
    """

    def run(
        self,
        cfg: StrategyConfig,
        symbol: str,
        start_date: str,
        end_date: str,
        starting_capital: float = 100_000.0,
        timeframe: str = "1d",
    ) -> BacktestResult:
        run_id = str(uuid.uuid4())
        logger.info("BacktestEngine.run: %s %s %s–%s capital=%.0f",
                    cfg.name, symbol, start_date, end_date, starting_capital)

        raw = self._fetch_ohlcv(symbol, start_date, end_date, timeframe)
        if raw.empty or len(raw) < 30:
            raise ValueError(f"Insufficient data for {symbol} in the requested period.")

        df = _compute_indicators(raw)

        # Use .shift(1) for signal generation — close of PRIOR bar only.
        sig_df = df.shift(1)

        exec_sim = ExecutionSimulator(cfg)
        trades: list[QuantTrade] = []
        equity = starting_capital
        equity_ts: list[tuple[date, float]] = []
        daily_loss = 0.0
        open_position: Optional[dict] = None
        open_count = 0

        bars = df.index.tolist()

        # Pre-compute layer signals on shifted data for all bars at once (vectorised)
        entry_signal  = _eval_layer(cfg.entry,        cfg.entry_logic,        sig_df)
        filter_signal = _eval_layer(cfg.filter,       cfg.filter_logic,       sig_df)
        confirm_sig   = _eval_layer(cfg.confirmation, cfg.confirmation_logic, sig_df)
        exit_signal   = _eval_layer(cfg.exit,         cfg.exit_logic,         sig_df)

        for i, ts in enumerate(bars):
            bar = df.loc[ts]
            bar_date = ts.date() if hasattr(ts, "date") else ts

            # Track equity at each bar
            if open_position:
                bar_equity = equity + open_position["unrealised_pnl_fn"](float(bar["Close"]))
            else:
                bar_equity = equity
            equity_ts.append((bar_date, bar_equity))

            # Risk limits
            dd_pct = 100 * (1 - equity / starting_capital)
            if dd_pct >= cfg.max_drawdown_pct:
                if open_position:
                    trades.append(self._close_trade(open_position, float(bar["Open"]), bar_date, exec_sim, "MAX_DRAWDOWN"))
                    equity += trades[-1].pnl
                    open_position = None
                    open_count = 0
                continue

            # ── EXIT open position ─────────────────────────────────────────────
            if open_position:
                entry_p = open_position["entry_price"]
                atr14   = open_position["atr14"]
                direction = open_position["direction"]

                if direction == "LONG":
                    stop_price   = entry_p - cfg.stop_atr_mult   * atr14
                    target_price = entry_p + cfg.target_atr_mult * atr14
                    hit_stop     = float(bar["Low"])  <= stop_price
                    hit_target   = float(bar["High"]) >= target_price
                else:
                    stop_price   = entry_p + cfg.stop_atr_mult   * atr14
                    target_price = entry_p - cfg.target_atr_mult * atr14
                    hit_stop     = float(bar["High"]) >= stop_price
                    hit_target   = float(bar["Low"])  <= target_price

                # Update MFE/MAE
                close_now = float(bar["Close"])
                if direction == "LONG":
                    open_position["mfe"] = max(open_position["mfe"], float(bar["High"]) - entry_p)
                    open_position["mae"] = min(open_position["mae"], float(bar["Low"])  - entry_p)
                else:
                    open_position["mfe"] = max(open_position["mfe"], entry_p - float(bar["Low"]))
                    open_position["mae"] = min(open_position["mae"], entry_p - float(bar["High"]))

                exit_reason = None
                exit_price  = None
                if hit_stop:
                    exit_reason = "STOP"
                    exit_price  = stop_price
                elif hit_target:
                    exit_reason = "TARGET"
                    exit_price  = target_price
                elif exit_signal.loc[ts]:
                    exit_reason = "SIGNAL"
                    exit_price  = float(bar["Open"])

                if exit_reason:
                    t = self._close_trade(open_position, exit_price, bar_date, exec_sim, exit_reason)
                    trades.append(t)
                    equity += t.pnl
                    daily_loss += min(0, t.pnl)
                    open_position = None
                    open_count -= 1

            # ── ENTRY ──────────────────────────────────────────────────────────
            if (open_count < cfg.max_concurrent_positions
                    and entry_signal.loc[ts]
                    and filter_signal.loc[ts]
                    and confirm_sig.loc[ts]
                    and abs(daily_loss / equity) * 100 < cfg.max_daily_loss_pct):

                atr14 = float(sig_df.loc[ts].get("ATR_14", float(bar["ATR_14"]) if "ATR_14" in bar.index else 1.0))
                if pd.isna(atr14) or atr14 == 0:
                    continue

                direction = "LONG" if cfg.direction in ("LONG", "BOTH") else "SHORT"
                entry_price_raw = float(bar["Open"])
                position_value  = equity * (cfg.position_size_pct / 100)
                shares = max(1, int(position_value / entry_price_raw))

                fill = exec_sim.simulate_entry(entry_price_raw, shares)

                def _unrealised(cur_price: float, d=direction, ep=fill.price) -> float:
                    if d == "LONG":
                        return (cur_price - ep) * shares
                    return (ep - cur_price) * shares

                open_position = {
                    "id":          str(uuid.uuid4()),
                    "entry_date":  bar_date,
                    "entry_price": fill.price,
                    "shares":      shares,
                    "direction":   direction,
                    "atr14":       atr14,
                    "commission_paid": fill.commission,
                    "mfe": 0.0,
                    "mae": 0.0,
                    "unrealised_pnl_fn": _unrealised,
                }
                open_count += 1

        # Close any remaining position at last bar
        if open_position and bars:
            last_bar = df.iloc[-1]
            last_date = bars[-1]
            last_date = last_date.date() if hasattr(last_date, "date") else last_date
            t = self._close_trade(open_position, float(last_bar["Close"]), last_date, exec_sim, "END_OF_DATA")
            trades.append(t)
            equity += t.pnl

        # Build equity/drawdown curves
        eq_series = pd.Series(
            [e for _, e in equity_ts],
            index=[d for d, _ in equity_ts],
        )
        rolling_max   = eq_series.cummax()
        dd_series     = (eq_series - rolling_max) / rolling_max * 100

        equity_curve   = [{"date": str(d), "equity": round(float(e), 2)} for d, e in zip(eq_series.index, eq_series)]
        drawdown_curve = [{"date": str(d), "drawdown_pct": round(float(v), 4)} for d, v in zip(dd_series.index, dd_series)]

        # Monthly returns heatmap
        monthly_returns = self._compute_monthly_returns(eq_series)

        years = max((pd.Timestamp(end_date) - pd.Timestamp(start_date)).days / 365.25, 0.01)
        metrics = PerformanceCalculator.compute(trades, eq_series, starting_capital, years)

        return BacktestResult(
            run_id=run_id,
            symbol=symbol,
            start_date=pd.Timestamp(start_date).date(),
            end_date=pd.Timestamp(end_date).date(),
            starting_capital=starting_capital,
            metrics=metrics,
            equity_curve=equity_curve,
            drawdown_curve=drawdown_curve,
            trades=[t.to_dict() for t in trades],
            monthly_returns=monthly_returns,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _fetch_ohlcv(symbol: str, start: str, end: str, timeframe: str) -> pd.DataFrame:
        """Fetch OHLCV via yfinance (existing market-data infrastructure)."""
        import yfinance as yf
        tf = TIMEFRAME_MAP.get(timeframe, "1d")
        df = yf.download(symbol, start=start, end=end, interval=tf, auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df = df.dropna(how="all")
        return df

    @staticmethod
    def _close_trade(
        pos: dict,
        exit_price: float,
        exit_date: date,
        exec_sim: ExecutionSimulator,
        reason: str,
    ) -> QuantTrade:
        shares = pos["shares"]
        fill   = exec_sim.simulate_exit(exit_price, shares)
        direction = pos["direction"]

        if direction == "LONG":
            gross_pnl = (fill.price - pos["entry_price"]) * shares
        else:
            gross_pnl = (pos["entry_price"] - fill.price) * shares

        total_commission = pos["commission_paid"] + fill.commission
        net_pnl  = gross_pnl - total_commission
        pnl_pct  = net_pnl / (pos["entry_price"] * shares)
        hold_days = (exit_date - pos["entry_date"]).days

        return QuantTrade(
            id=pos["id"],
            entry_date=pos["entry_date"],
            exit_date=exit_date,
            entry_price=pos["entry_price"],
            exit_price=fill.price,
            shares=shares,
            direction=direction,
            exit_reason=reason,
            pnl=net_pnl,
            pnl_pct=pnl_pct,
            commission_paid=total_commission,
            hold_days=hold_days,
            mfe=pos.get("mfe", 0.0),
            mae=pos.get("mae", 0.0),
        )

    @staticmethod
    def _compute_monthly_returns(eq: pd.Series) -> list[dict]:
        if eq.empty:
            return []
        try:
            monthly = eq.resample("ME").last()
            pct = monthly.pct_change().dropna()
            result = []
            for ts, val in pct.items():
                d = ts if isinstance(ts, (date, datetime)) else pd.Timestamp(ts)
                result.append({
                    "year":       d.year if hasattr(d, "year") else int(str(d)[:4]),
                    "month":      d.month if hasattr(d, "month") else int(str(d)[5:7]),
                    "return_pct": round(float(val) * 100, 4),
                })
            return result
        except Exception:
            return []
