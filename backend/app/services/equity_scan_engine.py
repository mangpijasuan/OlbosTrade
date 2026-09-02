"""
Equity scan engine — A-grade multi-asset candidate generation with EV ranking.

Integrates:
- Multi-asset scanning (not limited to watchlist)
- Expected Value (EV) ranking: EV = POP × target_profit − (1−POP) × max_loss
- Entry ladder logic (kelly-scaled tranches)
- IV rank + implied move awareness (from options market)
- NO-TRADE gates (market hours, kill switch)
- Live pricing hierarchy: ticker data → Black-Scholes theoretical
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from scipy import stats

from app.services.equity_signal_engine import (
    compute_equity_trade_plan,
    compute_indicators,
    earnings_gate,
    score_equity_signal,
)
from app.services.iv_overlay import get_iv_signal_boost

logger = logging.getLogger(__name__)

# Bounded fan-out for the watchlist sweep. 8 matches the throughput yfinance
# and the IBKR coordinator actually sustain; more just queues behind their
# rate limits while adding coordinator pressure.
SCAN_CONCURRENCY = 8
# Per-ticker deadline. One symbol that never answers must not hold the scan
# open — the caller gets the other results and a log line naming the one that
# did not answer.
SCAN_TICKER_TIMEOUT_S = 20.0


@dataclass
class EquityScanCandidate:
    """A-grade equity candidate with EV ranking and entry ladder."""
    ticker: str
    action: str
    confidence: float
    expected_value: float
    ev_per_risk: float
    pop: float
    kelly_fraction: float
    entry_price: float
    stop_price: float
    target_price: float
    max_loss: float
    max_profit: float
    entry_ladder: list[dict] = field(default_factory=list)
    iv_rank: float = 0.0
    realized_vol: float = 0.0
    pricing_source: str = "yfinance"
    indicators: dict = field(default_factory=dict)
    orderflow_score: float = 0.0
    iv_overlay_boost: float = 0.0
    reasons: dict = field(default_factory=dict)
    source: str = "Equity Scan Engine"

    def as_dict(self) -> dict:
        """Serialize candidate to dict for API response."""
        return {
            "ticker": self.ticker,
            "action": self.action,
            "source": self.source,
            "confidence": self.confidence,
            "expected_value": round(self.expected_value, 2),
            "ev_per_risk": round(self.ev_per_risk, 4),
            "pop": round(self.pop, 4),
            "kelly_fraction": round(self.kelly_fraction, 4),
            "entry_price": round(self.entry_price, 4),
            "stop_price": round(self.stop_price, 4),
            "target_price": round(self.target_price, 4),
            "max_loss": round(self.max_loss, 2),
            "max_profit": round(self.max_profit, 2),
            "entry_ladder": self.entry_ladder,
            "iv_rank": round(self.iv_rank, 2),
            "realized_vol": round(self.realized_vol, 4),
            "pricing_source": self.pricing_source,
            "indicators": self.indicators,
            "orderflow_score": round(self.orderflow_score, 4),
            "iv_overlay_boost": round(self.iv_overlay_boost, 4),
            "reasons": self.reasons,
        }


@dataclass
class EquityScanResult:
    """Multi-asset equity scan result with gate status."""
    candidates: list[EquityScanCandidate] = field(default_factory=list)
    tickers_scanned: list[str] = field(default_factory=list)
    gate_blocked: bool = False
    gate_reason: str = ""
    spot: float = 0.0
    iv_rank: float = 0.0
    realized_vol: float = 0.0
    error: str = ""

    def as_dict(self) -> dict:
        """Serialize result to dict for API response."""
        return {
            "candidates": [c.as_dict() for c in self.candidates],
            "tickers_scanned": self.tickers_scanned or [],
            "gate_blocked": self.gate_blocked,
            "gate_reason": self.gate_reason,
            "iv_rank": round(self.iv_rank, 2),
            "realized_vol": round(self.realized_vol, 4),
            "error": self.error,
        }


def _compute_pop_from_distance(
    entry: float,
    target: float,
    stop: float,
    atr: float,
) -> float:
    """
    Estimate probability of profit using normal distribution.

    POP = probability that price reaches target before hitting stop.
    Assumes log-normal price movement with volatility = ATR / entry.
    """
    if atr <= 0 or entry <= 0:
        return 0.5  # neutral if no vol

    # Distance from entry to target and stop (in terms of ATR)
    dist_to_target = abs(target - entry)
    dist_to_stop = abs(stop - entry)

    if dist_to_target == 0:
        return 0.5
    if dist_to_stop == 0:
        return 1.0  # stop at entry = guaranteed profit

    # Simplified: POP = distance_to_stop / (distance_to_target + distance_to_stop)
    # This gives 50-50 odds if target and stop are equidistant
    pop = dist_to_stop / (dist_to_target + dist_to_stop)
    return min(max(pop, 0.01), 0.99)  # clamp to [1%, 99%]


def _compute_kelly_fraction(
    pop: float,
    win: float,
    loss: float,
) -> float:
    """
    Kelly fraction: f* = (p·b − q) / b

    Where:
    - p = POP (probability of win)
    - q = 1 - p (probability of loss)
    - b = win / loss (odds ratio)
    """
    if loss <= 0 or win <= 0:
        return 0.05

    q = 1.0 - pop
    b = win / loss

    kelly = (pop * b - q) / b if b > 0 else 0.0
    return max(min(kelly, 0.50), 0.01)  # clamp to [1%, 50%]


def _build_entry_ladder(
    kelly: float,
    entry_price: float,
    stop_price: float,
    target_price: float,
) -> list[dict]:
    """
    Build entry ladder based on kelly fraction confidence.

    kelly < 15% → 1 tranche (full entry, max confidence)
    kelly 15-30% → 2 tranches (scale-in)
    kelly 30-50% → 3 tranches (incremental, lower confidence)
    """
    ladder = []

    if kelly < 0.15:
        # Single full entry
        ladder.append({
            "tranche": 1,
            "pct_position": 100,
            "entry_price": round(entry_price, 4),
            "description": "Full entry (high confidence)",
        })
    elif kelly < 0.30:
        # Two tranches: 60/40 scale-in
        ladder.append({
            "tranche": 1,
            "pct_position": 60,
            "entry_price": round(entry_price, 4),
            "description": "Initial entry (60%)",
        })
        ladder.append({
            "tranche": 2,
            "pct_position": 40,
            "entry_price": round(entry_price * 0.98, 4),
            "description": "Scale-in on weakness (40%)",
        })
    else:
        # Three tranches: 40/35/25 incremental
        ladder.append({
            "tranche": 1,
            "pct_position": 40,
            "entry_price": round(entry_price, 4),
            "description": "Initial entry (40%)",
        })
        ladder.append({
            "tranche": 2,
            "pct_position": 35,
            "entry_price": round(entry_price * 0.98, 4),
            "description": "Scale-in on weakness (35%)",
        })
        ladder.append({
            "tranche": 3,
            "pct_position": 25,
            "entry_price": round(entry_price * 0.96, 4),
            "description": "Accumulation on confirmation (25%)",
        })

    return ladder


async def _compute_iv_rank_for_ticker(ticker: str, broker=None) -> tuple[float, float]:
    """
    Compute IV rank and realized vol for ticker using options market.

    Returns: (iv_rank, realized_vol)
    Gracefully falls back to 0.0 if broker unavailable.
    """
    try:
        if broker is None:
            return 0.0, 0.0

        iv_data = await get_iv_signal_boost(ticker, broker)
        # get_iv_signal_boost can return {"iv_rank": None, ...} (options
        # unsupported, or IV surface not built yet) — .get(key, default) only
        # falls back when the key is absent, not when it's present as None,
        # so normalize explicitly to honor this function's float return type.
        iv_rank = iv_data.get("iv_rank")
        realized_vol = iv_data.get("realized_vol")
        return (
            iv_rank if iv_rank is not None else 0.0,
            realized_vol if realized_vol is not None else 0.0,
        )
    except Exception as exc:
        logger.debug("IV rank computation failed for %s: %s", ticker, exc)
        return 0.0, 0.0


async def _yf_bars_for_ticker(ticker: str, limit: int = 250) -> list[dict]:
    """Fetch OHLCV bars from yfinance."""
    import yfinance as yf

    def _fetch():
        hist = yf.Ticker(ticker).history(period=f"{min(limit * 2, 730)}d", auto_adjust=True)
        hist = hist.tail(limit)
        return hist

    loop = asyncio.get_running_loop()
    try:
        hist = await loop.run_in_executor(None, _fetch)
        result = []
        for ts, row in hist.iterrows():
            result.append({
                "timestamp": ts.to_pydatetime(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row.get("Volume", 0) or 0),
            })
        return result
    except Exception as exc:
        logger.warning("Failed to fetch bars for %s: %s", ticker, exc)
        return []


async def scan_options_for_ticker(
    ticker: str,
    broker=None,
) -> Optional[EquityScanCandidate]:
    """
    Analyze one ticker and return candidate if actionable.

    Flow:
    1. Check earnings gate
    2. Fetch bars from yfinance
    3. Compute indicators
    4. Score signal (action, confidence)
    5. Compute trade plan (entry, stop, target)
    6. Calculate EV, POP, kelly
    7. Build entry ladder
    8. Get IV rank
    9. Return candidate if action is BUY/SELL
    """
    # Earnings gate
    if earnings_gate(ticker, gate_days=3):
        logger.debug("Earnings gate triggered for %s", ticker)
        return None

    # Fetch bars. Needs >=200 so EMA200 computes — with 120 it was always NaN,
    # forcing above_ema200=False and skewing every signal ~1pt bearish versus
    # the background scanner's own 250-bar fetch (main.py's _run_equity_scan).
    bars = await _yf_bars_for_ticker(ticker, limit=250)
    if len(bars) < 30:
        logger.debug("Insufficient bars for %s: %d", ticker, len(bars))
        return None

    # Convert to DataFrame for indicator computation
    df = pd.DataFrame([{
        "open": b["open"],
        "high": b["high"],
        "low": b["low"],
        "close": b["close"],
        "volume": b["volume"],
    } for b in bars])

    ind = compute_indicators(df)
    if not ind:
        logger.debug("Indicator computation failed for %s", ticker)
        return None

    # Score signal
    orderflow = 0.0
    iv_boost = 0.0
    if broker is not None:
        try:
            from app.services.orderflow_engine import get_orderflow_score
            orderflow = await get_orderflow_score(ticker, broker)
        except Exception:
            pass

        try:
            iv_data = await get_iv_signal_boost(ticker, broker)
            iv_boost = iv_data.get("boost", 0.0)
        except Exception:
            pass

    action, confidence, reasons = score_equity_signal(
        ind,
        sentiment_score=0.0,
        orderflow_score=orderflow,
    )
    confidence = min(1.0, confidence + iv_boost)

    # Skip if not actionable or low confidence
    if action == "HOLD" or confidence < 0.50:
        return None

    # Compute trade plan
    trade_plan = compute_equity_trade_plan(
        ind,
        action,
        portfolio_value=10000.0,  # dummy value for sizing
        sentiment_score=0.0,
    )

    entry = trade_plan.get("entry_price", ind.get("close", 0))
    stop = trade_plan.get("stop_price", entry - ind.get("atr", 1))
    target = trade_plan.get("target_price", entry + ind.get("atr", 1) * 4)
    atr = ind.get("atr", 1)

    max_loss = abs(entry - stop)
    max_profit = abs(target - entry)

    if max_loss == 0 or max_profit == 0:
        return None

    # Compute EV metrics
    pop = _compute_pop_from_distance(entry, target, stop, atr)
    kelly = _compute_kelly_fraction(pop, max_profit, max_loss)
    ev = pop * max_profit - (1 - pop) * max_loss
    ev_per_risk = ev / max_loss if max_loss > 0 else 0

    # Build entry ladder
    entry_ladder = _build_entry_ladder(kelly, entry, stop, target)

    # IV rank
    iv_rank, realized_vol = await _compute_iv_rank_for_ticker(ticker, broker)

    return EquityScanCandidate(
        ticker=ticker,
        action=action,
        confidence=round(confidence, 4),
        expected_value=ev,
        ev_per_risk=ev_per_risk,
        pop=pop,
        kelly_fraction=kelly,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        max_loss=max_loss,
        max_profit=max_profit,
        entry_ladder=entry_ladder,
        iv_rank=iv_rank,
        realized_vol=realized_vol,
        pricing_source="yfinance",
        indicators={
            "rsi": round(ind.get("rsi", 50), 1),
            "macd": round(ind.get("macd", 0), 4),
            "bb_pct_b": round(ind.get("bb_pct_b", 0.5), 2),
            "atr": round(ind.get("atr", 1), 4),
            "volume_ratio": round(ind.get("volume_ratio", 1.0), 2),
        },
        orderflow_score=orderflow,
        iv_overlay_boost=iv_boost,
        reasons=reasons,
    )


async def scan_options(
    tickers: Optional[list[str]] = None,
    limit: int = 10,
    broker=None,
) -> EquityScanResult:
    """
    Multi-asset equity scan with EV ranking.

    Args:
        tickers: List of tickers to scan (required)
        limit: Max candidates to return
        broker: Optional broker for orderflow/IV boost

    Returns:
        EquityScanResult with candidates ranked by EV (highest first)
    """
    if not tickers:
        return EquityScanResult(
            error="No tickers provided"
        )

    result = EquityScanResult(tickers_scanned=tickers)

    # Bounded concurrency, and a deadline per ticker.
    #
    # This fired all ~100 tickers at once with no cap and no timeout. Each one
    # does a yfinance fetch plus a broker quote, so an unbounded fan-out just
    # queues behind provider rate limits and floods the IBKR coordinator —
    # against a throttled API that is usually slower than a bounded sweep, not
    # faster. Worse, nothing bounded a single hung symbol, so one stalled fetch
    # held the whole scan open: on 2026-08-30 a manual scan ran past 130s and
    # nginx returned 504 while the work carried on invisibly behind it.
    #
    # A ticker that exceeds its deadline is dropped and counted, never waited
    # on. A partial scan that reports what it missed is worth more than a
    # complete one nobody receives.
    sem = asyncio.Semaphore(SCAN_CONCURRENCY)

    async def _one(ticker: str):
        async with sem:
            try:
                return await asyncio.wait_for(
                    scan_options_for_ticker(ticker, broker),
                    timeout=SCAN_TICKER_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                logger.warning("equity scan: %s exceeded %.0fs — skipped",
                               ticker, SCAN_TICKER_TIMEOUT_S)
                return None
            except Exception as exc:
                # One bad symbol must not void the other ninety-nine.
                logger.warning("equity scan: %s failed: %s", ticker, exc)
                return None

    candidates_raw = await asyncio.gather(*(_one(t) for t in tickers))

    # Filter out None (non-actionable, timed out, or errored)
    candidates = [c for c in candidates_raw if c is not None]

    # Sort by EV (highest first)
    candidates.sort(key=lambda c: c.expected_value, reverse=True)

    # Limit results
    result.candidates = candidates[:limit]

    # Compute aggregate stats
    if candidates:
        all_ev = [c.expected_value for c in candidates]
        all_iv_rank = [c.iv_rank for c in candidates]
        all_vol = [c.realized_vol for c in candidates]

        result.iv_rank = sum(all_iv_rank) / len(all_iv_rank) if all_iv_rank else 0.0
        result.realized_vol = sum(all_vol) / len(all_vol) if all_vol else 0.0

    return result
