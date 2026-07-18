"""
Strategy Comparison — our real equity signal engine vs. simple rule-based
baselines (Buy & Hold, SMA cross, RSI threshold, MACD cross) over one
symbol's price history.

Pure module — no DB, no broker. Read-only research tool, not an execution
path. All five models share one position simulator (long/flat only, buy on
BUY when flat, close on SELL when long) so the comparison is about signal
quality, not execution sophistication: only the signal source differs
between models.

Indicators are computed over the full fetched history so early bars in the
requested window aren't warmup-starved (the same class of bug fixed
elsewhere this session for the live scanner — see equity_scan_engine.py),
but no model is allowed to act (buy/sell) before the requested start date —
each one starts flat exactly at the window's first bar.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd

from app.utils.metrics import calculate_all_metrics

STARTING_CAPITAL_DEFAULT = 25000.0


@dataclass
class Trade:
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    pnl: float
    hold_days: int


def _load_daily_bars(symbol: str) -> pd.DataFrame:
    """Fetch ~3y of daily bars — generous warmup margin for any reasonable
    requested date range, matching the pattern in forecasts.py."""
    import yfinance as yf

    history = yf.Ticker(symbol).history(period="3y", auto_adjust=True)
    if history.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    history = history.rename(columns=str.lower)
    history = history[["open", "high", "low", "close", "volume"]].dropna()
    history = history[(history["close"] > 0) & (history["high"] > 0) & (history["low"] > 0)]
    if history.index.tz is not None:
        history.index = history.index.tz_localize(None)
    return history


def simulate_positions(
    dates: list[str], closes: list[float], actions: list[str],
    starting_capital: float = STARTING_CAPITAL_DEFAULT,
) -> tuple[list[Trade], list[float]]:
    """
    Long/flat simulator shared by every model: BUY opens a position (if flat),
    SELL closes it (if long), HOLD is a no-op. Equity is marked to market
    every bar. A position still open at the last bar is force-closed there so
    Buy & Hold (which never sells) still produces a realized trade for the
    metrics — otherwise calculate_all_metrics would see zero trades and
    report a flat 0% return despite the equity curve having moved.
    """
    trades: list[Trade] = []
    equity_curve: list[float] = []
    cash = starting_capital
    shares = 0.0
    position_open = False
    entry_price = 0.0
    entry_date = ""
    entry_idx = 0
    cash_before_entry = starting_capital

    for i, (d, price, action) in enumerate(zip(dates, closes, actions)):
        if not position_open and action == "BUY" and price > 0:
            shares = cash / price
            entry_price = price
            entry_date = d
            entry_idx = i
            cash_before_entry = cash
            cash = 0.0
            position_open = True
        elif position_open and action == "SELL":
            exit_cash = shares * price
            trades.append(Trade(
                entry_date=entry_date, exit_date=d,
                entry_price=entry_price, exit_price=price,
                pnl=exit_cash - cash_before_entry, hold_days=i - entry_idx,
            ))
            cash = exit_cash
            shares = 0.0
            position_open = False

        equity_curve.append(cash + shares * price)

    if position_open and dates:
        final_price = closes[-1]
        exit_cash = shares * final_price
        trades.append(Trade(
            entry_date=entry_date, exit_date=dates[-1],
            entry_price=entry_price, exit_price=final_price,
            pnl=exit_cash - cash_before_entry, hold_days=len(dates) - 1 - entry_idx,
        ))

    return trades, equity_curve


# ── Baseline signal generators ───────────────────────────────────────────────
# Each returns one action per bar of the FULL series (for alignment), but only
# bars from start_idx onward can be non-HOLD — every model starts flat at the
# window's first bar, regardless of what it would have done earlier.

def _buy_and_hold_actions(n: int, start_idx: int) -> list[str]:
    actions = ["HOLD"] * n
    if start_idx < n:
        actions[start_idx] = "BUY"
    return actions


def _cross_actions(indicator_above: pd.Series, start_idx: int) -> list[str]:
    """Shared cross-detection state machine for SMA/MACD: BUY when the series
    crosses from below to above its reference, SELL on the reverse cross.
    Only starts tracking state at start_idx (flat entering the window)."""
    n = len(indicator_above)
    actions = ["HOLD"] * n
    prev_above: Optional[bool] = None
    for i in range(start_idx, n):
        a = indicator_above.iloc[i]
        if pd.isna(a):
            prev_above = None
            continue
        if prev_above is None:
            pass  # first usable bar — nothing to compare against yet
        elif a and not prev_above:
            actions[i] = "BUY"
        elif not a and prev_above:
            actions[i] = "SELL"
        prev_above = bool(a)
    return actions


def _sma_cross_actions(close: pd.Series, start_idx: int, window: int = 20) -> list[str]:
    sma = close.rolling(window=window).mean()
    return _cross_actions(close > sma, start_idx)


def _macd_cross_actions(close: pd.Series, start_idx: int) -> list[str]:
    from ta.trend import MACD
    macd_obj = MACD(close=close, window_fast=12, window_slow=26, window_sign=9)
    return _cross_actions(macd_obj.macd() > macd_obj.macd_signal(), start_idx)


def _rsi_threshold_actions(
    close: pd.Series, start_idx: int, period: int = 14,
    buy_below: float = 30.0, sell_above: float = 70.0,
) -> list[str]:
    """Mean-reversion baseline: buy when RSI drops below buy_below (oversold),
    sell when it rises above sell_above (overbought). Wilder's RSI, same math
    as data_fetcher.py::calculate_rsi."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    n = len(close)
    actions = ["HOLD"] * n
    in_position = False
    for i in range(start_idx, n):
        r = rsi.iloc[i]
        if pd.isna(r):
            continue
        if not in_position and r < buy_below:
            actions[i] = "BUY"
            in_position = True
        elif in_position and r > sell_above:
            actions[i] = "SELL"
            in_position = False
    return actions


