"""
Composable strategy engine ("symphonies") — Composer-style, for retail.

A strategy is a JSON tree of nodes that evaluates to target portfolio weights
{ticker: weight}. The SAME tree powers instant backtests and live rebalancing, so
a user can compose any rules-based strategy without writing code.

Node types
----------
- {"type": "asset", "ticker": "SPY"}
- {"type": "weight_equal", "children": [...]}
- {"type": "weight_specified", "weights": [0.6, 0.4], "children": [...]}
- {"type": "weight_inverse_vol", "window": 20, "children": [...]}
- {"type": "if", "condition": {...}, "then": <node>, "else": <node>}
- {"type": "filter", "select": "top"|"bottom", "n": 2,
   "by": {"fn": "cumulative_return", "window": 90}, "children": [...]}

Condition
---------
{"lhs": {"fn": "rsi", "ticker": "SPY", "window": 10}, "op": ">", "rhs": 80}
(rhs may be a number or another indicator spec.)

Indicators: rsi, sma, ema, price, cumulative_return, volatility, max_drawdown.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


class StrategyError(Exception):
    """Raised when a strategy tree is malformed or can't be evaluated."""


# ── Indicators (operate on a chronological close Series, as-of last element) ────
def _rsi(s: pd.Series, window: int) -> float:
    delta = s.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    val = rsi.iloc[-1]
    return float(val) if val == val else 50.0  # NaN → neutral


def _sma(s: pd.Series, window: int) -> float:
    return float(s.tail(window).mean())


def _ema(s: pd.Series, window: int) -> float:
    return float(s.ewm(span=window, adjust=False).mean().iloc[-1])


def _price(s: pd.Series, window: int = 0) -> float:
    return float(s.iloc[-1])


def _cumulative_return(s: pd.Series, window: int) -> float:
    if len(s) <= window:
        window = len(s) - 1
    if window <= 0:
        return 0.0
    return float(s.iloc[-1] / s.iloc[-1 - window] - 1.0)


def _volatility(s: pd.Series, window: int) -> float:
    rets = s.pct_change().tail(window)
    v = rets.std() * np.sqrt(252)
    return float(v) if v == v else 0.0


def _max_drawdown(s: pd.Series, window: int) -> float:
    w = s.tail(window)
    peak = w.cummax()
    dd = (w / peak - 1.0).min()
    return float(abs(dd)) if dd == dd else 0.0


_INDICATORS = {
    "rsi": _rsi, "sma": _sma, "ema": _ema, "price": _price,
    "current_price": _price, "cumulative_return": _cumulative_return,
    "cum_return": _cumulative_return, "volatility": _volatility,
    "max_drawdown": _max_drawdown,
}

_OPS = {
    ">": lambda a, b: a > b, "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b, "!=": lambda a, b: a != b,
}


def _series(data: dict[str, pd.Series], ticker: str) -> pd.Series:
    s = data.get(ticker)
    if s is None:
        raise StrategyError(f"no price data for ticker '{ticker}'")
    s = s.dropna()
    if s.empty:
        raise StrategyError(f"empty price series for ticker '{ticker}'")
    return s


def _eval_indicator(spec: dict, data: dict[str, pd.Series]) -> float:
    fn = spec.get("fn")
    if fn not in _INDICATORS:
        raise StrategyError(f"unknown indicator '{fn}'")
    s = _series(data, spec.get("ticker"))
    window = int(spec.get("window", 14))
    return _INDICATORS[fn](s, window)


def _eval_condition(cond: dict, data: dict[str, pd.Series]) -> bool:
    if "lhs" not in cond or "op" not in cond or "rhs" not in cond:
        raise StrategyError("condition needs lhs, op, rhs")
    lhs = _eval_indicator(cond["lhs"], data)
    rhs = cond["rhs"]
    rhs_val = _eval_indicator(rhs, data) if isinstance(rhs, dict) else float(rhs)
    op = cond["op"]
    if op not in _OPS:
        raise StrategyError(f"unknown operator '{op}'")
    return bool(_OPS[op](lhs, rhs_val))


def _primary_ticker(weights: dict[str, float]) -> str | None:
    """The dominant ticker in a sub-result — used to rank/weight composite children."""
    return max(weights, key=weights.get) if weights else None