def _ours_actions(df: pd.DataFrame, start_idx: int, end_idx: int) -> list[str]:
    """Delegates to the real production signal engine (equity_signal_engine.py)
    run bar-by-bar on an expanding window — this is what our system would
    actually have said historically, not a reimplementation."""
    from app.services.equity_signal_engine import compute_indicators, score_equity_signal

    actions = []
    for i in range(start_idx, end_idx + 1):
        window = df.iloc[: i + 1]
        if len(window) < 30:
            actions.append("HOLD")
            continue
        ind = compute_indicators(window)
        if not ind:
            actions.append("HOLD")
            continue
        action, _confidence, _reasons = score_equity_signal(ind)
        actions.append(action if action in ("BUY", "SELL") else "HOLD")
    return actions


MODEL_NAMES = ("Buy & Hold", "SMA Cross", "RSI Threshold", "MACD Cross", "Ours")


def _model_actions(name: str, full_df: pd.DataFrame, start_idx: int, end_idx: int) -> list[str]:
    close = full_df["close"]
    if name == "Buy & Hold":
        return _buy_and_hold_actions(len(full_df), start_idx)[start_idx:end_idx + 1]
    if name == "SMA Cross":
        return _sma_cross_actions(close, start_idx)[start_idx:end_idx + 1]
    if name == "RSI Threshold":
        return _rsi_threshold_actions(close, start_idx)[start_idx:end_idx + 1]
    if name == "MACD Cross":
        return _macd_cross_actions(close, start_idx)[start_idx:end_idx + 1]
    if name == "Ours":
        return _ours_actions(full_df, start_idx, end_idx)
    raise ValueError(f"unknown model {name!r}")


def generate_comparison(
    symbol: str, start: str, end: str,
    starting_capital: float = STARTING_CAPITAL_DEFAULT,
) -> dict:
    """Run all MODEL_NAMES over [start, end] for `symbol` and return a
    comparison report: metrics table + per-model trades/equity curve."""
    ticker = symbol.strip().upper()
    if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
        raise ValueError("invalid symbol")

    full_df = _load_daily_bars(ticker)
    if full_df.empty:
        raise ValueError(f"no price history available for {ticker}")

    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    in_window = (full_df.index >= start_ts) & (full_df.index <= end_ts)
    if int(in_window.sum()) < 30:
        raise ValueError("date range must include at least 30 trading days")

    window_positions = np.flatnonzero(in_window)
    start_idx, end_idx = int(window_positions[0]), int(window_positions[-1])
    if start_idx < 1:
        raise ValueError("not enough price history before the start date for indicator warmup")

    dates = [d.date().isoformat() for d in full_df.index[start_idx:end_idx + 1]]
    closes = full_df["close"].iloc[start_idx:end_idx + 1].tolist()

    models = []
    for name in MODEL_NAMES:
        actions = _model_actions(name, full_df, start_idx, end_idx)
        trades, equity_curve = simulate_positions(dates, closes, actions, starting_capital)

        pnl_series = [t.pnl for t in trades]
        hold_days = [t.hold_days for t in trades]
        metrics = calculate_all_metrics(
            pnl_series=pnl_series, hold_days=hold_days,
            starting_capital=starting_capital, total_commissions=0.0,
            equity_curve=pd.Series(equity_curve),
        )

        markers = (
            [{"date": t.entry_date, "action": "BUY", "price": t.entry_price} for t in trades]
            + [{"date": t.exit_date, "action": "SELL", "price": t.exit_price} for t in trades]
        )
        markers.sort(key=lambda m: m["date"])

        models.append({
            "name": name,
            "metrics": {
                "cumulative_return_pct": round(metrics.total_return_pct * 100, 2),
                "annual_return_pct": round(metrics.annualized_return_pct * 100, 2),
                "sharpe_ratio": metrics.sharpe_ratio,
                "max_drawdown_pct": round(metrics.max_drawdown_pct * 100, 2),
            },
            "trades": [asdict(t) for t in trades],
            "markers": markers,
            "equity_curve": [{"date": d, "value": round(v, 2)} for d, v in zip(dates, equity_curve)],
        })

    return {
        "symbol": ticker,
        "start": dates[0],
        "end": dates[-1],
        "starting_capital": starting_capital,
        "bars": [{"date": d, "close": c} for d, c in zip(dates, closes)],
        "models": models,
        "disclaimer": "Research only — no execution path. Long/flat simulation, no commissions or slippage modeled.",
    }