def collect_tickers(node: Any, acc: set[str] | None = None) -> set[str]:
    """All tickers referenced anywhere in the tree (assets + condition indicators)."""
    acc = acc if acc is not None else set()
    if not isinstance(node, dict):
        return acc
    t = node.get("type")
    if t == "asset" and node.get("ticker"):
        acc.add(node["ticker"])
    for key in ("then", "else"):
        if isinstance(node.get(key), dict):
            collect_tickers(node[key], acc)
    for child in node.get("children", []) or []:
        collect_tickers(child, acc)
    cond = node.get("condition")
    if isinstance(cond, dict):
        for side in ("lhs", "rhs"):
            if isinstance(cond.get(side), dict) and cond[side].get("ticker"):
                acc.add(cond[side]["ticker"])
    by = node.get("by")
    if isinstance(by, dict) and by.get("ticker"):
        acc.add(by["ticker"])
    return acc


def _combine(subs: list[dict[str, float]], weights: list[float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for d, w in zip(subs, weights):
        for k, v in d.items():
            out[k] = out.get(k, 0.0) + v * w
    return out


def evaluate(node: Any, data: dict[str, pd.Series]) -> dict[str, float]:
    """Evaluate a strategy tree against as-of price data → {ticker: weight}."""
    if not isinstance(node, dict) or "type" not in node:
        raise StrategyError("each node must be an object with a 'type'")
    t = node["type"]

    if t == "asset":
        if not node.get("ticker"):
            raise StrategyError("asset node needs a 'ticker'")
        return {node["ticker"]: 1.0}

    if t == "if":
        chosen = node.get("then") if _eval_condition(node.get("condition", {}), data) \
                 else node.get("else")
        return evaluate(chosen, data) if chosen else {}

    children = node.get("children") or []
    if t in ("weight_equal", "group"):
        if not children:
            raise StrategyError("weight_equal needs children")
        subs = [evaluate(c, data) for c in children]
        return _combine(subs, [1.0 / len(subs)] * len(subs))

    if t == "weight_specified":
        ws = node.get("weights") or []
        if len(ws) != len(children) or not children:
            raise StrategyError("weight_specified needs matching weights & children")
        subs = [evaluate(c, data) for c in children]
        return _combine(subs, [float(w) for w in ws])

    if t == "weight_inverse_vol":
        if not children:
            raise StrategyError("weight_inverse_vol needs children")
        window = int(node.get("window", 20))
        subs = [evaluate(c, data) for c in children]
        invs = []
        for sub in subs:
            tk = _primary_ticker(sub)
            try:
                vol = _volatility(_series(data, tk), window) if tk else 0.0
            except StrategyError:
                vol = 0.0
            invs.append(1.0 / vol if vol > 1e-9 else 0.0)
        total = sum(invs)
        if total <= 0:
            return _combine(subs, [1.0 / len(subs)] * len(subs))
        return _combine(subs, [iv / total for iv in invs])

    if t == "filter":
        if not children:
            raise StrategyError("filter needs children")
        by = node.get("by")
        if not isinstance(by, dict):
            raise StrategyError("filter needs a 'by' indicator spec")
        n = int(node.get("n", 1))
        select = node.get("select", "top")
        ranked = []
        for c in children:
            sub = evaluate(c, data)
            tk = _primary_ticker(sub)
            spec = {**by, "ticker": tk}
            try:
                score = _eval_indicator(spec, data) if tk else float("-inf")
            except StrategyError:
                score = float("-inf")
            ranked.append((score, sub))
        ranked.sort(key=lambda x: x[0], reverse=(select == "top"))
        picked = [sub for _, sub in ranked[:max(1, n)]]
        if not picked:
            return {}
        return _combine(picked, [1.0 / len(picked)] * len(picked))

    raise StrategyError(f"unknown node type '{t}'")


def normalize(weights: dict[str, float]) -> dict[str, float]:
    """Drop zeros/negatives and scale to sum to 1.0."""
    pos = {k: v for k, v in weights.items() if v > 1e-9}
    total = sum(pos.values())
    if total <= 0:
        return {}
    return {k: round(v / total, 6) for k, v in pos.items()}


# ── Backtest ───────────────────────────────────────────────────────────────────
def _rebalance_due(d: pd.Timestamp, last: pd.Timestamp | None, cadence: str) -> bool:
    if last is None:
        return True
    if cadence == "daily":
        return d.date() != last.date()
    if cadence == "weekly":
        return d.isocalendar().week != last.isocalendar().week or d.year != last.year
    if cadence == "monthly":
        return (d.year, d.month) != (last.year, last.month)
    return d.date() != last.date()


def _metrics(values: list[float]) -> dict:
    if len(values) < 2:
        return {"total_return_pct": 0.0, "cagr_pct": 0.0, "max_drawdown_pct": 0.0,
                "sharpe": 0.0, "volatility_pct": 0.0}
    arr = np.array(values, dtype=float)
    total_return = arr[-1] / arr[0] - 1.0
    years = max(len(arr) / 252.0, 1e-9)
    cagr = (arr[-1] / arr[0]) ** (1 / years) - 1.0 if arr[0] > 0 else 0.0
    daily = np.diff(arr) / arr[:-1]
    vol = float(np.std(daily) * np.sqrt(252)) if len(daily) else 0.0
    sharpe = float(np.mean(daily) / np.std(daily) * np.sqrt(252)) if np.std(daily) > 1e-12 else 0.0
    peak = np.maximum.accumulate(arr)
    max_dd = float(np.min(arr / peak - 1.0))
    return {
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(abs(max_dd) * 100, 2),
        "sharpe": round(sharpe, 2),
        "volatility_pct": round(vol * 100, 2),
    }


def run_backtest(
    strategy: dict,
    closes: pd.DataFrame,
    start_date,
    end_date,
    cadence: str = "weekly",
    starting_capital: float = 10000.0,
) -> dict:
    """
    Replay the strategy over `closes` (index=DatetimeIndex, columns=tickers).
    Weights are decided from data through each rebalance day and applied the NEXT
    day onward (no look-ahead). Returns equity curve + metrics + final weights.
    """
    closes = closes.sort_index().ffill()
    rets = closes.pct_change().fillna(0.0)
    tickers = list(closes.columns)

    in_window = [d for d in closes.index
                 if start_date <= d.date() <= end_date]
    if len(in_window) < 2:
        raise StrategyError("not enough price history in the requested window")

    equity = float(starting_capital)
    weights: dict[str, float] = {}
    last_rebal: pd.Timestamp | None = None
    curve: list[dict] = []
    rebalances = 0

    for i, d in enumerate(in_window):
        if i > 0 and weights:
            port_ret = sum(weights.get(t, 0.0) * float(rets.at[d, t])
                           for t in weights if t in rets.columns)
            equity *= (1.0 + port_ret)
        curve.append({"date": d.date().isoformat(), "value": round(equity, 2)})

        if _rebalance_due(d, last_rebal, cadence):
            asof = {t: closes[t].loc[:d] for t in tickers}
            try:
                weights = normalize(evaluate(strategy, asof))
                rebalances += 1
            except StrategyError:
                pass  # keep prior weights if a rebalance can't evaluate (e.g. warmup)
            last_rebal = d

    return {
        "equity_curve": curve,
        "final_weights": weights,
        "rebalances": rebalances,
        "metrics": _metrics([c["value"] for c in curve]),
    }


# ── Example strategies ──────────────────────────────────────────────────────────
def example_strategies() -> list[dict]:
    return [
        {
            "name": "Risk-On / Risk-Off (SPY vs Bonds)",
            "description": "Hold SPY while it's above its 200-day average; rotate to "
                           "long-term treasuries (TLT) when it drops below.",
            "cadence": "weekly",
            "tree": {
                "type": "if",
                "condition": {"lhs": {"fn": "price", "ticker": "SPY"},
                              "op": ">", "rhs": {"fn": "sma", "ticker": "SPY", "window": 200}},
                "then": {"type": "asset", "ticker": "SPY"},
                "else": {"type": "asset", "ticker": "TLT"},
            },
        },
        {
            "name": "Top-2 Momentum (Mega-cap Tech)",
            "description": "Each week hold the 2 strongest of AAPL/MSFT/NVDA/AMZN/GOOGL "
                           "by 90-day return, equal-weighted.",
            "cadence": "weekly",
            "tree": {
                "type": "filter", "select": "top", "n": 2,
                "by": {"fn": "cumulative_return", "window": 90},
                "children": [
                    {"type": "asset", "ticker": "AAPL"},
                    {"type": "asset", "ticker": "MSFT"},
                    {"type": "asset", "ticker": "NVDA"},
                    {"type": "asset", "ticker": "AMZN"},
                    {"type": "asset", "ticker": "GOOGL"},
                ],
            },
        },
        {
            "name": "RSI Mean-Reversion with Cash Defense",
            "description": "If SPY RSI(10) is overbought (>75) go to cash (BIL), "
                           "otherwise hold a risk-parity-style SPY/TLT/GLD by inverse vol.",
            "cadence": "daily",
            "tree": {
                "type": "if",
                "condition": {"lhs": {"fn": "rsi", "ticker": "SPY", "window": 10},
                              "op": ">", "rhs": 75},
                "then": {"type": "asset", "ticker": "BIL"},
                "else": {
                    "type": "weight_inverse_vol", "window": 20,
                    "children": [
                        {"type": "asset", "ticker": "SPY"},
                        {"type": "asset", "ticker": "TLT"},
                        {"type": "asset", "ticker": "GLD"},
                    ],
                },
            },
        },
    ]
